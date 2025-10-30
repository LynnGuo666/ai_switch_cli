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

# 函数：获取健康检查状态
fetch_health_status() {
    local cache_age=999999
    if [[ -f "$HEALTH_CHECK_CACHE_FILE" ]]; then
        cache_age=$(($(date +%s) - $(stat -f %m "$HEALTH_CHECK_CACHE_FILE" 2>/dev/null || stat -c %Y "$HEALTH_CHECK_CACHE_FILE" 2>/dev/null || echo 0)))
    fi
    
    if [[ $cache_age -lt $HEALTH_CHECK_CACHE_TTL ]]; then
        cat "$HEALTH_CHECK_CACHE_FILE" 2>/dev/null
        return
    fi
    
    local response=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null)
    if [[ $? -eq 0 && -n "$response" ]]; then
        echo "$response" > "$HEALTH_CHECK_CACHE_FILE"
        echo "$response"
    else
        # 如果请求失败，尝试使用缓存
        cat "$HEALTH_CHECK_CACHE_FILE" 2>/dev/null || echo '{"services":{}}'
    fi
}

# 函数：根据channel_id获取服务状态
get_channel_status() {
    local channel_id="$1"
    local health_data=$(fetch_health_status)
    
    local status=$(echo "$health_data" | jq -r ".services.\"$channel_id\".status // \"unknown\"" 2>/dev/null)
    local last_check=$(echo "$health_data" | jq -r ".services.\"$channel_id\".lastCheck // \"\"" 2>/dev/null)
    
    if [[ "$status" == "null" || "$status" == "" ]]; then
        echo "unknown"
    else
        echo "$status"
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
    
    echo "配置列表 ($ai_type):"
    echo "=========================================="
    
    for ((i=0; i<config_count; i++)); do
        local name=$(jq -r ".configs[$i].name" "$config_file")
        local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$config_file")
        local status=""
        
        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            status=$(get_channel_status "$channel_id")
            if [[ "$status" == "ok" ]]; then
                status="🟢 正常"
            elif [[ "$status" == "error" ]]; then
                status="🔴 错误"
            else
                status="⚪ 未知"
            fi
        else
            status="⚪ 未配置"
        fi
        
        echo "[$i] $name"
        if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
            echo "    渠道ID: $channel_id | 状态: $status"
        fi
        
        if [[ "$ai_type" == "claude" ]]; then
            local url=$(jq -r ".configs[$i].url" "$config_file")
            echo "    URL: $url"
        else
            local base_url=$(jq -r ".configs[$i].base_url" "$config_file")
            echo "    Base URL: $base_url"
        fi
        echo ""
    done
}

