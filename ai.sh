#!/bin/bash

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

# 优先加载配置文件路径
CLAUDE_CONFIG_FILE="$(dirname "$0")/claude_configs.json"
CODEX_CONFIG_FILE="$(dirname "$0")/codex_configs.json"
HEALTH_CHECK_URL="https://check-cx.59188888.xyz/health"

# 健康检查数据缓存（避免频繁请求）
HEALTH_CHECK_CACHE_FILE="/tmp/ai_health_check_cache.json"
HEALTH_CHECK_CACHE_TTL=60  # 缓存60秒

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
    STATUS_UNKNOWN="${GRAY}○${RESET}"
    STATUS_OK_TEXT="${GREEN}正常${RESET}"
    STATUS_ERROR_TEXT="${RED}错误${RESET}"
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
    STATUS_UNKNOWN="⚪"
    STATUS_OK_TEXT="正常"
    STATUS_ERROR_TEXT="错误"
    STATUS_UNKNOWN_TEXT="未知"
fi

# 函数：获取健康检查状态（实时拉取，不使用缓存）
fetch_health_status() {
    echo -e "${GRAY}正在拉取渠道状态...${RESET}" >&2
    local response=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null)
    if [[ $? -eq 0 && -n "$response" ]]; then
        echo "$response"
    else
        echo '{"services":{}}'
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

# 函数：根据channel_id获取服务状态和lastCheck时间（从已拉取的数据中）
get_channel_info_from_data() {
    local channel_id="$1"
    local health_data="$2"
    
    local status=$(echo "$health_data" | jq -r ".services.\"$channel_id\".status // \"unknown\"" 2>/dev/null)
    local last_check=$(echo "$health_data" | jq -r ".services.\"$channel_id\".lastCheck // \"\"" 2>/dev/null)
    
    if [[ "$status" == "null" || "$status" == "" ]]; then
        echo "unknown||"
    else
        echo "$status|$last_check|"
    fi
}

# 函数：根据channel_id获取服务状态和lastCheck时间
get_channel_status() {
    local channel_id="$1"
    local health_data=$(fetch_health_status)
    
    local status=$(echo "$health_data" | jq -r ".services.\"$channel_id\".status // \"unknown\"" 2>/dev/null)
    local last_check=$(echo "$health_data" | jq -r ".services.\"$channel_id\".lastCheck // \"\"" 2>/dev/null)
    
    if [[ "$status" == "null" || "$status" == "" ]]; then
        echo "unknown|"
    else
        echo "$status|$last_check"
    fi
}

