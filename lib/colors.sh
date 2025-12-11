#!/bin/bash
# 颜色定义和状态图标

# 颜色定义
if [[ -t 1 ]]; then
    # 支持颜色输出
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    GOLD='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    GRAY='\033[0;90m'
    WHITE='\033[0;37m'
    BOLD='\033[1m'
    RESET='\033[0m'
    # 状态图标和颜色
    STATUS_OK="${GREEN}●${RESET}"
    STATUS_ERROR="${RED}●${RESET}"
    STATUS_TIMEOUT="${YELLOW}●${RESET}"
    STATUS_UNKNOWN="${GRAY}○${RESET}"
    STATUS_OK_TEXT="${GREEN}正常${RESET}"
    STATUS_ERROR_TEXT="${RED}错误${RESET}"
    STATUS_TIMEOUT_TEXT="${YELLOW}超时${RESET}"
    STATUS_UNKNOWN_TEXT="${GRAY}未知${RESET}"
else
    # 不支持颜色输出（非终端）
    RED=''
    GREEN=''
    YELLOW=''
    GOLD=''
    BLUE=''
    CYAN=''
    GRAY=''
    WHITE=''
    BOLD=''
    RESET=''
    STATUS_OK="🟢"
    STATUS_ERROR="🔴"
    STATUS_TIMEOUT="🟡"
    STATUS_UNKNOWN="⚪"
    STATUS_OK_TEXT="正常"
    STATUS_ERROR_TEXT="错误"
    STATUS_TIMEOUT_TEXT="超时"
    STATUS_UNKNOWN_TEXT="未知"
fi
