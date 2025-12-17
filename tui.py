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

# 默认状态站 URL (api-db.lib00.com 格式)
DEFAULT_HEALTH_URL = "https://api-api-db.lib00.com/v1/monitor/data?range=24h"

# PyInstaller 打包后 __file__ 指向临时解压目录，需要用 sys.executable 获取真实路径
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的可执行文件
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    # 普通 Python 运行
    _BASE_DIR = Path(__file__).resolve().parent

SETTINGS_FILE = _BASE_DIR / ".tui_settings.json"
ENV_FILE = _BASE_DIR / ".env"


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
def normalize_health(data: Dict, ai_type: str = "claude") -> Dict[str, List[Dict]]:
    """解析健康检查 API 返回数据。

    返回结构:
    {
        "DuckCoding": [
            {
                "name": "CC 专用-2api",
                "model": "Claude Code专用-2api",
                "status": "slow",
                "latency": "4654",
                "uptime": "97.50",
                "lastCheck": "2025-12-17T15:00:00",
                "nodes": [
                    {"name": "duckcoding自测", "availability": 0.968, "latency_avg": 5936.48, "results": [1,1,1,...]},
                    ...
                ]
            }
        ]
    }
    """
    groups: Dict[str, List[Dict]] = {}
    if not isinstance(data, dict):
        return groups

    # 检查是否是 api-db.lib00.com 格式 (包含 data 包装)
    if data.get("code") == 200 and isinstance(data.get("data"), dict):
        data = data["data"]

    # 获取数据生成时间（上次检查时间）
    generated_at = data.get("generated_at")

    def add_entry(entry: Dict) -> None:
        grp = str(entry.get("group", "") or "")
        if not grp:
            grp = "unknown"
        groups.setdefault(grp, []).append(entry)

    def status_code_to_str(code) -> str:
        """将数字状态码转换为字符串状态"""
        code_map = {1: "ok", 2: "slow", 3: "error"}
        if isinstance(code, int):
            return code_map.get(code, "unknown")
        return str(code) if code else "unknown"

    def is_matching_channel(svc: Dict) -> bool:
        """判断渠道是否匹配当前 ai_type，优先使用 model_type_label"""
        model_type = str(svc.get("model_type_label") or svc.get("model_type_code") or "").lower()

        # 优先使用 model_type_label 精确匹配
        if model_type:
            if ai_type == "claude":
                return model_type == "claude_code"
            else:  # codex
                return model_type == "codex"

        # 回退到关键词匹配（兼容旧数据）
        model_name = str(svc.get("model_name") or "").lower()
        channel_name = str(svc.get("channel_name") or "").lower()
        text = f"{model_name} {channel_name}"

        if ai_type == "claude":
            return any(kw in text for kw in ["claude", "cc专用", "cc ", "sonnet", "opus", "haiku"])
        else:  # codex
            return any(kw in text for kw in ["codex", "gpt", "openai"])

    def timestamp_to_iso(ts) -> str:
        """将毫秒时间戳转换为 ISO 格式（API 返回北京时间）"""
        if not ts:
            return ""
        try:
            if isinstance(ts, (int, float)):
                # API 返回的是北京时间的时间戳，直接用本地时间解析
                dt = datetime.fromtimestamp(ts / 1000)
                return dt.isoformat()
        except Exception:
            pass
        return str(ts)

    def parse_nodes_with_services(svc: Dict, service_name: str) -> List[Dict]:
        """解析 timeline 中的所有节点数据，返回节点列表，每个节点包含该 service 的检测数据"""
        nodes_data: Dict[int, Dict] = {}  # node_id -> node_data
        tl = svc.get("timeline") or []
        if not isinstance(tl, list):
            return []

        for block in tl:
            if not isinstance(block, dict):
                continue
            nodes = block.get("nodes") or {}
            for node_key, node_info in nodes.items():
                if not isinstance(node_info, dict):
                    continue
                node_id = node_info.get("node_id")
                if node_id is None:
                    continue

                if node_id not in nodes_data:
                    nodes_data[node_id] = {
                        "node_id": node_id,
                        "node_name": node_info.get("node_name_zh") or node_info.get("node_name_en", ""),
                        "services": [],  # 该节点检测的 service 列表
                    }

                # 累加数据到临时变量
                nd = nodes_data[node_id]
                if "temp_results" not in nd:
                    nd["temp_results"] = []
                    nd["temp_count_total"] = 0
                    nd["temp_count_success"] = 0
                    nd["temp_latency_avg"] = 0

                nd["temp_results"].extend(node_info.get("results") or [])
                nd["temp_count_total"] += node_info.get("count_total", 0)
                nd["temp_count_success"] += node_info.get("count_success", 0)
                if node_info.get("latency_avg"):
                    nd["temp_latency_avg"] = node_info.get("latency_avg", 0)

        # 计算可用率并构建 service 数据
        result = []
        for node_id, nd in sorted(nodes_data.items()):
            avail = 0.0
            if nd.get("temp_count_total", 0) > 0:
                avail = nd["temp_count_success"] / nd["temp_count_total"]

            # 构建该节点的 service 检测结果
            results = nd.get("temp_results", [])[-50:]
            # 计算最近状态
            recent_status = "unknown"
            if results:
                last = results[-1]
                recent_status = {1: "ok", 2: "slow", 3: "error"}.get(last, "unknown")

            service_entry = {
                "name": service_name,
                "status": recent_status,
                "availability": avail,
                "latency_avg": nd.get("temp_latency_avg", 0),
                "results": results,
            }

            result.append({
                "node_id": node_id,
                "node_name": nd["node_name"],
                "service": service_entry,
            })

        return result

    def parse_timeline_simple(svc: Dict) -> List[str]:
        """解析 timeline 为简单状态列表（用于历史条显示）"""
        tl = svc.get("timeline") or []
        if not isinstance(tl, list) or not tl:
            return []
        # 取第一个 block 的第一个节点的 results
        first_block = tl[0] if tl else {}
        nodes = first_block.get("nodes") or {}
        for node_key, node_info in nodes.items():
            if isinstance(node_info, dict):
                results = node_info.get("results") or []
                return [status_code_to_str(r) for r in results[-50:]]
        return []

    # 按节点聚合所有 service 的检测数据
    # nodes_aggregated: {node_id: {"node_name": str, "services": [...]}}
    nodes_aggregated: Dict[int, Dict] = {}

    # api-db.lib00.com 格式 (services 是 list)
    if isinstance(data.get("services"), list):
        for svc in data["services"]:
            if not isinstance(svc, dict):
                continue
            # 过滤不匹配的渠道
            if not is_matching_channel(svc):
                continue

            current = svc.get("current_status") or {}
            status_code = current.get("status", 0)
            service_name = str(svc.get("channel_name") or svc.get("model_name", ""))

            # 解析该 service 在各节点的检测数据
            node_entries = parse_nodes_with_services(svc, service_name)
            for ne in node_entries:
                node_id = ne["node_id"]
                if node_id not in nodes_aggregated:
                    nodes_aggregated[node_id] = {
                        "node_name": ne["node_name"],
                        "services": [],
                    }
                nodes_aggregated[node_id]["services"].append(ne["service"])

            add_entry({
                "status": status_code_to_str(status_code),
                "lastCheck": timestamp_to_iso(generated_at),
                "model": str(svc.get("model_name", "")),
                "name": service_name,
                "group": str(svc.get("provider_name") or svc.get("provider_code", "")),
                "latency": str(current.get("latency_ms", "")),
                "uptime": str(current.get("uptime_percent", "")),
                "nodes_by_service": [],  # 旧字段保留兼容
                "timeline": parse_timeline_simple(svc),
            })

    # 将聚合的节点数据添加到返回结果
    # 存储在特殊 key "__nodes__" 中
    if nodes_aggregated:
        nodes_list = []
        for node_id, nd in sorted(nodes_aggregated.items()):
            nodes_list.append({
                "node_id": node_id,
                "node_name": nd["node_name"],
                "services": nd["services"],
            })
        groups["__nodes__"] = nodes_list

    return groups