# 函数：显示帮助信息
show_help() {
    echo "AI 配置管理工具 v1.7.0"
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

# 函数：初始化配置文件
init_config_file() {
    local config_file="$1"
    if [[ ! -f "$config_file" ]]; then
        echo '{"configs":[]}' > "$config_file"
    fi
}

# 函数：添加配置
add_config() {
    local ai_type="$1"
    local config_file
    
    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
        init_config_file "$config_file"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
        init_config_file "$config_file"
    else
        echo "[Error] 无效的AI类型: $ai_type (应为 claude 或 codex)"
        exit 1
    fi
    
    echo "添加新配置 ($ai_type):"
    read -p "配置名称: " name
    read -p "渠道ID (channel_id，用于匹配健康检查，可选): " channel_id
    
    if [[ "$ai_type" == "claude" ]]; then
        read -p "Token: " token
        read -p "URL: " url
    else
        read -p "API Key: " api_key
        read -p "Base URL: " base_url
    fi
    
    read -p "输入价格 (例如: ¥1.5/1M tokens): " input_price
    read -p "输出价格 (例如: ¥1.5/1M tokens): " output_price
    read -p "描述 (可选): " description
    
    # 构建新配置JSON
    local new_config
    if [[ "$ai_type" == "claude" ]]; then
        new_config=$(jq -n \
            --arg name "$name" \
            --arg token "$token" \
            --arg url "$url" \
            --arg input "$input_price" \
            --arg output "$output_price" \
            --arg desc "$description" \
            --arg channel_id "$channel_id" \
            '{
                name: $name,
                token: $token,
                url: $url,
                channel_id: (if $channel_id == "" then null else $channel_id end),
                pricing: {
                    input: $input,
                    output: $output,
                    description: $desc
                }
            }')
    else
        new_config=$(jq -n \
            --arg name "$name" \
            --arg api_key "$api_key" \
            --arg base_url "$base_url" \
            --arg input "$input_price" \
            --arg output "$output_price" \
            --arg desc "$description" \
            --arg channel_id "$channel_id" \
            '{
                name: $name,
                api_key: $api_key,
                base_url: $base_url,
                channel_id: (if $channel_id == "" then null else $channel_id end),
                pricing: {
                    input: $input,
                    output: $output,
                    description: $desc
                }
            }')
    fi
    
    # 添加到配置文件
    jq ".configs += [$new_config]" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    echo "[Success] 配置已添加"
}

# 函数：编辑配置
edit_config() {
    local ai_type="$1"
    local index="$2"
    local config_file
    
    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi
    
    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi
    
    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $index -lt 0 || $index -ge $config_count ]]; then
        echo "[Error] 无效的配置索引: $index (范围: 0-$((config_count-1)))"
        exit 1
    fi
    
    echo "编辑配置 ($ai_type) #$index:"
    
    # 显示当前配置
    local current_name=$(jq -r ".configs[$index].name" "$config_file")
    local current_channel_id=$(jq -r ".configs[$index].channel_id // \"\"" "$config_file")
    echo "当前配置: $current_name"
    echo ""
    
    read -p "配置名称 [回车保持 '$current_name']: " name
    name=${name:-$current_name}
    
    read -p "渠道ID [回车保持 '$current_channel_id']: " channel_id
    channel_id=${channel_id:-$current_channel_id}
    
    if [[ "$ai_type" == "claude" ]]; then
        local current_token=$(jq -r ".configs[$index].token" "$config_file")
        local current_url=$(jq -r ".configs[$index].url" "$config_file")
        read -p "Token [回车保持当前值]: " token
        token=${token:-$current_token}
        read -p "URL [回车保持当前值]: " url
        url=${url:-$current_url}
        
        jq ".configs[$index] |= . + {
            name: \"$name\",
            token: \"$token\",
            url: \"$url\",
            channel_id: (if \"$channel_id\" == \"\" then null else \"$channel_id\" end)
        }" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    else
        local current_api_key=$(jq -r ".configs[$index].api_key" "$config_file")
        local current_base_url=$(jq -r ".configs[$index].base_url" "$config_file")
        read -p "API Key [回车保持当前值]: " api_key
        api_key=${api_key:-$current_api_key}
        read -p "Base URL [回车保持当前值]: " base_url
        base_url=${base_url:-$current_base_url}
        
        jq ".configs[$index] |= . + {
            name: \"$name\",
            api_key: \"$api_key\",
            base_url: \"$base_url\",
            channel_id: (if \"$channel_id\" == \"\" then null else \"$channel_id\" end)
        }" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
    fi
    
    echo "[Success] 配置已更新"
}

# 函数：删除配置
delete_config() {
    local ai_type="$1"
    local index="$2"
    local config_file
    
    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi
    
    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi
    
    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $index -lt 0 || $index -ge $config_count ]]; then
        echo "[Error] 无效的配置索引: $index (范围: 0-$((config_count-1)))"
        exit 1
    fi
    
    local config_name=$(jq -r ".configs[$index].name" "$config_file")
    echo "确定要删除配置 '$config_name' (索引 $index) 吗? (y/N)"
    read -p "> " confirm
    
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        jq "del(.configs[$index])" "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
        echo "[Success] 配置已删除"
    else
        echo "[Cancel] 已取消删除"
    fi
}