# 函数：显示所有渠道状态
show_status() {
    echo "渠道状态检查"
    echo "=========================================="
    
    local health_data=$(fetch_health_status)
    local services=$(echo "$health_data" | jq -r '.services | keys[]' 2>/dev/null)
    
    if [[ -z "$services" ]]; then
        echo "[Warning] 无法获取渠道状态"
        return
    fi
    
    echo "$health_data" | jq -r '.services | to_entries[] | "\(.key): \(.value.status) (最后检查: \(.value.lastCheck))"' 2>/dev/null | while IFS= read -r line; do
        local channel_id=$(echo "$line" | cut -d':' -f1)
        local status_part=$(echo "$line" | cut -d':' -f2-)
        
        if echo "$status_part" | grep -q "ok"; then
            echo "🟢 $channel_id - $status_part"
        elif echo "$status_part" | grep -q "error"; then
            echo "🔴 $channel_id - $status_part"
        else
            echo "⚪ $channel_id - $status_part"
        fi
    done
    
    echo ""
    echo "配置中的渠道匹配:"
    echo "----------------------------------------"
    
    # 检查Claude配置
    if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
        local claude_count=$(jq '.configs | length' "$CLAUDE_CONFIG_FILE" 2>/dev/null || echo "0")
        for ((i=0; i<claude_count; i++)); do
            local name=$(jq -r ".configs[$i].name" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            local channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CLAUDE_CONFIG_FILE" 2>/dev/null)
            if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
                local status=$(get_channel_status "$channel_id")
                if [[ "$status" == "ok" ]]; then
                    echo "🟢 Claude: $name ($channel_id)"
                elif [[ "$status" == "error" ]]; then
                    echo "🔴 Claude: $name ($channel_id)"
                else
                    echo "⚪ Claude: $name ($channel_id) - 未找到"
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
                local status=$(get_channel_status "$channel_id")
                if [[ "$status" == "ok" ]]; then
                    echo "🟢 Codex: $name ($channel_id)"
                elif [[ "$status" == "error" ]]; then
                    echo "🔴 Codex: $name ($channel_id)"
                else
                    echo "⚪ Codex: $name ($channel_id) - 未找到"
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
    exit 1
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

# 获取健康检查状态
health_data=$(fetch_health_status)

# 将配置信息写入临时文件，包含索引信息
for ((i=0; i<config_count; i++)); do
    name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
    channel_id=$(jq -r ".configs[$i].channel_id // \"\"" "$CONFIG_FILE")
    input_price=$(jq -r ".configs[$i].pricing.input" "$CONFIG_FILE")
    output_price=$(jq -r ".configs[$i].pricing.output" "$CONFIG_FILE")
    description=$(jq -r ".configs[$i].pricing.description" "$CONFIG_FILE")
    
    # 获取渠道状态
    status_icon=""
    if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
        status=$(get_channel_status "$channel_id")
        if [[ "$status" == "ok" ]]; then
            status_icon="🟢"
        elif [[ "$status" == "error" ]]; then
            status_icon="🔴"
        else
            status_icon="⚪"
        fi
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
    
    echo "$i|$name|$input_price|$output_price|$description|$total_price|$status_icon|$channel_id" >> "$temp_file"
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
while IFS='|' read -r index name input_price output_price description total_price status_icon channel_id; do
    echo "$line_num) $status_icon $name"
    echo "    输入: $input_price | 输出: $output_price"
    
    # 计算并显示转换后的人民币价格
    input_num=$(echo "$input_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    output_num=$(echo "$output_price" | grep -o '[0-9]*\.\?[0-9]*' | head -1)
    input_num=${input_num:-0}
    output_num=${output_num:-0}
    
    # 检查是否为美元价格，如果是则乘以7转换为人民币
    if [[ "$input_price" == *"$"* ]]; then
        input_cny=$(echo "$input_num * 7" | bc -l 2>/dev/null || echo "$input_num")
        output_cny=$(echo "$output_num * 7" | bc -l 2>/dev/null || echo "$output_num")
        echo "    (约 ¥${input_cny}/1M tokens | ¥${output_cny}/1M tokens)"
    fi
    
    # 显示渠道状态
    if [[ -n "$channel_id" && "$channel_id" != "null" && "$channel_id" != "" ]]; then
        status=$(get_channel_status "$channel_id")
        if [[ "$status" == "ok" ]]; then
            echo "    渠道状态: 🟢 正常 ($channel_id)"
        elif [[ "$status" == "error" ]]; then
            echo "    渠道状态: 🔴 错误 ($channel_id)"
        else
            echo "    渠道状态: ⚪ 未知 ($channel_id)"
        fi
    fi
    
    # 只有当描述不为空且不是null时才显示
    if [[ -n "$description" && "$description" != "null" ]]; then
        echo "    $description"
    fi
    echo ""
    
    # 保存索引映射
    eval "config_index_$line_num=$index"
    
    line_num=$((line_num + 1))
done < "$temp_file"

# 清理临时文件
rm -f "$temp_file"

# 获取当前配置名称
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
    config_count=$(jq '.configs | length' "$CONFIG_FILE")
    for ((i=0; i<config_count; i++)); do
        token=$(jq -r ".configs[$i].$TOKEN_FIELD" "$CONFIG_FILE")
        url=$(jq -r ".configs[$i].$URL_FIELD" "$CONFIG_FILE")
        if [[ "$token" == "$CURRENT_TOKEN" && "$url" == "$CURRENT_URL" ]]; then
            current_config_name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
            break
        fi
    done
fi

# 在列表末尾显示当前设置
if [[ -n "$current_config_name" ]]; then
    echo "当前设置：$current_config_name"
else
    echo "当前设置：未配置"
fi
echo "=========================================="

read -p "#? " choice

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
    exit 1
fi

if [ "$mode" = "1" ]; then
    # 临时设置
    export "$ENV_TOKEN_NAME=$TOKEN"
    export "$ENV_URL_NAME=$BASE_URL"
    echo "已切换到: $CONFIG_NAME (临时设置)"
    echo "仅在当前终端会话中有效"
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
else
    echo "[Error] 无效的设置方式选择"
    exit 1
fi