def fetch_health_status(url: str, ai_type: str = "claude", timeout: int = 15) -> Tuple[Dict[str, List[Dict[str, str]]], str]:
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
            return normalize_health(data, ai_type), ""
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
            return normalize_health(data, ai_type), ""
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
    MODE_CONFIRM = "confirm"
    MODE_CONFIRM_CUSTOM_KEY = "confirm_custom_key"

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

        # 确认页面待应用的配置
        self.confirm_cfg: Optional[Dict] = None
        # 自定义 Key 确认页面的 Key
        self.confirm_custom_key: str = ""

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
            # timestamp_to_iso 返回的是本地时间（无时区），用本地时间比较
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # 如果没有时区信息，作为本地时间处理
            if dt.tzinfo is None:
                now = datetime.now()
            else:
                now = datetime.now(timezone.utc)
            diff = (now - dt).total_seconds()
            # 处理负数（未来时间，可能是 API 返回的预定时间）
            if diff < 0:
                return "刚刚"
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

        ai_type = self.ai_type  # 捕获当前 ai_type
        def _fetch():
            health, err = fetch_health_status(url, ai_type)
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
            return "●", 5   # 绿色
        if status == "slow":
            return "●", 4   # 黄色 (作为橙色替代)
        if status in ("error", "timeout", "failed"):
            return "●", 6   # 红色
        return "○", 1       # 白色/未知

    def _group_entries(self, cfg: Dict) -> List[Dict[str, str]]:
        group = str(cfg.get("group", "") or "")
        return self.health_map.get(group, []) if group else []

    def _choose_status(self, entries: List[Dict[str, str]]) -> Tuple[str, int]:
        if not entries:
            return "○", 1
        severity = {"error": 0, "failed": 0, "slow": 1, "degraded": 2, "ok": 3, "operational": 3, "unknown": 4}
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

    def get_status_detail(self, real_idx: int | None) -> Tuple[List[Tuple[str, int]], int, List[str], List[Dict]]:
        """返回 (状态行列表[(文本, 颜色)], 整体颜色, timeline, nodes)"""
        if real_idx is None or real_idx >= len(self.configs):
            return [("未知", 1)], 1, [], []
        cfg = self.configs[real_idx]
        entries = self._group_entries(cfg)
        if not entries:
            return [("无状态数据", 1)], 1, [], []
        lines: List[Tuple[str, int]] = []
        timeline: List[str] = []
        nodes: List[Dict] = []
        for e in entries:
            icon, icon_color = self._status_icon(e.get("status"))
            tl = e.get("timeline") or []
            if tl and not timeline:
                timeline = tl
            # 收集节点数据
            entry_nodes = e.get("nodes") or []
            if entry_nodes and not nodes:
                nodes = entry_nodes
            ago = self._fmt_ago(e.get("lastCheck", ""))
            model = e.get("model") or e.get("name") or ""
            uptime = e.get("uptime", "")
            line = f"{icon} {model} {e.get('status','?')}"
            if uptime:
                line += f" {uptime}%"
            if ago:
                line += f" ({ago})"
            lines.append((line, icon_color))
        _, overall_color = self._choose_status(entries)
        return lines, overall_color, timeline, nodes

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
        # 自定义配置：显示 URL 和 Key
        if url_env:
            import re
            match = re.search(r'https?://([^/]+)', url_env)
            domain = match.group(1) if match else url_env[:20]
            key_short = self._mask_key(token_env) if token_env else "无Key"
            return f"自定义({domain}) {key_short}", None
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
        elif self.mode == self.MODE_CONFIRM:
            self._draw_confirm(max_y, max_x)
        elif self.mode == self.MODE_CONFIRM_CUSTOM_KEY:
            self._draw_confirm_custom_key(max_y, max_x)
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
        help_line = "↑↓j:移动  Tab:切换  k:自定义Key  a:添加  s:设置  r:刷新  Enter:应用  q:退出"
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
                status_lines, status_color, timeline, _ = self.get_status_detail(real_idx)
                status_label = "状态:" + status_suffix
                self.stdscr.addnstr(detail_y, detail_x, status_label, detail_w, curses.A_UNDERLINE)
                detail_y += 1
                for sl_text, sl_color in status_lines:
                    if detail_y >= max_y - 5:
                        break
                    self.stdscr.addnstr(detail_y, detail_x, f"  {sl_text[:detail_w-2]}", detail_w, curses.color_pair(sl_color))
                    detail_y += 1

                # 检测节点（按节点分组，每个节点下显示 services）
                nodes_data = self.health_map.get("__nodes__", [])
                if nodes_data and detail_y < max_y - 5:
                    detail_y += 1
                    self.stdscr.addnstr(detail_y, detail_x, "检测节点:", detail_w, curses.A_UNDERLINE)
                    detail_y += 1
                    for nd in nodes_data:
                        if detail_y >= max_y - 4:
                            break
                        node_name = nd.get("node_name", "")[:14]
                        services = nd.get("services", [])
                        # 计算节点整体可用率
                        total_avail = sum(s.get("availability", 0) for s in services)
                        avg_avail = total_avail / len(services) if services else 0
                        # 节点状态图标
                        if avg_avail >= 0.95:
                            node_icon, node_color = "●", 5  # 绿色
                        elif avg_avail >= 0.8:
                            node_icon, node_color = "●", 4  # 黄色
                        else:
                            node_icon, node_color = "●", 6  # 红色
                        # 绘制节点行
                        node_line = f"{node_icon} {node_name}"
                        self.stdscr.addnstr(detail_y, detail_x, node_line, detail_w, curses.color_pair(node_color) | curses.A_BOLD)
                        detail_y += 1
                        # 绘制该节点下的 services
                        for svc in services[:6]:  # 每个节点最多显示6个 service
                            if detail_y >= max_y - 4:
                                break
                            svc_name = svc.get("name", "")
                            svc_status = svc.get("status", "unknown")
                            svc_avail = svc.get("availability", 0)
                            svc_icon, svc_color = self._status_icon(svc_status)
                            results = svc.get("results", [])[-10:]
                            avail_str = f"{svc_avail*100:.1f}%"

                            # 分段绘制：图标+名称 | 百分比 | 历史条
                            # 图标和名称
                            name_max = 18
                            svc_name_trunc = svc_name[:name_max]
                            self.stdscr.addnstr(detail_y, detail_x, f"  {svc_icon} ", 4, curses.color_pair(svc_color))
                            self.stdscr.addnstr(detail_y, detail_x + 4, svc_name_trunc, name_max, curses.color_pair(svc_color))
                            # 百分比（固定位置）
                            pct_x = detail_x + 4 + name_max + 1
                            self.stdscr.addnstr(detail_y, pct_x, avail_str, 6, curses.color_pair(svc_color))
                            # 历史条（固定位置）
                            bar_x = pct_x + 7
                            for i, r in enumerate(results):
                                if bar_x + i >= detail_x + detail_w - 1:
                                    break
                                if r == 1:
                                    bar_char, bar_color = "│", 5
                                elif r == 2:
                                    bar_char, bar_color = "│", 4
                                else:
                                    bar_char, bar_color = "│", 6
                                self.stdscr.addnstr(detail_y, bar_x + i, bar_char, 1, curses.color_pair(bar_color))
                            detail_y += 1

                # 历史条（整体）
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

    def _draw_confirm(self, max_y: int, max_x: int) -> None:
        """绘制确认应用配置页面。"""
        cfg = self.confirm_cfg
        if not cfg:
            self.mode = self.MODE_LIST
            return

        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]

        # 标题
        self.stdscr.addnstr(0, 0, " [确认应用配置] ", 20, curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addnstr(1, 0, "Enter/y:确认  Esc/n:取消", max_x - 1, curses.A_DIM)
        self.stdscr.addnstr(2, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)

        y = 4
        # 软件类型
        type_color = curses.color_pair(4) if self.ai_type == "claude" else curses.color_pair(5)
        self.stdscr.addnstr(y, 2, "软件类型:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, self.ai_type.upper(), 10, type_color | curses.A_BOLD)
        y += 2

        # 渠道名称
        self.stdscr.addnstr(y, 2, "渠道名称:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, cfg.get("name", "未知")[:max_x-16], max_x - 16, curses.color_pair(2))
        y += 2

        # 分组
        group = cfg.get("group", "") or "-"
        self.stdscr.addnstr(y, 2, "分组:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, group[:max_x-16], max_x - 16)
        y += 2

        # BASE URL
        url_val = cfg.get(url_key, "") or "-"
        self.stdscr.addnstr(y, 2, "BASE URL:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, url_val[:max_x-16], max_x - 16)
        y += 2

        # API KEY (脱敏)
        key_val = self._mask_key(cfg.get(token_key, ""))
        self.stdscr.addnstr(y, 2, "API KEY:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, key_val[:max_x-16], max_x - 16)
        y += 2

        # 环境变量
        self.stdscr.addnstr(y, 2, "─" * (max_x - 4), max_x - 4, curses.A_DIM)
        y += 1
        self.stdscr.addnstr(y, 2, "将设置以下环境变量:", max_x - 4, curses.A_DIM)
        y += 1
        self.stdscr.addnstr(y, 4, f"{cfg_map['env_url']}", max_x - 6, curses.color_pair(2))
        y += 1
        self.stdscr.addnstr(y, 4, f"{cfg_map['env_token']}", max_x - 6, curses.color_pair(2))
        y += 2

        # 底部确认提示
        self.stdscr.addnstr(max_y - 3, 2, "─" * (max_x - 4), max_x - 4, curses.A_DIM)
        self.stdscr.addnstr(max_y - 2, 2, "是否确认应用此配置?", max_x - 4, curses.color_pair(4) | curses.A_BOLD)

    def _draw_confirm_custom_key(self, max_y: int, max_x: int) -> None:
        """绘制自定义 Key 确认页面。"""
        cfg = self.confirm_cfg
        if not cfg:
            self.mode = self.MODE_LIST
            return

        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        url_key = cfg_map["json_url"]

        # 标题
        self.stdscr.addnstr(0, 0, " [确认应用自定义 Key] ", 25, curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.addnstr(1, 0, "Enter/y:确认  Esc/n:取消", max_x - 1, curses.A_DIM)
        self.stdscr.addnstr(2, 0, "─" * (max_x - 1), max_x - 1, curses.A_DIM)

        y = 4
        # 软件类型
        type_color = curses.color_pair(4) if self.ai_type == "claude" else curses.color_pair(5)
        self.stdscr.addnstr(y, 2, "软件类型:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, self.ai_type.upper(), 10, type_color | curses.A_BOLD)
        y += 2

        # 渠道名称
        self.stdscr.addnstr(y, 2, "渠道名称:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, cfg.get("name", "未知")[:max_x-16], max_x - 16, curses.color_pair(2))
        y += 2

        # BASE URL (来自配置)
        url_val = cfg.get(url_key, "") or "-"
        self.stdscr.addnstr(y, 2, "BASE URL:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, url_val[:max_x-16], max_x - 16)
        y += 2

        # 自定义 API KEY (脱敏)
        key_val = self._mask_key(self.confirm_custom_key)
        self.stdscr.addnstr(y, 2, "自定义 KEY:", 12, curses.A_BOLD)
        self.stdscr.addnstr(y, 14, key_val[:max_x-16], max_x - 16, curses.color_pair(5))
        y += 2

        # 环境变量
        self.stdscr.addnstr(y, 2, "─" * (max_x - 4), max_x - 4, curses.A_DIM)
        y += 1
        self.stdscr.addnstr(y, 2, "将设置以下环境变量:", max_x - 4, curses.A_DIM)
        y += 1
        self.stdscr.addnstr(y, 4, f"{cfg_map['env_url']}", max_x - 6, curses.color_pair(2))
        y += 1
        self.stdscr.addnstr(y, 4, f"{cfg_map['env_token']} (自定义)", max_x - 6, curses.color_pair(5))
        y += 2

        # 底部确认提示
        self.stdscr.addnstr(max_y - 3, 2, "─" * (max_x - 4), max_x - 4, curses.A_DIM)
        self.stdscr.addnstr(max_y - 2, 2, "是否确认应用此配置?", max_x - 4, curses.color_pair(4) | curses.A_BOLD)

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
        """进入确认页面。"""
        cfg = self.current_cfg()
        if not cfg:
            self._msg("[错误] 无配置可应用")
            return
        self.confirm_cfg = cfg
        self.mode = self.MODE_CONFIRM

    def do_apply_config(self) -> None:
        """实际执行应用配置。"""
        cfg = self.confirm_cfg
        if not cfg:
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
        self.confirm_cfg = None
        self.mode = self.MODE_LIST

    def handle_confirm_key(self, ch: int) -> bool:
        """处理确认页面的按键。"""
        if ch in (ord('y'), ord('Y'), 10):  # y/Y/Enter 确认
            self.do_apply_config()
        elif ch in (ord('n'), ord('N'), 27):  # n/N/Esc 取消
            self._msg("[取消] 未应用配置")
            self.confirm_cfg = None
            self.mode = self.MODE_LIST
        return True

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
            # 输入为空时忽略 Enter（避免粘贴带换行符误触发）
            if not self.custom_key_input.strip():
                return True

            cfg = self.current_cfg()
            if not cfg:
                self._msg("[错误] 无配置可应用")
                self.mode = self.MODE_LIST
                return True

            # 进入确认页面
            self.confirm_cfg = cfg
            self.confirm_custom_key = self.custom_key_input.strip()
            self.mode = self.MODE_CONFIRM_CUSTOM_KEY
            return True

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self.custom_key_input = self.custom_key_input[:-1]
        elif 32 <= ch <= 126:  # 可打印字符，排除换行符
            self.custom_key_input += chr(ch)
        # 忽略换行符等控制字符，避免粘贴时误触发

        return True

    def handle_confirm_custom_key(self, ch: int) -> bool:
        """处理自定义 Key 确认页面的按键。"""
        if ch in (ord('y'), ord('Y'), 10):  # y/Y/Enter 确认
            self.do_apply_custom_key()
        elif ch in (ord('n'), ord('N'), 27):  # n/N/Esc 取消
            self._msg("[取消] 未应用自定义 Key")
            self.confirm_cfg = None
            self.confirm_custom_key = ""
            self.mode = self.MODE_LIST
        return True

    def do_apply_custom_key(self) -> None:
        """实际执行应用自定义 Key。"""
        cfg = self.confirm_cfg
        if not cfg:
            return

        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        url_key = cfg_map["json_url"]

        env_vars = {
            cfg_map["env_token"]: self.confirm_custom_key,
            cfg_map["env_url"]: str(cfg.get(url_key, "") or ""),
        }
        shell_cfg = env_service.write_permanent(env_vars)
        for k, v in env_vars.items():
            os.environ[k] = v

        self._msg(f"[已应用] {cfg.get('name','')} + 自定义Key -> {shell_cfg.name}")
        self._msg(f"  请执行: source {shell_cfg}")
        self.confirm_cfg = None
        self.confirm_custom_key = ""
        self.mode = self.MODE_LIST

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

            if self.mode == self.MODE_CONFIRM:
                self.handle_confirm_key(ch)
                continue

            if self.mode == self.MODE_CONFIRM_CUSTOM_KEY:
                self.handle_confirm_custom_key(ch)
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
            elif ch in (ord("t"), ord("T"), ord("\t")):
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
    try:
        curses.wrapper(lambda stdscr: TUI(stdscr).run())
    except KeyboardInterrupt:
        pass  # Ctrl+C 优雅退出


if __name__ == "__main__":
    main()