# 函数：列出配置
list_configs() {
    local ai_type="$1"
    local config_file
    
    if [[ "$ai_type" == "claude" ]]; then
        config_file="$CLAUDE_CONFIG_FILE"
    elif [[ "$ai_type" == "codex" ]]; then
        config_file="$CODEX_CONFIG_FILE"
    else
        echo "[Error] 无效的AI类型: $ai_type"
        exit 1
    fi
    
    if [[ ! -f "$config_file" ]]; then
        echo "[Error] 配置文件不存在: $config_file"
        exit 1
    fi
    
    local config_count=$(jq '.configs | length' "$config_file")
    if [[ $config_count -eq 0 ]]; then
        echo "没有配置"
        return
    fi
    
    # 拉取实时状态（仅在list_configs中使用）
    echo -e "${GRAY}正在拉取渠道状态...${RESET}"
    local health_data=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null)
    if [[ $? -ne 0 || -z "$health_data" ]]; then
        health_data='{"services":{}}'
    fi
    
    echo -e "${BOLD}配置列表 ($ai_type):${RESET}"
    echo "=========================================="
    
    for ((i=0; i<config_count; i++)); do
        local name=$(jq -r ".configs[$i].name" "$config_file")
        local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$config_file")
        local status=""
        local status_icon=""
        local last_check=""
        
        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
            local status_val=$(echo "$channel_info" | cut -d'|' -f1)
            last_check=$(echo "$channel_info" | cut -d'|' -f2)
            
            if [[ "$status_val" == "ok" ]]; then
                status_icon="$STATUS_OK"
                status="$STATUS_OK_TEXT"
            elif [[ "$status_val" == "error" ]]; then
                status_icon="$STATUS_ERROR"
                status="$STATUS_ERROR_TEXT"
            else
                status_icon="$STATUS_UNKNOWN"
                status="$STATUS_UNKNOWN_TEXT"
            fi
        else
            status_icon="$STATUS_UNKNOWN"
            status="$STATUS_UNKNOWN_TEXT (未配置)"
        fi
        
        echo -e "${BOLD}[$i]${RESET} $status_icon ${GOLD}$name${RESET}"
        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            local time_ago=$(format_time_ago "$last_check")
            if [[ -n "$time_ago" ]]; then
                echo -e "    ${GRAY}渠道ID:${RESET} ${CYAN}$channel_id${RESET} ${GRAY}|${RESET} ${GRAY}状态:${RESET} $status ${GRAY}($time_ago)${RESET}"
            else
                echo -e "    ${GRAY}渠道ID:${RESET} ${CYAN}$channel_id${RESET} ${GRAY}|${RESET} ${GRAY}状态:${RESET} $status"
            fi
        fi
        
        if [[ "$ai_type" == "claude" ]]; then
            local url=$(jq -r ".configs[$i].url" "$config_file")
            echo -e "    ${GRAY}URL:${RESET} $url"
        else
            local base_url=$(jq -r ".configs[$i].base_url" "$config_file")
            echo -e "    ${GRAY}Base URL:${RESET} $base_url"
        fi
        echo ""
    done
}

