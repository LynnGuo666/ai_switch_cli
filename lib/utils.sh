#!/bin/bash
# 通用工具函数

# 函数：将URL格式化为可点击链接（使用ANSI转义序列）
format_clickable_url() {
    local url="$1"
    if [[ -z "$url" || "$url" == "null" ]]; then
        echo ""
        return
    fi

    # 使用 OSC 8 转义序列创建可点击链接
    # 格式: \033]8;;URL\033\\显示文本\033]8;;\033\\
    # 或者使用 \a (bell) 代替 \033\\: \033]8;;URL\a显示文本\033]8;;\a
    if [[ -t 1 ]]; then
        # 在终端中，使用可点击链接格式
        # 使用 printf 而不是 echo -e，避免转义序列被再次处理
        printf "\033]8;;%s\033\\%s\033]8;;\033\\" "$url" "$url"
    else
        # 非终端环境，直接输出URL
        echo "$url"
    fi
}

# 函数：格式化时间显示为"xx分钟前"（处理UTC时间）
format_time_ago() {
    local utc_time="$1"
    if [[ -z "$utc_time" || "$utc_time" == "null" || "$utc_time" == "" ]]; then
        echo ""
        return
    fi

    # 检查是否有date命令
    if ! command -v date &> /dev/null; then
        echo "$(echo "$utc_time" | cut -d'T' -f2 | cut -d'.' -f1)"
        return
    fi

    # 解析UTC时间字符串（格式：2025-10-30T09:30:06.294Z）
    local date_part=$(echo "$utc_time" | cut -d'T' -f1)
    local time_part=$(echo "$utc_time" | cut -d'T' -f2 | cut -d'.' -f1 | cut -d'Z' -f1)

    # macOS date命令
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # 提取年月日时分秒
        local year=$(echo "$date_part" | cut -d'-' -f1)
        local month=$(echo "$date_part" | cut -d'-' -f2)
        local day=$(echo "$date_part" | cut -d'-' -f3)
        local hour=$(echo "$time_part" | cut -d':' -f1)
        local minute=$(echo "$time_part" | cut -d':' -f2)
        local second=$(echo "$time_part" | cut -d':' -f3)

        # 转换为Unix时间戳（UTC）
        local utc_timestamp=$(date -u -j -f "%Y-%m-%d %H:%M:%S" "${year}-${month}-${day} ${hour}:${minute}:${second}" "+%s" 2>/dev/null)

        if [[ -n "$utc_timestamp" ]]; then
            local current_timestamp=$(date +%s)
            local diff_seconds=$((current_timestamp - utc_timestamp))

            if [[ $diff_seconds -lt 0 ]]; then
                echo "刚刚"
                return
            fi

            local diff_minutes=$((diff_seconds / 60))

            if [[ $diff_minutes -lt 1 ]]; then
                echo "刚刚"
            elif [[ $diff_minutes -lt 60 ]]; then
                echo "${diff_minutes}分钟前"
            else
                local diff_hours=$((diff_minutes / 60))
                if [[ $diff_hours -lt 24 ]]; then
                    echo "${diff_hours}小时前"
                else
                    local diff_days=$((diff_hours / 24))
                    echo "${diff_days}天前"
                fi
            fi
        else
            echo "$time_part"
        fi
    else
        # Linux date命令（GNU date）
        local utc_timestamp=$(date -d "$utc_time" +%s 2>/dev/null)

        if [[ -n "$utc_timestamp" ]]; then
            local current_timestamp=$(date +%s)
            local diff_seconds=$((current_timestamp - utc_timestamp))

            if [[ $diff_seconds -lt 0 ]]; then
                echo "刚刚"
                return
            fi

            local diff_minutes=$((diff_seconds / 60))

            if [[ $diff_minutes -lt 1 ]]; then
                echo "刚刚"
            elif [[ $diff_minutes -lt 60 ]]; then
                echo "${diff_minutes}分钟前"
            else
                local diff_hours=$((diff_minutes / 60))
                if [[ $diff_hours -lt 24 ]]; then
                    echo "${diff_hours}小时前"
                else
                    local diff_days=$((diff_hours / 24))
                    echo "${diff_days}天前"
                fi
            fi
        else
            echo "$time_part"
        fi
    fi
}

# 函数：显示帮助信息
show_help() {
    echo "AI 配置管理工具 v1.8.0"
    echo ""
    echo "用法:"
    echo "  $0                    # 交互式配置切换"
    echo "  $0 --add <type>      # 添加配置 (type: claude|codex)"
    echo "  $0 --edit <type> <id># 编辑配置"
    echo "  $0 --delete <type> <id> # 删除配置"
    echo "  $0 --list <type>     # 列出所有配置 (type: claude|codex)"
    echo "  $0 --status          # 显示所有渠道状态"
    echo "  $0 --help            # 显示帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 --add claude      # 添加Claude配置"
    echo "  $0 --list codex      # 列出Codex配置"
    echo "  $0 --edit claude 0   # 编辑Claude配置索引0"
    echo "  $0 --status          # 显示渠道状态"
}
