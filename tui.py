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
from typing import Dict, List, Tuple
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
import ssl

DEFAULT_HEALTH_URL = os.environ.get("HEALTH_STATUS_URL", "https://check.linux.do/api/v1/status")

from core import config_loader, env_service


# ----------------- 健康检查拉取 -----------------
def normalize_health(data: Dict) -> Dict[str, Dict[str, str]]:
    services: Dict[str, Dict[str, str]] = {}
    if not isinstance(data, dict):
        return services
    if isinstance(data.get("services"), dict):
        for cid, val in data["services"].items():
            if not cid:
                continue
            status = str((val or {}).get("status", "unknown"))
            last = str((val or {}).get("lastCheck", ""))
            services[cid] = {"status": status, "lastCheck": last}
    if not services and isinstance(data.get("providers"), list):
        for item in data["providers"]:
            cid = (item or {}).get("id")
            if not cid:
                continue
            latest = (item or {}).get("latest", {}) or {}
            status = str(latest.get("status", "unknown"))
            last = str(latest.get("checkedAt", ""))
            services[cid] = {"status": status, "lastCheck": last}
    return services


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

    def _do_fetch(ctx: ssl.SSLContext | None) -> Tuple[Dict[str, Dict[str, str]], str]:
        try:
            opener = _build_opener(ctx)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
            data = json.loads(raw.decode("utf-8"))
            return normalize_health(data), ""
        except Exception as exc:  # noqa: BLE001
            return {}, str(exc)

    # 先正常验证
    data, err = _do_fetch(None)
    if data or not err:
        return data, err

    # 证书校验失败时自动降级为不校验证书
    if "CERTIFICATE_VERIFY_FAILED" in err:
        insecure_ctx = ssl._create_unverified_context()
        data2, err2 = _do_fetch(insecure_ctx)
        if data2 or not err2:
            return data2, ""
        return data2, err2

    return data, err


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
        self.health_map: Dict[str, Dict[str, str]] = {}
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
            self.output_lines.append(f"[Info] 已获取渠道状态: {len(self.health_map)} 条")

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
            text_blob = f"{cfg.get('name','')} {cfg.get('channel_id','')}".lower()
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
            status_line, _ = self.get_status_detail(self.filtered_idx[min(self.selected, len(self.filtered_idx) - 1)] if self.filtered_idx else None)
            details = [
                f"名称: {cfg.get('name','')}",
                f"URL/Base: {cfg.get(url_key,'')}",
                f"Channel ID: {cfg.get('channel_id','') or ''}",
                f"状态: {status_line}",
                "----------------------------------------",
                "快捷键: e 导出临时, w 写入 shell, r 刷新, x/X 清空",
            ]
            for line in details:
                if detail_y >= max_y - 4:
                    break
                self.stdscr.addnstr(detail_y, list_w, line, list_w - 2)
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
        if status == "error":
            return "X", 6
        if status == "timeout":
            return "!", 7
        return "?", 8

    def get_status_for(self, real_idx: int) -> Tuple[str, int]:
        """用于列表显示的状态文字和颜色。"""
        if real_idx is None or real_idx >= len(self.configs):
            return "[?]", 8
        cfg = self.configs[real_idx]
        channel_id = str(cfg.get("channel_id", "") or "")
        if not channel_id:
            return "[?]", 8
        info = self.health_map.get(channel_id, {})
        icon, color = self._status_icon(info.get("status"))
        return f"[{icon}]", color

    def get_status_detail(self, real_idx: int | None) -> Tuple[str, int]:
        """用于详情显示，附带 lastCheck。"""
        if real_idx is None or real_idx >= len(self.configs):
            return "unknown", 8
        cfg = self.configs[real_idx]
        channel_id = str(cfg.get("channel_id", "") or "")
        if not channel_id:
            return "unknown (无 channel_id)", 8
        info = self.health_map.get(channel_id, {})
        status = info.get("status", "unknown")
        last = info.get("lastCheck", "")
        icon, color = self._status_icon(status)
        if last:
            return f"{icon} {status} | last: {last}", color
        return f"{icon} {status}", color

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