# 函数：显示所有渠道状态
show_status() {
    echo -e "${BOLD}渠道状态检查${RESET}"
    echo "=========================================="
    
    # 拉取实时状态
    echo -e "${GRAY}正在拉取渠道状态...${RESET}"
    local health_data=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null)
    if [[ $? -ne 0 || -z "$health_data" ]]; then
        health_data='{"services":{}}'
    fi
    
    local services=$(echo "$health_data" | jq -r '.services | keys[]' 2>/dev/null)
    
    if [[ -z "$services" ]]; then
        echo -e "${YELLOW}[Warning] 无法获取渠道状态${RESET}"
        return
    fi
    
    echo "$health_data" | jq -r '.services | to_entries[] | "\(.key): \(.value.status): \(.value.lastCheck)"' 2>/dev/null | while IFS=':' read -r channel_id status_val last_check; do
        # 清理变量（去除空格）
        channel_id=$(echo "$channel_id" | xargs)
        status_val=$(echo "$status_val" | xargs)
        last_check=$(echo "$last_check" | xargs)
        
        local time_ago=$(format_time_ago "$last_check")
        
        if [[ "$status_val" == "ok" ]]; then
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_OK ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GREEN}ok${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_OK ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GREEN}ok${RESET}"
            fi
        elif [[ "$status_val" == "error" ]]; then
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_ERROR ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${RED}error${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_ERROR ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${RED}error${RESET}"
            fi
        else
            if [[ -n "$time_ago" ]]; then
                echo -e "$STATUS_UNKNOWN ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GRAY}unknown${RESET} ${GRAY}($time_ago)${RESET}"
            else
                echo -e "$STATUS_UNKNOWN ${CYAN}$channel_id${RESET} ${GRAY}-${RESET} ${GRAY}unknown${RESET}"
            fi
        fi
    done
    
    echo ""
    echo -e "${BOLD}配置中的渠道匹配:${RESET}"
    echo "----------------------------------------"
    
    # 检查Claude配置
    if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
        local claude_count=$(jq '.configs | length' "$CLAUDE_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<claude_count; i++)); do
            local name=$(jq -r ".configs[$i].name" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
                local status=$(echo "$channel_info" | cut -d'|' -f1)
                local last_check=$(echo "$channel_info" | cut -d'|' -f2)
                local time_ago=$(format_time_ago "$last_check")
                
                if [[ "$status" == "ok" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_OK ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_OK ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "error" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_ERROR ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_ERROR ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                else
                    echo -e "$STATUS_UNKNOWN ${BOLD}Claude:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}- 未找到${RESET}"
                fi
            fi
        done
    fi
    
    # 检查Codex配置
    if [[ -f "$CODEX_CONFIG_FILE" ]]; then
        local codex_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<codex_count; i++)); do
            local name=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
            local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CODEX_CONFIG_FILE" 2>/dev/null)
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                local channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
                local status=$(echo "$channel_info" | cut -d'|' -f1)
                local last_check=$(echo "$channel_info" | cut -d'|' -f2)
                local time_ago=$(format_time_ago "$last_check")
                
                if [[ "$status" == "ok" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_OK ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_OK ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                elif [[ "$status" == "error" ]]; then
                    if [[ -n "$time_ago" ]]; then
                        echo -e "$STATUS_ERROR ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}($time_ago)${RESET}"
                    else
                        echo -e "$STATUS_ERROR ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET}"
                    fi
                else
                    echo -e "$STATUS_UNKNOWN ${BOLD}Codex:${RESET} ${GOLD}$name${RESET} ${GRAY}($channel_id)${RESET} ${GRAY}- 未找到${RESET}"
                fi
            fi
        done
    fi
}

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

# 以下是原有的交互式模式代码
# 清除屏幕内容
clear

# 检查配置文件是否存在
CLAUDE_CONFIG_EXISTS=false
CODEX_CONFIG_EXISTS=false

if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
    CLAUDE_CONFIG_EXISTS=true
fi

if [[ -f "$CODEX_CONFIG_FILE" ]]; then
    CODEX_CONFIG_EXISTS=true
fi

# 选择AI类型（使用循环，支持输入0返回）
while true; do
    # 获取当前Claude配置
    CURRENT_CLAUDE_CONFIG="未配置"
    if [[ $CLAUDE_CONFIG_EXISTS == true && -n "$ANTHROPIC_AUTH_TOKEN" && -n "$ANTHROPIC_BASE_URL" ]]; then
        config_count=$(jq '.configs | length' "$CLAUDE_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<config_count; i++)); do
            token=$(jq -r ".configs[$i].token" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            url=$(jq -r ".configs[$i].url" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            if [[ "$token" == "$ANTHROPIC_AUTH_TOKEN" && "$url" == "$ANTHROPIC_BASE_URL" ]]; then
                CURRENT_CLAUDE_CONFIG=$(jq -r ".configs[$i].name" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
                break
            fi
        done
    fi

    # 获取当前Codex配置
    CURRENT_CODEX_CONFIG="未配置"
    if [[ $CODEX_CONFIG_EXISTS == true && -n "$OPENAI_API_KEY" && -n "$OPENAI_BASE_URL" ]]; then
        config_count=$(jq '.configs | length' "$CODEX_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<config_count; i++)); do
            api_key=$(jq -r ".configs[$i].api_key" "$CODEX_CONFIG_FILE" 2>/dev/null)
            base_url=$(jq -r ".configs[$i].base_url" "$CODEX_CONFIG_FILE" 2>/dev/null)
            if [[ "$api_key" == "$OPENAI_API_KEY" && "$base_url" == "$OPENAI_BASE_URL" ]]; then
                CURRENT_CODEX_CONFIG=$(jq -r ".configs[$i].name" "$CODEX_CONFIG_FILE" 2>/dev/null)
                break
            fi
        done
    fi

    # 选择AI类型
    clear
    echo "=========================================="
    echo "AI 配置切换工具"
    echo "=========================================="
    echo ""
    echo "请选择 AI 类型:"
    echo "1) Claude (当前: $CURRENT_CLAUDE_CONFIG)"
    echo "2) Codex (OpenAI) (当前: $CURRENT_CODEX_CONFIG)"
    echo ""
    read -p "选择 [1/2]: " ai_choice

    # 根据选择设置配置文件和环境变量类型
    if [ "$ai_choice" = "1" ]; then
        AI_TYPE="claude"
        CONFIG_FILE="$(dirname "$0")/claude_configs.json"
        ENV_TOKEN_NAME="ANTHROPIC_AUTH_TOKEN"
        ENV_URL_NAME="ANTHROPIC_BASE_URL"
        DISPLAY_NAME="Claude"
    elif [ "$ai_choice" = "2" ]; then
        AI_TYPE="codex"
        CONFIG_FILE="$(dirname "$0")/codex_configs.json"
        ENV_TOKEN_NAME="OPENAI_API_KEY"
        ENV_URL_NAME="OPENAI_BASE_URL"
        DISPLAY_NAME="Codex"
    else
        echo "[Error] 无效选择"
        continue
    fi

clear

# 检查配置文件是否存在
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "[Error] 配置文件不存在: $CONFIG_FILE"
    echo "请创建配置文件，JSON格式"
    exit 1
fi

# 检查是否通过source运行
echo "=========================================="
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "$DISPLAY_NAME 配置切换工具"
    echo "永久设置模式"
    FORCE_PERMANENT=true
    TEMP_SETTING_AVAILABLE=false
else
    echo "$DISPLAY_NAME 配置切换工具"
    echo ""
    TEMP_SETTING_AVAILABLE=true
fi
echo "作者：Lynn v1.7.0"
echo "=========================================="

# 读取配置文件并显示选项
echo ""

# 获取配置数量
config_count=$(jq '.configs | length' "$CONFIG_FILE")

# 创建临时文件来存储排序后的配置
temp_file=$(mktemp)

# 在脚本开始时拉取健康检查状态（全局使用，运行期间都可以使用）
echo -e "${GRAY}正在拉取渠道状态...${RESET}"
health_data=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null)
if [[ $? -ne 0 || -z "$health_data" ]]; then
    health_data='{"services":{}}'
fi

# 获取当前配置名称（用于高亮显示）
current_config_name=""
# 根据AI类型检查不同的环境变量
if [ "$AI_TYPE" = "claude" ]; then
    CURRENT_TOKEN="$ANTHROPIC_AUTH_TOKEN"
    CURRENT_URL="$ANTHROPIC_BASE_URL"
    TOKEN_FIELD="token"
    URL_FIELD="url"
else
    CURRENT_TOKEN="$OPENAI_API_KEY"
    CURRENT_URL="$OPENAI_BASE_URL"
    TOKEN_FIELD="api_key"
    URL_FIELD="base_url"
fi

if [[ -n "$CURRENT_TOKEN" && -n "$CURRENT_URL" ]]; then
    config_count_check=$(jq '.configs | length' "$CONFIG_FILE")
    for ((i=0; i<config_count_check; i++)); do
        token=$(jq -r ".configs[$i].$TOKEN_FIELD" "$CONFIG_FILE")
        url=$(jq -r ".configs[$i].$URL_FIELD" "$CONFIG_FILE")
        if [[ "$token" == "$CURRENT_TOKEN" && "$url" == "$CURRENT_URL" ]]; then
            current_config_name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
            break
        fi
    done
fi

# 将配置信息写入临时文件，包含索引信息
for ((i=0; i<config_count; i++)); do
    name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
    channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CONFIG_FILE")
    input_price=$(jq -r ".configs[$i].pricing.input" "$CONFIG_FILE")
    output_price=$(jq -r ".configs[$i].pricing.output" "$CONFIG_FILE")
    description=$(jq -r ".configs[$i].pricing.description" "$CONFIG_FILE")
    
    # 获取渠道状态
    status_icon=""
    status_color=""
    last_check_time=""
    if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
        channel_info=$(get_channel_info_from_data "$channel_id" "$health_data")
        status=$(echo "$channel_info" | cut -d'|' -f1)
        last_check_time=$(echo "$channel_info" | cut -d'|' -f2)
        
        if [[ "$status" == "ok" ]]; then
            status_icon="$STATUS_OK"
            status_color="ok"
        elif [[ "$status" == "error" ]]; then
            status_icon="$STATUS_ERROR"
            status_color="error"
        else
            status_icon="$STATUS_UNKNOWN"
            status_color="unknown"
        fi
    else
        # 没有channel_id时，使用灰色点
        status_icon="$STATUS_UNKNOWN"
        status_color=""
    fi
    
    # 提取价格数字用于排序（处理 ¥0.9/1M tokens 或 $3/1M tokens 格式）
    input_num=$(echo "$input_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    output_num=$(echo "$output_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    
    # 如果无法提取数字，使用0
    input_num=${input_num:-0}
    output_num=${output_num:-0}
    
    # 检查是否为美元价格，如果是则乘以7转换为人民币
    if [[ "$input_price" == *"$"* ]]; then
        input_num=$(echo "$input_num * 7" | bc -l 2>/dev/null || echo "$input_num")
    fi
    if [[ "$output_price" == *"$"* ]]; then
        output_num=$(echo "$output_num * 7" | bc -l 2>/dev/null || echo "$output_num")
    fi
    
    # 计算总价格（输入+输出）
    total_price=$(echo "$input_num + $output_num" | bc -l 2>/dev/null || echo "0")
    
    echo "$i|$name|$input_price|$output_price|$description|$total_price|$status_icon|$channel_id|$status_color|$last_check_time" >> "$temp_file"
done

    # 按总价格排序（从低到高）
    if command -v bc &> /dev/null; then
        sort -t'|' -k6,6n "$temp_file" > "${temp_file}.sorted"
        mv "${temp_file}.sorted" "$temp_file"
    else
        echo "[Warning] 未找到bc命令，将按原始顺序显示"
    fi

# 显示排序后的配置
line_num=1
while IFS='|' read -r index name input_price output_price description total_price status_icon channel_id status_color last_check_time; do
    # 判断是否是当前配置
    if [[ "$name" == "$current_config_name" ]]; then
        name_color="${GOLD}"
    else
        name_color="${WHITE}"
    fi
    
    # 显示配置名称（前面始终有点，有状态用对应颜色，无状态用灰色）
    if [[ -n "$last_check_time" && "$last_check_time" != "" ]]; then
        # 格式化时间显示为"xx分钟前"
        time_ago=$(format_time_ago "$last_check_time")
        if [[ -n "$time_ago" ]]; then
            echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET} ${GRAY}($time_ago)${RESET}"
        else
            echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET}"
        fi
    else
        echo -e "${BOLD}$line_num)${RESET} $status_icon ${name_color}$name${RESET}"
    fi
    
    # 显示价格信息（全部改为灰色）
    echo -e "    ${GRAY}输入: $input_price | 输出: $output_price${RESET}"
    
    # 计算并显示转换后的人民币价格
    input_num=$(echo "$input_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    output_num=$(echo "$output_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    input_num=${input_num:-0}
    output_num=${output_num:-0}
    
    # 检查是否为美元价格，如果是则乘以7转换为人民币
    if [[ "$input_price" == *"$"* ]]; then
        input_cny=$(echo "$input_num * 7" | bc -l 2>/dev/null || echo "$input_num")
        output_cny=$(echo "$output_num * 7" | bc -l 2>/dev/null || echo "$output_num")
        echo -e "    ${GRAY}(约 ¥${input_cny}/1M tokens | ¥${output_cny}/1M tokens)${RESET}"
    fi
    
    # 只有当描述不为空且不是null时才显示（改为灰色）
    if [[ -n "$description" && "$description" != "null" ]]; then
        echo -e "    ${GRAY}$description${RESET}"
    fi
    echo ""
    
    # 保存索引映射
    eval "config_index_$line_num=$index"
    
    line_num=$((line_num + 1))
done < "$temp_file"

# 清理临时文件
rm -f "$temp_file"

# 在列表末尾显示当前设置
if [[ -n "$current_config_name" ]]; then
    echo "当前设置：$current_config_name"
else
    echo "当前设置：未配置"
fi
echo "=========================================="
echo "0) 返回AI类型选择"
echo ""

read -p "#? " choice

# 如果输入0，返回AI类型选择
if [[ "$choice" == "0" ]]; then
    continue
fi

if [[ -z "$FORCE_PERMANENT" ]]; then
    echo ""
    echo "请选择设置方式:"
    echo "1) 临时设置 (仅当前终端会话有效)"
    echo "2) 永久设置 (写入配置文件)"
    
    read -p "设置方式 [1/2]: " mode
else
    mode="2"
fi

# 验证选择并获取配置
if [[ $choice -ge 1 && $choice -le $((line_num-1)) ]]; then
    # 使用保存的索引映射
    eval "index=\$config_index_$choice"
    CONFIG_NAME=$(jq -r ".configs[$index].name" "$CONFIG_FILE")
    
    # 根据AI类型读取不同的字段
    if [ "$AI_TYPE" = "claude" ]; then
        TOKEN=$(jq -r ".configs[$index].token" "$CONFIG_FILE")
        BASE_URL=$(jq -r ".configs[$index].url" "$CONFIG_FILE")
    else
        TOKEN=$(jq -r ".configs[$index].api_key" "$CONFIG_FILE")
        BASE_URL=$(jq -r ".configs[$index].base_url" "$CONFIG_FILE")
    fi
else
    echo "[Error] 无效选择"
    continue
fi

if [ "$mode" = "1" ]; then
    # 临时设置
    export "$ENV_TOKEN_NAME=$TOKEN"
    export "$ENV_URL_NAME=$BASE_URL"
    echo "已切换到: $CONFIG_NAME (临时设置)"
    echo "仅在当前终端会话中有效"
    break
elif [ "$mode" = "2" ]; then
    # 永久设置
    # 检测当前shell类型
    if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
        SHELL_CONFIG_FILE="$HOME/.zshrc"
    else
        SHELL_CONFIG_FILE="$HOME/.bash_profile"
    fi

    # 1. 先在内存中准备好要输出的内容
    output_message="切换配置任务清单:
■ 配置已写入: $SHELL_CONFIG_FILE
□ 刷新配置生效
□ 请手动执行以下命令以刷新配置：
   source $SHELL_CONFIG_FILE

✓ 已切换到: $CONFIG_NAME (永久设置)"

    # 2. 执行文件写入操作
    # 移除旧的配置（如果存在）
    grep -v "$ENV_TOKEN_NAME=" "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" 2>/dev/null || touch "$SHELL_CONFIG_FILE.tmp"
    grep -v "$ENV_URL_NAME=" "$SHELL_CONFIG_FILE.tmp" > "$SHELL_CONFIG_FILE.tmp2"
    mv "$SHELL_CONFIG_FILE.tmp2" "$SHELL_CONFIG_FILE"
    rm -f "$SHELL_CONFIG_FILE.tmp"
    
    # 添加新配置
    echo "export $ENV_TOKEN_NAME=\"$TOKEN\"" >> "$SHELL_CONFIG_FILE"
    echo "export $ENV_URL_NAME=\"$BASE_URL\"" >> "$SHELL_CONFIG_FILE"

    # 3. 最后，一次性打印所有输出
    echo "$output_message"
    break
else
    echo "[Error] 无效的设置方式选择"
    continue
fi
done
