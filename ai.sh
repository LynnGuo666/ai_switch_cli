#!/bin/bash

# AI 配置管理工具 v1.8.0
# 主入口文件

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检查jq是否可用
if ! command -v jq &> /dev/null; then
    echo "[Error] 需要安装jq来解析JSON文件"
    echo "macOS: brew install jq"
    echo "Ubuntu: sudo apt install jq"
    exit 1
fi

# 检查curl是否可用
if ! command -v curl &> /dev/null; then
    echo "[Error] 需要安装curl来拉取渠道状态"
    echo "macOS: brew install curl"
    echo "Ubuntu: sudo apt install curl"
    exit 1
fi

# 配置文件路径
CLAUDE_CONFIG_FILE="$SCRIPT_DIR/claude_configs.json"
CODEX_CONFIG_FILE="$SCRIPT_DIR/codex_configs.json"
HEALTH_CHECK_CONFIG_FILE="$SCRIPT_DIR/health_check_configs.json"

# 检测是否通过 source 运行（在加载模块前检测）
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # 直接运行脚本
    IS_SOURCED=false
else
    # 通过 source 运行
    IS_SOURCED=true
fi

# 加载模块
source "$SCRIPT_DIR/lib/colors.sh"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/health.sh"
source "$SCRIPT_DIR/lib/codex.sh"
source "$SCRIPT_DIR/lib/config.sh"
source "$SCRIPT_DIR/lib/interactive.sh"

# 解析命令行参数
if [[ $# -gt 0 ]]; then
    case "$1" in
        --add)
            if [[ -z "$2" ]]; then
                echo "[Error] 请指定AI类型 (claude|codex)"
                exit 1
            fi
            add_config "$2"
            exit 0
            ;;
        --edit)
            if [[ -z "$2" || -z "$3" ]]; then
                echo "[Error] 用法: $0 --edit <type> <index>"
                exit 1
            fi
            edit_config "$2" "$3"
            exit 0
            ;;
        --delete)
            if [[ -z "$2" || -z "$3" ]]; then
                echo "[Error] 用法: $0 --delete <type> <index>"
                exit 1
            fi
            delete_config "$2" "$3"
            exit 0
            ;;
        --list)
            if [[ -z "$2" ]]; then
                echo "[Error] 请指定AI类型 (claude|codex)"
                exit 1
            fi
            list_configs "$2"
            exit 0
            ;;
        --status)
            show_status
            exit 0
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "[Error] 未知参数: $1"
            echo "使用 $0 --help 查看帮助"
            exit 1
            ;;
    esac
fi

# 运行交互式界面
run_interactive
