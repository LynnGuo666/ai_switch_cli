#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端内的简易 TUI 配置切换工具（curses）。

快捷键：
- ↑/↓/j     ：移动选择
- Enter     ：应用选中配置
- t         ：切换 AI 类型 (claude/codex)
- /         ：输入搜索关键字
- c         ：清除搜索
- a         ：添加自定义配置（输入 BASE_URL 和 KEY）
- k         ：使用自定义 Key 应用选中配置（保持 URL 不变）
- s         ：设置（状态站 URL）
- r         ：重新加载配置 / 刷新状态
- x         ：清空当前类型环境变量（仅本进程）
- X         ：清空当前类型环境变量并从 shell 配置移除
- q         ：退出
"""

from __future__ import annotations

import curses
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 默认状态站 URL
DEFAULT_HEALTH_URL = "https://check.linux.do/api/v1/status"
SETTINGS_FILE = Path(__file__).resolve().parent / ".tui_settings.json"
ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_dotenv():
    """加载 .env 文件中的环境变量。"""
    if not ENV_FILE.exists():
        return
    try:
        with ENV_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:  # 不覆盖已有环境变量
                        os.environ[key] = value
    except Exception:
        pass


# 启动时加载 .env
load_dotenv()


from core import config_loader, env_service


def load_settings() -> Dict:
    """加载用户设置。"""
    defaults = {
        "health_url": os.environ.get("HEALTH_STATUS_URL", DEFAULT_HEALTH_URL),
        "custom_configs": {"claude": [], "codex": []},
    }
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_settings(settings: Dict) -> None:
    """保存用户设置。"""
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ----------------- 健康检查拉取 -----------------
def normalize_health(data: Dict) -> Dict[str, List[Dict[str, str]]]:
    groups: Dict[str, List[Dict[str, str]]] = {}
    if not isinstance(data, dict):
        return groups

    def add_entry(entry: Dict[str, str]) -> None:
        grp = str(entry.get("group", "") or "")
        if not grp:
            grp = "unknown"
        groups.setdefault(grp, []).append(entry)

    def parse_timeline(item: Dict) -> List[str]:
        tl = item.get("timeline") or []
        if not isinstance(tl, list):
            return []
        statuses: List[str] = []
        for t in tl:
            if isinstance(t, dict):
                statuses.append(str(t.get("status", "unknown")))
        return statuses

    # services 结构
    if isinstance(data.get("services"), dict):
        for _, val in data["services"].items():
            if not isinstance(val, dict):
                continue
            add_entry({
                "status": str(val.get("status", "unknown")),
                "lastCheck": str(val.get("lastCheck", "")),
                "model": str(val.get("model", "")),
                "name": str(val.get("name", "")),
                "group": str(val.get("group", "")),
                "latency": str(val.get("latencyMs", "")),
                "timeline": parse_timeline(val),
            })

    # providers 结构
    if (not groups) and isinstance(data.get("providers"), list):
        for item in data["providers"]:
            if not isinstance(item, dict):
                continue
            latest = item.get("latest", {}) or {}
            add_entry({
                "status": str(latest.get("status", "unknown")),
                "lastCheck": str(latest.get("checkedAt", "")),
                "model": str(item.get("model", "")),
                "name": str(item.get("name", "")),
                "group": str(item.get("group", "")),
                "latency": str(latest.get("latencyMs", "")),
                "timeline": parse_timeline(item),
            })

    return groups


def fetch_health_status(url: str, timeout: int = 15) -> Tuple[Dict[str, List[Dict[str, str]]], str]:
    """获取渠道状态，返回 (map, error_msg)。优先使用 cloudscraper，回退到 requests。"""
    # 代理设置
    def get_proxy():
        for var in ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"]:
            proxy = os.environ.get(var)
            if proxy:
                return proxy
        return None

    proxy_url = get_proxy()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    # 尝试 cloudscraper
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        if proxies:
            scraper.proxies = proxies
        resp = scraper.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return normalize_health(data), ""
    except ImportError:
        pass
    except Exception:
        pass

    # 回退到 requests
    try:
        import requests
        resp = requests.get(url, proxies=proxies, timeout=timeout, verify=False,
                           headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        if resp.status_code == 200:
            data = resp.json()
            return normalize_health(data), ""
        return {}, f"HTTP {resp.status_code} (可能被 CF 盾拦截)"
    except ImportError:
        return {}, "请安装 requests 或 cloudscraper"
    except Exception as exc:
        return {}, str(exc)[:60]


class TUI:
    # 界面模式
    MODE_LIST = "list"
    MODE_SETTINGS = "settings"
    MODE_ADD_CUSTOM = "add_custom"
    MODE_CUSTOM_KEY = "custom_key"

    def __init__(self, stdscr: "curses._CursesWindow") -> None:
        self.stdscr = stdscr
        self.mode = self.MODE_LIST
        self.ai_type = "claude"
        self.search = ""
        self.configs: List[Dict] = []
        self.filtered_idx: List[int] = []
        self.selected = 0
        self.scroll_offset = 0
        self.messages: List[str] = []
        self.health_map: Dict[str, List[Dict[str, str]]] = {}
        self.settings = load_settings()

        # 异步状态获取
        self.health_loading = False
        self.health_error = ""
        self._health_thread: Optional[threading.Thread] = None

        # 设置界面状态
        self.settings_cursor = 0
        self.settings_editing = False
        self.settings_input = ""

        # 自定义配置输入状态
        self.custom_input_step = 0  # 0=base_url, 1=key, 2=name
        self.custom_input = {"base_url": "", "key": "", "name": ""}

        # 自定义 Key 输入状态
        self.custom_key_input = ""

        self._init_colors()
        self.load_configs()

    def _init_colors(self) -> None:
        curses.start_color()
        try:
            curses.use_default_colors()
        except Exception:
            pass
        curses.init_pair(1, curses.COLOR_WHITE, -1)    # 普通
        curses.init_pair(2, curses.COLOR_CYAN, -1)     # 当前配置
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)  # 选中
        curses.init_pair(4, curses.COLOR_YELLOW, -1)   # 标题/Claude
        curses.init_pair(5, curses.COLOR_GREEN, -1)    # ok/Codex
        curses.init_pair(6, curses.COLOR_RED, -1)      # error
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)  # timeout/warn
        curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_BLUE)  # 输入框

    def _msg(self, text: str) -> None:
        self.messages.append(text)
        if len(self.messages) > 50:
            self.messages = self.messages[-50:]

    def _mask_key(self, key: str) -> str:
        """脱敏显示 Key，保留前8位和后4位。"""
        if not key:
            return "(空)"
        if len(key) <= 16:
            return key[:4] + "***" + key[-2:] if len(key) > 6 else "***"
        return key[:8] + "***" + key[-4:]

    def _fmt_ago(self, ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            diff = (now - dt).total_seconds()
            if diff < 60:
                return f"{int(diff)}s前"
            if diff < 3600:
                return f"{int(diff/60)}m前"
            if diff < 86400:
                return f"{int(diff/3600)}h前"
            return f"{int(diff/86400)}d前"
        except Exception:
            return ts

    # ----------------- 数据加载 -----------------
    def refresh_health(self) -> None:
        """异步获取渠道状态。"""
        url = self.settings.get("health_url", DEFAULT_HEALTH_URL)
        if not url:
            self._msg("[跳过] 状态站 URL 为空")
            return

        # 如果已有线程在运行，不重复启动
        if self._health_thread and self._health_thread.is_alive():
            return

        self.health_loading = True
        self.health_error = ""
        self._msg("[状态] 正在获取...")

        def _fetch():
            health, err = fetch_health_status(url)
            self.health_map = health
            self.health_loading = False
            if err:
                self.health_error = err[:60]
                self._msg(f"[状态] 获取失败: {err[:60]}")
            elif not health:
                self._msg("[状态] 返回为空")
            else:
                self._msg(f"[状态] 已获取 {len(health)} 组")

        self._health_thread = threading.Thread(target=_fetch, daemon=True)
        self._health_thread.start()

    def load_configs(self) -> None:
        try:
            self.configs = config_loader.load_configs(self.ai_type)
            # 合并自定义配置
            custom = self.settings.get("custom_configs", {}).get(self.ai_type, [])
            for c in custom:
                c["_custom"] = True
            self.configs = self.configs + custom
            self._msg(f"[加载] {self.ai_type} 配置共 {len(self.configs)} 条")
            self.refresh_health()
        except Exception as exc:
            self.configs = []
            self._msg(f"[错误] {exc}")
        self.apply_filter()
        self.scroll_offset = 0

    def apply_filter(self) -> None:
        self.filtered_idx = []
        self.selected = 0
        key = self.search.lower()
        for i, cfg in enumerate(self.configs):
            text_blob = f"{cfg.get('name','')} {cfg.get('group','')}".lower()
            if key and key not in text_blob:
                continue
            self.filtered_idx.append(i)
        if not self.filtered_idx and self.search:
            self._msg("[搜索] 无匹配结果")
        self.scroll_offset = 0

    # ----------------- 状态相关 -----------------
    def _status_icon(self, status: str) -> Tuple[str, int]:
        status = (status or "unknown").lower()
        if status in ("ok", "operational"):
            return "●", 5
        if status == "error":
            return "●", 6
        if status in ("timeout", "degraded"):
            return "●", 7
        return "○", 1

    def _group_entries(self, cfg: Dict) -> List[Dict[str, str]]:
        group = str(cfg.get("group", "") or "")
        return self.health_map.get(group, []) if group else []

    def _choose_status(self, entries: List[Dict[str, str]]) -> Tuple[str, int]:
        if not entries:
            return "○", 1
        severity = {"error": 0, "timeout": 1, "failed": 1, "degraded": 2, "ok": 3, "operational": 3, "unknown": 4}
        best_st = "unknown"
        best_score = 99
        for e in entries:
            st = str(e.get("status", "unknown")).lower()
            score = severity.get(st, 99)
            if score < best_score:
                best_score = score
                best_st = st
        return self._status_icon(best_st)

    def get_status_for(self, real_idx: int) -> Tuple[str, int]:
        if real_idx >= len(self.configs):
            return "○", 1
        cfg = self.configs[real_idx]
        entries = self._group_entries(cfg)
        return self._choose_status(entries)

    def get_status_detail(self, real_idx: int | None) -> Tuple[List[str], int, List[str]]:
        if real_idx is None or real_idx >= len(self.configs):
            return ["未知"], 1, []
        cfg = self.configs[real_idx]
        entries = self._group_entries(cfg)
        if not entries:
            return ["无状态数据"], 1, []
        lines: List[str] = []
        timeline: List[str] = []
        for e in entries:
            icon, _ = self._status_icon(e.get("status"))
            tl = e.get("timeline") or []
            if tl and not timeline:
                timeline = tl
            ago = self._fmt_ago(e.get("lastCheck", ""))
            model = e.get("model") or e.get("name") or ""
            line = f"{icon} {model} {e.get('status','?')}"
            if ago:
                line += f" ({ago})"
            lines.append(line)
        _, color = self._choose_status(entries)
        return lines, color, timeline

    # ----------------- 当前环境 -----------------
    def current_env(self) -> Tuple[str, int | None]:
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_env = os.environ.get(cfg_map["env_token"], "")
        url_env = os.environ.get(cfg_map["env_url"], "")
        if not token_env and not url_env:
            return "未配置", None
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
        for i, cfg in enumerate(self.configs):
            if str(cfg.get(token_key, "") or "") == token_env and str(cfg.get(url_key, "") or "") == url_env:
                return cfg.get("name", "已匹配"), i
        short = f"{token_env[:8]}..." if len(token_env) > 8 else token_env or "?"
        return f"自定义({short})", None

    def current_cfg(self) -> Dict | None:
        if not self.filtered_idx:
            return None
        idx = min(self.selected, len(self.filtered_idx) - 1)
        return self.configs[self.filtered_idx[idx]]

    # ----------------- 绘制 -----------------
    def draw(self) -> None:
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()

        if self.mode == self.MODE_SETTINGS:
            self._draw_settings(max_y, max_x)
        elif self.mode == self.MODE_ADD_CUSTOM:
            self._draw_add_custom(max_y, max_x)
        elif self.mode == self.MODE_CUSTOM_KEY:
            self._draw_custom_key(max_y, max_x)
        else:
            self._draw_list(max_y, max_x)

        self.stdscr.refresh()

    def _draw_list(self, max_y: int, max_x: int) -> None:
        current_name, current_idx = self.current_env()
        list_w = max(max_x // 2, 40)
        visible_rows = max(3, max_y - 8)

        # ─── 顶部标题栏 ───
        type_color = curses.color_pair(4) if self.ai_type == "claude" else curses.color_pair(5)
        title = f" [{self.ai_type.upper()}] "
        self.stdscr.addnstr(0, 0, title, len(title), type_color | curses.A_BOLD)
        info = f"当前: {current_name[:20]}"
        self.stdscr.addnstr(0, len(title) + 1, info, max_x - len(title) - 2, curses.color_pair(2))

        # ─── 快捷键提示 ───
        help_line = "↑↓j:移动  k:自定义Key  a:添加  s:设置  r:刷新  Enter:应用  q:退出"
        self.stdscr.addnstr(1, 0, help_line, max_x - 1, curses.color_pair(1) | curses.A_DIM)

        # ─── 搜索状态 ───
        if self.search:
            self.stdscr.addnstr(2, 0, f"搜索: {self.search}", max_x - 1, curses.color_pair(4))
            list_start_y = 3
        else:
            list_start_y = 2

        # ─── 左侧配置列表 ───
        self.stdscr.addnstr(list_start_y, 0, "─" * (list_w - 1), list_w - 1, curses.A_DIM)
        names = config_loader.list_configs(self.ai_type, self.configs)

        for row in range(visible_rows):
            list_i = self.scroll_offset + row
            if list_i >= len(self.filtered_idx):
                break
            real_idx = self.filtered_idx[list_i]
            cfg = self.configs[real_idx]

            # 状态图标
            icon, icon_color = self.get_status_for(real_idx)

            # 配置名称
            name = cfg.get("name", "<未命名>")[:25]
            if cfg.get("_custom"):
                name = f"* {name}"

            # 当前标记
            is_current = current_idx is not None and real_idx == current_idx
            suffix = " [当前]" if is_current else ""

            # 选择高亮
            y = list_start_y + 1 + row
            if list_i == self.selected:
                attr = curses.color_pair(3) | curses.A_BOLD
            elif is_current:
                attr = curses.color_pair(2)
            else:
                attr = curses.color_pair(1)

            # 绘制行
            self.stdscr.addnstr(y, 0, icon, 2, curses.color_pair(icon_color))
            self.stdscr.addnstr(y, 2, f" {name}{suffix}", list_w - 4, attr)

        # ─── 右侧详情 ───
        detail_x = list_w + 1
        detail_w = max_x - detail_x - 1
        if detail_w > 10:
            # 状态加载指示
            status_suffix = " (获取中...)" if self.health_loading else ""
            self.stdscr.addnstr(list_start_y, detail_x, "─ 详情 " + "─" * (detail_w - 7), detail_w, curses.A_DIM)
            cfg = self.current_cfg()
            detail_y = list_start_y + 1
            if cfg:
                cfg_map = config_loader.CONFIG_MAP[self.ai_type]
                url_key = cfg_map["json_url"]
                token_key = cfg_map["json_token"]

                self.stdscr.addnstr(detail_y, detail_x, f"名称: {cfg.get('name','')[:30]}", detail_w, curses.A_BOLD)
                detail_y += 1
                url_val = cfg.get(url_key, '')[:50]
                self.stdscr.addnstr(detail_y, detail_x, f"URL:  {url_val}", detail_w)
                detail_y += 1
                # 显示脱敏 Key
                key_val = self._mask_key(cfg.get(token_key, ''))
                self.stdscr.addnstr(detail_y, detail_x, f"Key:  {key_val}", detail_w)
                detail_y += 1
                self.stdscr.addnstr(detail_y, detail_x, f"分组: {cfg.get('group','') or '-'}", detail_w)
                detail_y += 2

                # 状态详情
                real_idx = self.filtered_idx[min(self.selected, len(self.filtered_idx) - 1)]
                status_lines, status_color, timeline = self.get_status_detail(real_idx)
                status_label = "状态:" + status_suffix
                self.stdscr.addnstr(detail_y, detail_x, status_label, detail_w, curses.A_UNDERLINE)
                detail_y += 1
                for sl in status_lines[:5]:
                    if detail_y >= max_y - 5:
                        break
                    self.stdscr.addnstr(detail_y, detail_x, f"  {sl[:detail_w-2]}", detail_w, curses.color_pair(status_color))
                    detail_y += 1

                # 历史条
                if timeline and detail_y < max_y - 4:
                    detail_y += 1
                    self.stdscr.addnstr(detail_y, detail_x, "历史: ", 6)
                    tail = timeline[-min(20, detail_w - 8):]
                    for i, st in enumerate(tail):
                        _, c = self._status_icon(st)
                        self.stdscr.addnstr(detail_y, detail_x + 6 + i, "│", 1, curses.color_pair(c))

        # ─── 底部消息区 ───
        self.stdscr.addnstr(max_y - 4, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)
        for i, msg in enumerate(self.messages[-3:]):
            self.stdscr.addnstr(max_y - 3 + i, 0, msg[:max_x - 1], max_x - 1)

    def _draw_settings(self, max_y: int, max_x: int) -> None:
        self.stdscr.addnstr(0, 0, " [设置] ", 10, curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addnstr(1, 0, "↑/↓:选择  Enter:编辑  q/Esc:返回", max_x - 1, curses.A_DIM)
        self.stdscr.addnstr(2, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)

        items = [
            ("状态站 URL", "health_url", self.settings.get("health_url", "")),
        ]

        for i, (label, key, value) in enumerate(items):
            y = 4 + i * 2
            attr = curses.color_pair(3) if i == self.settings_cursor else curses.color_pair(1)
            self.stdscr.addnstr(y, 2, f"{label}:", 20, curses.A_BOLD)

            if self.settings_editing and i == self.settings_cursor:
                # 编辑模式
                self.stdscr.addnstr(y + 1, 4, self.settings_input[:max_x - 8] + "▏", max_x - 6, curses.color_pair(8))
            else:
                display = value[:max_x - 8] if value else "(空)"
                self.stdscr.addnstr(y + 1, 4, display, max_x - 6, attr)

        self.stdscr.addnstr(max_y - 2, 0, "提示: 设置会自动保存", max_x - 1, curses.A_DIM)

    def _draw_add_custom(self, max_y: int, max_x: int) -> None:
        self.stdscr.addnstr(0, 0, f" [添加自定义配置 - {self.ai_type.upper()}] ", 40, curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addnstr(1, 0, "Enter:下一步  Esc:取消", max_x - 1, curses.A_DIM)
        self.stdscr.addnstr(2, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)

        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        fields = [
            ("BASE URL", "base_url", cfg_map["env_url"]),
            ("API KEY", "key", cfg_map["env_token"]),
            ("名称 (可选)", "name", "显示名称"),
        ]

        for i, (label, key, hint) in enumerate(fields):
            y = 4 + i * 3
            is_current = i == self.custom_input_step
            attr = curses.color_pair(4) if is_current else curses.color_pair(1)
            self.stdscr.addnstr(y, 2, f"{label}:", 20, attr | curses.A_BOLD)
            self.stdscr.addnstr(y, 24, f"({hint})", 30, curses.A_DIM)

            value = self.custom_input.get(key, "")
            if is_current:
                display = value + "▏"
                self.stdscr.addnstr(y + 1, 4, display[:max_x - 8], max_x - 6, curses.color_pair(8))
            else:
                display = value if value else "(未填写)"
                if key == "key" and value:
                    display = value[:8] + "..." + value[-4:] if len(value) > 16 else value
                self.stdscr.addnstr(y + 1, 4, display[:max_x - 8], max_x - 6)

        # 提示
        if self.custom_input_step == 2:
            self.stdscr.addnstr(max_y - 2, 0, "按 Enter 完成添加", max_x - 1, curses.color_pair(5))

    def _draw_custom_key(self, max_y: int, max_x: int) -> None:
        """绘制自定义Key输入界面。"""
        cfg = self.current_cfg()
        cfg_name = cfg.get("name", "未知") if cfg else "未知"

        self.stdscr.addnstr(0, 0, f" [自定义 Key - {self.ai_type.upper()}] ", 40, curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addnstr(1, 0, "Enter:应用  Esc:取消", max_x - 1, curses.A_DIM)
        self.stdscr.addnstr(2, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)

        # 说明
        self.stdscr.addnstr(4, 2, "使用选中配置的 URL，但替换为自定义 Key", max_x - 4, curses.color_pair(1))
        self.stdscr.addnstr(5, 2, f"配置: {cfg_name}", max_x - 4, curses.color_pair(2))

        if cfg:
            cfg_map = config_loader.CONFIG_MAP[self.ai_type]
            url_key = cfg_map["json_url"]
            url_val = cfg.get(url_key, '')[:60]
            self.stdscr.addnstr(6, 2, f"URL:  {url_val}", max_x - 4, curses.A_DIM)

        # Key 输入框
        self.stdscr.addnstr(8, 2, "请输入自定义 Key:", 20, curses.A_BOLD)
        display = self.custom_key_input + "▏"
        self.stdscr.addnstr(9, 4, display[:max_x - 8], max_x - 6, curses.color_pair(8))

        # 提示
        self.stdscr.addnstr(max_y - 3, 2, "场景：渠道提供免费 Key，保持 URL 不变，使用新 Key", max_x - 4, curses.A_DIM)
        self.stdscr.addnstr(max_y - 2, 2, "注意：此操作不会保存到配置文件，仅设置环境变量", max_x - 4, curses.A_DIM)

    # ----------------- 操作 -----------------
    def move(self, delta: int) -> None:
        if not self.filtered_idx:
            return
        self.selected = max(0, min(self.selected + delta, len(self.filtered_idx) - 1))
        max_y, _ = self.stdscr.getmaxyx()
        visible_rows = max(3, max_y - 8)
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + visible_rows:
            self.scroll_offset = self.selected - visible_rows + 1

    def toggle_ai(self) -> None:
        self.ai_type = "codex" if self.ai_type == "claude" else "claude"
        self.search = ""
        self.load_configs()

    def prompt_search(self) -> None:
        curses.echo()
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.addnstr(max_y - 1, 0, "搜索: ", max_x - 1)
        self.stdscr.clrtoeol()
        try:
            self.search = self.stdscr.getstr(max_y - 1, 6, 50).decode("utf-8").strip()
        except Exception:
            self.search = ""
        curses.noecho()
        self.apply_filter()

    def apply_config(self) -> None:
        cfg = self.current_cfg()
        if not cfg:
            self._msg("[错误] 无配置可应用")
            return
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
        env_vars = {
            cfg_map["env_token"]: str(cfg.get(token_key, "") or ""),
            cfg_map["env_url"]: str(cfg.get(url_key, "") or ""),
        }
        shell_cfg = env_service.write_permanent(env_vars)
        for k, v in env_vars.items():
            os.environ[k] = v
        self._msg(f"[已应用] {cfg.get('name','')} -> {shell_cfg.name}")
        self._msg(f"  请执行: source {shell_cfg}")

    def clear_env(self, permanent: bool) -> None:
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        keys = [cfg_map["env_token"], cfg_map["env_url"]]
        for k in keys:
            os.environ.pop(k, None)
        if permanent:
            shell_cfg = env_service.remove_permanent(keys)
            self._msg(f"[已清空] 从 {shell_cfg.name} 移除")
            self._msg(f"  请执行: source {shell_cfg}")
        else:
            self._msg(f"[已清空] 当前进程: {', '.join(keys)}")

    # ----------------- 设置模式 -----------------
    def enter_settings(self) -> None:
        self.mode = self.MODE_SETTINGS
        self.settings_cursor = 0
        self.settings_editing = False
        self.settings_input = ""

    def handle_settings_key(self, ch: int) -> bool:
        if ch in (ord("q"), ord("Q"), 27):  # q 或 Esc
            self.mode = self.MODE_LIST
            return True

        if self.settings_editing:
            if ch == 10:  # Enter
                # 保存当前编辑
                keys = ["health_url"]
                if self.settings_cursor < len(keys):
                    self.settings[keys[self.settings_cursor]] = self.settings_input
                    save_settings(self.settings)
                    self._msg("[设置] 已保存")
                self.settings_editing = False
            elif ch == 27:  # Esc
                self.settings_editing = False
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.settings_input = self.settings_input[:-1]
            elif 32 <= ch <= 126:
                self.settings_input += chr(ch)
            return True

        # 非编辑模式
        if ch in (curses.KEY_UP, ord("k")):
            self.settings_cursor = max(0, self.settings_cursor - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.settings_cursor = min(0, self.settings_cursor + 1)  # 只有1项
        elif ch == 10:  # Enter
            keys = ["health_url"]
            if self.settings_cursor < len(keys):
                self.settings_input = self.settings.get(keys[self.settings_cursor], "")
                self.settings_editing = True
        return True

    # ----------------- 添加自定义配置模式 -----------------
    def enter_add_custom(self) -> None:
        self.mode = self.MODE_ADD_CUSTOM
        self.custom_input_step = 0
        self.custom_input = {"base_url": "", "key": "", "name": ""}

    def handle_add_custom_key(self, ch: int) -> bool:
        if ch == 27:  # Esc
            self.mode = self.MODE_LIST
            self._msg("[取消] 添加自定义配置")
            return True

        keys = ["base_url", "key", "name"]
        current_key = keys[self.custom_input_step]

        if ch == 10:  # Enter
            if self.custom_input_step < 2:
                # 下一步
                self.custom_input_step += 1
            else:
                # 完成添加
                if not self.custom_input["base_url"] or not self.custom_input["key"]:
                    self._msg("[错误] BASE URL 和 KEY 不能为空")
                    return True

                cfg_map = config_loader.CONFIG_MAP[self.ai_type]
                new_cfg = {
                    cfg_map["json_url"]: self.custom_input["base_url"],
                    cfg_map["json_token"]: self.custom_input["key"],
                    "name": self.custom_input["name"] or f"自定义-{len(self.settings.get('custom_configs', {}).get(self.ai_type, [])) + 1}",
                }

                # 保存到设置
                if "custom_configs" not in self.settings:
                    self.settings["custom_configs"] = {"claude": [], "codex": []}
                if self.ai_type not in self.settings["custom_configs"]:
                    self.settings["custom_configs"][self.ai_type] = []
                self.settings["custom_configs"][self.ai_type].append(new_cfg)
                save_settings(self.settings)

                self._msg(f"[已添加] {new_cfg['name']}")
                self.mode = self.MODE_LIST
                self.load_configs()
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.custom_input[current_key] = self.custom_input[current_key][:-1]
        elif 32 <= ch <= 126:
            self.custom_input[current_key] += chr(ch)

        return True

    # ----------------- 自定义 Key 模式 -----------------
    def enter_custom_key(self) -> None:
        """进入自定义 Key 输入模式。"""
        cfg = self.current_cfg()
        if not cfg:
            self._msg("[错误] 请先选择一个配置")
            return
        self.mode = self.MODE_CUSTOM_KEY
        self.custom_key_input = ""

    def handle_custom_key(self, ch: int) -> bool:
        """处理自定义 Key 模式的按键。"""
        if ch == 27:  # Esc
            self.mode = self.MODE_LIST
            self._msg("[取消] 自定义 Key")
            return True

        if ch == 10:  # Enter
            if not self.custom_key_input.strip():
                self._msg("[错误] Key 不能为空")
                return True

            cfg = self.current_cfg()
            if not cfg:
                self._msg("[错误] 无配置可应用")
                self.mode = self.MODE_LIST
                return True

            cfg_map = config_loader.CONFIG_MAP[self.ai_type]
            url_key = cfg_map["json_url"]

            # 使用选中配置的 URL + 自定义 Key
            env_vars = {
                cfg_map["env_token"]: self.custom_key_input.strip(),
                cfg_map["env_url"]: str(cfg.get(url_key, "") or ""),
            }
            shell_cfg = env_service.write_permanent(env_vars)
            for k, v in env_vars.items():
                os.environ[k] = v

            self._msg(f"[已应用] {cfg.get('name','')} + 自定义Key -> {shell_cfg.name}")
            self._msg(f"  请执行: source {shell_cfg}")
            self.mode = self.MODE_LIST
            return True

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self.custom_key_input = self.custom_key_input[:-1]
        elif 32 <= ch <= 126:
            self.custom_key_input += chr(ch)

        return True

    # ----------------- 主循环 -----------------
    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.timeout(100)  # 非阻塞模式，100ms超时用于刷新异步状态
        while True:
            self.draw()
            ch = self.stdscr.getch()

            if ch == -1:  # 超时，无输入
                continue

            if self.mode == self.MODE_SETTINGS:
                self.handle_settings_key(ch)
                continue

            if self.mode == self.MODE_ADD_CUSTOM:
                self.handle_add_custom_key(ch)
                continue

            if self.mode == self.MODE_CUSTOM_KEY:
                self.handle_custom_key(ch)
                continue

            # 列表模式
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (curses.KEY_UP,):
                self.move(-1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.move(1)
            elif ch == ord("k"):  # k 用于自定义 Key，不再用于上移
                self.enter_custom_key()
            elif ch == 10:  # Enter
                self.apply_config()
            elif ch in (ord("t"), ord("T")):
                self.toggle_ai()
            elif ch == ord("/"):
                self.prompt_search()
            elif ch in (ord("c"), ord("C")):
                self.search = ""
                self.apply_filter()
            elif ch in (ord("r"), ord("R")):
                self.load_configs()
            elif ch in (ord("s"), ord("S")):
                self.enter_settings()
            elif ch in (ord("a"), ord("A")):
                self.enter_add_custom()
            elif ch == ord("x"):
                self.clear_env(permanent=False)
            elif ch == ord("X"):
                self.clear_env(permanent=True)


def main() -> None:
    curses.wrapper(lambda stdscr: TUI(stdscr).run())


if __name__ == "__main__":
    main()


