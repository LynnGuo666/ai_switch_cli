#!/bin/bash

# 清除屏幕内容
clear

# 配置文件路径
CONFIG_FILE="$(dirname "$0")/claude_configs.json"

# 检查配置文件是否存在
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "[Error] 配置文件不存在: $CONFIG_FILE"
    echo "请创建配置文件，JSON格式"
    exit 1
fi

# 检查是否通过source运行
echo "=========================================="
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Claude 配置切换工具"
    echo "永久设置模式"
    FORCE_PERMANENT=true
    TEMP_SETTING_AVAILABLE=false
else
    echo "Claude 配置切换工具"
    echo ""
    TEMP_SETTING_AVAILABLE=true
fi
echo "作者：Lynn v1.4.0"
echo "=========================================="

# 检查jq是否可用
if ! command -v jq &> /dev/null; then
    echo "[Error] 需要安装jq来解析JSON文件"
    echo "macOS: brew install jq"
    echo "Ubuntu: sudo apt install jq"
    exit 1
fi

# 读取配置文件并显示选项
echo ""

# 获取配置数量
config_count=$(jq '.configs | length' "$CONFIG_FILE")

# 创建临时文件来存储排序后的配置
temp_file=$(mktemp)

# 将配置信息写入临时文件，包含索引信息
for ((i=0; i<config_count; i++)); do
    name=$(jq -r ".configs[$i].name" "$CONFIG_FILE")
    input_price=$(jq -r ".configs[$i].pricing.input" "$CONFIG_FILE")
    output_price=$(jq -r ".configs[$i].pricing.output" "$CONFIG_FILE")
    description=$(jq -r ".configs[$i].pricing.description" "$CONFIG_FILE")
    
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
    
    echo "$i|$name|$input_price|$output_price|$description|$total_price" >> "$temp_file"
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
while IFS='|' read -r index name input_price output_price description total_price; do
    echo "$line_num) $name"
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
if [[ -n "$ANTHROPIC_AUTH_TOKEN" && -n "$ANTHROPIC_BASE_URL" ]]; then
    config_count=$(jq '.configs | length' "$CONFIG_FILE")
    for ((i=0; i<config_count; i++)); do
        token=$(jq -r ".configs[$i].token" "$CONFIG_FILE")
        url=$(jq -r ".configs[$i].url" "$CONFIG_FILE")
        if [[ "$token" == "$ANTHROPIC_AUTH_TOKEN" && "$url" == "$ANTHROPIC_BASE_URL" ]]; then
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
    TOKEN=$(jq -r ".configs[$index].token" "$CONFIG_FILE")
    BASE_URL=$(jq -r ".configs[$index].url" "$CONFIG_FILE")
else
    echo "[Error] 无效选择"
    exit 1
fi

if [ "$mode" = "1" ]; then
    # 临时设置
    export ANTHROPIC_AUTH_TOKEN="$TOKEN"
    export ANTHROPIC_BASE_URL="$BASE_URL"
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
    grep -v "ANTHROPIC_AUTH_TOKEN=" "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" 2>/dev/null || touch "$SHELL_CONFIG_FILE.tmp"
    grep -v "ANTHROPIC_BASE_URL=" "$SHELL_CONFIG_FILE.tmp" > "$SHELL_CONFIG_FILE.tmp2"
    mv "$SHELL_CONFIG_FILE.tmp2" "$SHELL_CONFIG_FILE"
    rm -f "$SHELL_CONFIG_FILE.tmp"
    
    # 添加新配置
    echo "export ANTHROPIC_AUTH_TOKEN=\"$TOKEN\"" >> "$SHELL_CONFIG_FILE"
    echo "export ANTHROPIC_BASE_URL=\"$BASE_URL\"" >> "$SHELL_CONFIG_FILE"

    # 3. 最后，一次性打印所有输出
    echo "$output_message"
else
    echo "[Error] 无效的设置方式选择"
    exit 1
fi
