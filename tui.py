#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端内的简易 TUI 配置切换工具（curses）。

快捷键：
- ↑/↓       ：移动选择
- t         ：切换 AI 类型 (claude/codex)
- /         ：输入搜索关键字（名称 / channel_id）
- c         ：清除搜索
- e         ：生成临时 export 文本（显示在下方输出区）
- w         ：写入 shell（永久），提示 source
- r         ：重新加载配置
- x         ：清空当前类型环境变量（仅本进程）
- X         ：清空当前类型环境变量并从 shell 配置移除
- q         ：退出

说明：
- 不包含 codex_folder 复制逻辑
- 写入 shell 时优先 .zshrc，否则 .bash_profile
"""

from __future__ import annotations

import curses
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
import ssl

DEFAULT_HEALTH_URL = os.environ.get("HEALTH_STATUS_URL", "https://check.linux.do/api/v1/status")

from core import config_loader, env_service


# ----------------- 健康检查拉取（按 group 聚合，可有多模型与时间线） -----------------
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
            add_entry(
                {
                    "status": str(val.get("status", "unknown")),
                    "lastCheck": str(val.get("lastCheck", "")),
                    "model": str(val.get("model", "")),
                    "name": str(val.get("name", "")),
                    "group": str(val.get("group", "")),
                    "latency": str(val.get("latencyMs", "")),
                    "timeline": parse_timeline(val),
                }
            )

    # providers 结构
    if (not groups) and isinstance(data.get("providers"), list):
        for item in data["providers"]:
            if not isinstance(item, dict):
                continue
            latest = item.get("latest", {}) or {}
            add_entry(
                {
                    "status": str(latest.get("status", "unknown")),
                    "lastCheck": str(latest.get("checkedAt", "")),
                    "model": str(item.get("model", "")),
                    "name": str(item.get("name", "")),
                    "group": str(item.get("group", "")),
                    "latency": str(latest.get("latencyMs", "")),
                    "timeline": parse_timeline(item),
                }
            )

    return groups


def fetch_health_status(url: str = DEFAULT_HEALTH_URL, timeout: int = 8) -> Tuple[Dict[str, Dict[str, str]], str]:
    """获取渠道状态，返回 (map, error_msg)。"""
    headers = {
        "User-Agent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Priority": "u=0, i",
        "Sec-CH-UA": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Cookie": '_ga=GA1.1.894289585.1760930871; __stripe_mid=e0e8301c-af8b-492c-ab44-dcf0f2af00e198939e; linux_do_cdk_session_id=MTc2NDg1NjE0MXxOd3dBTkVSU1JGRkpVRUpSTjFBMFYxSlpVa2RYVjFoTFV6UlZSRXRHTlRaRk5FcFpNemMwVHpkRFdrWkpUVmhYVUU0M1VUUkdURUU9fNUIw963dMzzoO0pw3GlF9fM9cwAfyN32Ik_jnV-eA5q; _ga_1X49KS6K0M=GS2.1.s1765443935$o245$g1$t1765446716$j60$l0$h574049462; cf_clearance=n7651XyRBPrcCiGchoeqsYQvc9.RC50PeBJW1dK5ORw-1765448683-1.2.1.1-r_NTcpHgFDCxzvpw.6ZeJSvdNbrfE9QpXPYClrTA5l5uB8ZvCbdgjCMg0YqtpxJrUgTo524AwWnodbMG4ZaFI4yesrOwaSA9pn98SfUgyCDI_omL01MjbOEO8nBonTkvLEJKyLsOMEfxaOTZtLXOd7ZTH3uDCidsS1crqF2PB0DPdM9hVxlAYOrHtnTyeFkLzmd3rLnQrS1i75emtN9qasCyOQkRcarWHPwnncgTSFc',
    }
    req = Request(url, headers=headers)

    default_proxy = "http://127.0.0.1:7890"
    proxies = {
        "http": os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or default_proxy,
        "https": os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or default_proxy,
    }
    proxies = {k: v for k, v in proxies.items() if v}

    def _build_opener(ctx: ssl.SSLContext | None):
        handlers = []
        if proxies:
            handlers.append(ProxyHandler(proxies))
        if ctx is not None:
            handlers.append(HTTPSHandler(context=ctx))
        return build_opener(*handlers)

    def _do_fetch(ctx: ssl.SSLContext | None, use_proxy: bool = True) -> Tuple[Dict[str, Dict[str, str]], str]:
        try:
            opener = _build_opener(ctx) if use_proxy else _build_opener(ctx if ctx else None)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            return normalize_health(data), ""
        except Exception as exc:  # noqa: BLE001
            return {}, str(exc)

    # 先正常验证
    data, err = _do_fetch(None, use_proxy=True)
    if data or not err:
        return data, err

    # 证书校验失败时自动降级为不校验证书
    if "CERTIFICATE_VERIFY_FAILED" in err:
        insecure_ctx = ssl._create_unverified_context()
        data2, err2 = _do_fetch(insecure_ctx, use_proxy=True)
        if data2 or not err2:
            return data2, ""
        # 继续尝试在不使用代理的情况下拉取
        data3, err3 = _do_fetch(insecure_ctx, use_proxy=False)
        if data3 or not err3:
            return data3, ""
        return data3, err3

    # 其他错误，尝试不走代理再试一次
    data_np, err_np = _do_fetch(None, use_proxy=False)
    if data_np or not err_np:
        return data_np, ""

    return data, err_np or err

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


class TUI:
    def __init__(self, stdscr: "curses._CursesWindow") -> None:
        self.stdscr = stdscr
        self.ai_type = "claude"
        self.search = ""
        self.configs: List[Dict] = []
        self.filtered_idx: List[int] = []
        self.selected = 0
        self.scroll_offset = 0
        self.output_lines: List[str] = ["就绪"]
        self.health_map: Dict[str, List[Dict[str, str]]] = {}
        self._init_colors()
        self.load_configs()

    def _init_colors(self) -> None:
        curses.start_color()
        try:
            curses.use_default_colors()
        except Exception:
            pass
        curses.init_pair(1, curses.COLOR_WHITE, -1)  # 普通
        curses.init_pair(2, curses.COLOR_CYAN, -1)   # 当前配置
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)  # 选中
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # 顶部/Claude
        curses.init_pair(5, curses.COLOR_GREEN, -1)  # ok
        curses.init_pair(6, curses.COLOR_RED, -1)    # error
        curses.init_pair(7, curses.COLOR_YELLOW, -1) # timeout
        curses.init_pair(8, curses.COLOR_MAGENTA, -1) # unknown

    # 状态获取 ------------------------------------------------------------
    def refresh_health(self) -> None:
        health, err = fetch_health_status()
        self.health_map = health
        if err:
            self.output_lines.append(f"[Warning] 渠道状态获取失败（已忽略）: {err}")
        elif not self.health_map:
            self.output_lines.append("[Warning] 渠道状态获取为空（已忽略）")
        else:
            self.output_lines.append(f"[Info] 已获取渠道状态: {len(self.health_map)} 组")

    # 数据与过滤 ----------------------------------------------------------
    def load_configs(self) -> None:
        try:
            self.configs = config_loader.load_configs(self.ai_type)
            names = config_loader.list_configs(self.ai_type, self.configs)
            self.output_lines = [f"已加载 {self.ai_type} 配置，共 {len(names)} 条"]
            self.refresh_health()
        except Exception as exc:  # noqa: BLE001
            self.configs = []
            self.output_lines = [f"[Error] {exc}"]
        self.apply_filter()
        self.scroll_offset = 0

    def apply_filter(self) -> None:
        self.filtered_idx = []
        self.selected = 0
        key = self.search.lower()
        names = config_loader.list_configs(self.ai_type, self.configs)
        for i, display in enumerate(names):
            cfg = self.configs[i]
            text_blob = f"{cfg.get('name','')} {cfg.get('group','')}".lower()
            if key and key not in text_blob:
                continue
            self.filtered_idx.append(i)
        if not self.filtered_idx:
            self.output_lines = ["无匹配结果"]
        self.scroll_offset = 0

    # 渲染 ---------------------------------------------------------------
    def draw(self) -> None:
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        list_w = max_x // 2
        current_name, current_idx = self.current_env()
        visible_rows = max(5, max_y - 6)

        # 顶部状态
        title = (
            f"[AI: {self.ai_type}] 当前: {current_name} | 搜索: {self.search or '<空>'} "
            "(t 切换, / 搜索, c 清空, q 退出)"
        )
        top_color = curses.color_pair(4 if self.ai_type == "claude" else 5)
        self.stdscr.addnstr(0, 0, title, max_x - 1, top_color | curses.A_BOLD)

        # 左侧列表
        self.stdscr.addnstr(1, 0, "配置列表", list_w - 1, curses.A_UNDERLINE)
        names = config_loader.list_configs(self.ai_type, self.configs)
        for row in range(visible_rows):
            list_i = self.scroll_offset + row
            if list_i >= len(self.filtered_idx):
                break
            real_idx = self.filtered_idx[list_i]
            text = names[real_idx]
            if current_idx is not None and real_idx == current_idx:
                text += "  [当前]"
            status_text, status_color = self.get_status_for(real_idx)
            text = f"{status_text} {text}"
            attr = curses.color_pair(status_color)
            if list_i == self.selected:
                attr = curses.color_pair(3)
            elif current_idx is not None and real_idx == current_idx:
                attr = curses.color_pair(2)
            self.stdscr.addnstr(2 + row, 0, text, list_w - 2, attr)

        # 右侧详情
        self.stdscr.addnstr(1, list_w, "配置详情", list_w - 2, curses.A_UNDERLINE)
        detail_y = 2
        cfg = self.current_cfg()
        if cfg:
            cfg_map = config_loader.CONFIG_MAP[self.ai_type]
            token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
            status_lines, status_color, timeline = self.get_status_detail(self.filtered_idx[min(self.selected, len(self.filtered_idx) - 1)] if self.filtered_idx else None)
            details = [
                f"名称: {cfg.get('name','')}",
                f"URL/Base: {cfg.get(url_key,'')}",
                f"分组: {cfg.get('group','') or '未配置'}",
                "状态:",
                "----------------------------------------",
                "快捷键: e 导出临时, w 写入 shell, r 刷新, x/X 清空",
            ]
            for line in details:
                if detail_y >= max_y - 4:
                    break
                attr = curses.color_pair(status_color) if line.startswith("状态:") else curses.color_pair(1)
                self.stdscr.addnstr(detail_y, list_w, line, list_w - 2, attr)
                detail_y += 1

            for s_line in status_lines:
                if detail_y >= max_y - 4:
                    break
                self.stdscr.addnstr(detail_y, list_w, f"  {s_line}", list_w - 2, curses.color_pair(status_color))
                detail_y += 1

            # 历史条
            if timeline and detail_y < max_y - 3:
                self.stdscr.addnstr(detail_y, list_w, "历史: ", list_w - 2, curses.A_BOLD)
                self._draw_history(detail_y, list_w + 4, list_w - 6, timeline)
                detail_y += 1
        else:
            self.stdscr.addnstr(2, list_w, "未选择配置", list_w - 2)

        # 输出区
        self.stdscr.addnstr(max_y - 4, 0, "-" * (max_x - 1), max_x - 1)
        out_lines = self.output_lines[-3:]
        for i, line in enumerate(out_lines):
            self.stdscr.addnstr(max_y - 3 + i, 0, line, max_x - 1)

        self.stdscr.refresh()

    # 操作 ---------------------------------------------------------------
    def current_env(self) -> Tuple[str, int | None]:
        """返回当前环境匹配的配置名称及索引。"""
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_env = os.environ.get(cfg_map["env_token"], "")
        url_env = os.environ.get(cfg_map["env_url"], "")
        if not token_env or not url_env:
            return "未配置", None
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
        for i, cfg in enumerate(self.configs):
            if str(cfg.get(token_key, "") or "") == token_env and str(cfg.get(url_key, "") or "") == url_env:
                return cfg.get("name", "已匹配"), i
        short = f"{token_env[:4]}..." if token_env else "未知"
        return f"环境未匹配({short})", None

    def _status_icon(self, status: str) -> Tuple[str, int]:
        status = (status or "unknown").lower()
        if status == "ok":
            return "O", 5
        if status == "operational":
            return "O", 5
        if status == "error":
            return "X", 6
        if status == "timeout":
            return "!", 7
        if status == "degraded":
            return "~", 7
        return "?", 8

    def _group_entries(self, cfg: Dict) -> List[Dict[str, str]]:
        group = str(cfg.get("group", "") or "")
        if not group:
            return []
        return self.health_map.get(group, [])

    def _choose_status(self, entries: List[Dict[str, str]]) -> Tuple[str, int]:
        if not entries:
            return "[?]", 8
        severity_order = ["error", "timeout", "failed", "degraded", "operational", "ok", "unknown"]
        best = "unknown"
        for e in entries:
            st = str(e.get("status", "unknown")).lower()
            if severity_order.index(st) < severity_order.index(best):
                best = st
        icon, color = self._status_icon(best)
        return f"[{icon}]", color

    def get_status_for(self, real_idx: int) -> Tuple[str, int]:
        """用于列表显示的状态文字和颜色（按 group 聚合）。"""
        if real_idx is None or real_idx >= len(self.configs):
            return "[?]", 8
        cfg = self.configs[real_idx]
        entries = self._group_entries(cfg)
        return self._choose_status(entries)

    def get_status_detail(self, real_idx: int | None) -> Tuple[List[str], int, List[str]]:
        """用于详情显示，列出该 group 下的所有模型状态，并返回时间线。"""
        if real_idx is None or real_idx >= len(self.configs):
            return ["unknown"], 8, []
        cfg = self.configs[real_idx]
        entries = self._group_entries(cfg)
        if not entries:
            return ["unknown (无匹配 group)"], 8, []
        lines: List[str] = []
        timeline: List[str] = []
        for e in entries:
            icon, _color = self._status_icon(e.get("status"))
            tl = e.get("timeline") or []
            if tl and not timeline:
                timeline = tl  # 取该组第一条的时间线
            ago = self._fmt_ago(e.get("lastCheck", ""))
            line = f"{icon} {e.get('model','') or e.get('name','') or ''} {e.get('status','unknown')}"
            if ago:
                line += f" ({ago})"
            lines.append(line.strip())
        _best_icon, color = self._choose_status(entries)
        return lines, color, timeline

    def _draw_history(self, y: int, x: int, width: int, timeline: List[str]) -> None:
        if width <= 0:
            return
        # 取最新的若干条（右侧显示），最多 20
        tail = timeline[-20:]
        start_x = x
        for st in tail:
            _icon, color = self._status_icon(st)
            self.stdscr.addnstr(y, start_x, "|", 1, curses.color_pair(color))
            start_x += 1
            if start_x - x >= width:
                break

    def current_cfg(self) -> Dict | None:
        if not self.filtered_idx:
            return None
        real_idx = self.filtered_idx[min(self.selected, len(self.filtered_idx) - 1)]
        return self.configs[real_idx]

    def move(self, delta: int) -> None:
        if not self.filtered_idx:
            return
        self.selected = max(0, min(self.selected + delta, len(self.filtered_idx) - 1))
        max_y, _ = self.stdscr.getmaxyx()
        visible_rows = max(5, max_y - 6)
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
        self.stdscr.addnstr(max_y - 1, 0, "输入搜索关键字: ", max_x - 1)
        self.stdscr.clrtoeol()
        self.search = self.stdscr.getstr(max_y - 1, 10).decode("utf-8").strip()
        curses.noecho()
        self.apply_filter()
        self.scroll_offset = 0

    def export_temp(self) -> None:
        cfg = self.current_cfg()
        if not cfg:
            self.output_lines.append("无配置可导出")
            return
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
        env_vars = {
            cfg_map["env_token"]: str(cfg.get(token_key, "") or ""),
            cfg_map["env_url"]: str(cfg.get(url_key, "") or ""),
        }
        export_text = env_service.build_export_lines(env_vars)
        self.output_lines.append("临时 export：")
        for line in export_text.splitlines():
            self.output_lines.append(f"  {line}")
        self.output_lines.append("可在终端执行: eval \"$(python ai_env.py --type {t} --name '{n}')\"".format(
            t=self.ai_type, n=cfg.get("name", ""),
        ))

    def write_shell(self) -> None:
        cfg = self.current_cfg()
        if not cfg:
            self.output_lines.append("无配置可写入")
            return
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        token_key, url_key = cfg_map["json_token"], cfg_map["json_url"]
        env_vars = {
            cfg_map["env_token"]: str(cfg.get(token_key, "") or ""),
            cfg_map["env_url"]: str(cfg.get(url_key, "") or ""),
        }
        shell_cfg = env_service.write_permanent(env_vars)
        self.output_lines.append("已写入环境变量:")
        for k, v in env_vars.items():
            self.output_lines.append(f"  {k}={v}")
        self.output_lines.append(f"目标文件: {shell_cfg}")
        self.output_lines.append(f"请执行: source {shell_cfg}")

    def clear_env(self, permanent: bool) -> None:
        cfg_map = config_loader.CONFIG_MAP[self.ai_type]
        keys = [cfg_map["env_token"], cfg_map["env_url"]]
        for k in keys:
            os.environ.pop(k, None)
        if permanent:
            shell_cfg = env_service.remove_permanent(keys)
            self.output_lines.append(f"已从 shell 配置移除: {', '.join(keys)}")
            self.output_lines.append(f"目标文件: {shell_cfg}")
            self.output_lines.append(f"如需生效请执行: source {shell_cfg}")
        else:
            self.output_lines.append(f"已清空当前进程环境变量: {', '.join(keys)}")
        # 刷新状态
        self.apply_filter()

    # 主循环 --------------------------------------------------------------
    def run(self) -> None:
        while True:
            self.draw()
            ch = self.stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            elif ch in (curses.KEY_UP, ord("k")):
                self.move(-1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.move(1)
            elif ch in (ord("t"), ord("T")):
                self.toggle_ai()
            elif ch == ord("/"):
                self.prompt_search()
            elif ch in (ord("c"), ord("C")):
                self.search = ""
                self.apply_filter()
            elif ch in (ord("r"), ord("R")):
                self.load_configs()
            elif ch in (ord("e"), ord("E")):
                self.export_temp()
            elif ch in (ord("w"), ord("W")):
                self.write_shell()
            elif ch == ord("x"):
                self.clear_env(permanent=False)
            elif ch == ord("X"):
                self.clear_env(permanent=True)


def main() -> None:
    curses.wrapper(lambda stdscr: TUI(stdscr).run())


if __name__ == "__main__":
    main()
