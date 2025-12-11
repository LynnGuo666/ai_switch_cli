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
import os
import sys
from typing import Dict, List, Tuple

from core import config_loader, env_service


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
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # 顶部

    # 数据与过滤 ----------------------------------------------------------
    def load_configs(self) -> None:
        try:
            self.configs = config_loader.load_configs(self.ai_type)
            names = config_loader.list_configs(self.ai_type, self.configs)
            self.output_lines = [f"已加载 {self.ai_type} 配置，共 {len(names)} 条"]
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
        self.stdscr.addnstr(0, 0, title, max_x - 1, curses.color_pair(4) | curses.A_BOLD)

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
            attr = curses.color_pair(1)
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
            details = [
                f"名称: {cfg.get('name','')}",
                f"URL/Base: {cfg.get(url_key,'')}",
                f"Channel ID: {cfg.get('channel_id','') or ''}",
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
