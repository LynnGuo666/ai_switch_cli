#!/usr/bin/env python3
"""
配置文件编辑器 Web 界面
用于编辑 AI 配置管理工具的配置文件
"""

import os
import json
import toml
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
from werkzeug.serving import make_server
import threading

app = Flask(__name__)

# 获取脚本所在目录
BASE_DIR = Path(__file__).parent.absolute()

# 配置文件路径
CLAUDE_CONFIG = BASE_DIR / "claude_configs.json"
CODEX_CONFIG = BASE_DIR / "codex_configs.json"
HEALTH_CHECK_CONFIG = BASE_DIR / "health_check_configs.json"
CODEX_DIR = BASE_DIR / "codex"

# HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 配置编辑器</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .header h1 {
            color: #333;
            margin-bottom: 10px;
        }
        
        .header p {
            color: #666;
        }
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .tab {
            background: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        .tab:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }
        
        .tab.active {
            background: #667eea;
            color: white;
        }
        
        .tab-content {
            display: none;
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .tab-content.active {
            display: block;
        }
        
        .config-item {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            border: 2px solid transparent;
            transition: all 0.3s;
        }
        
        .config-item:hover {
            border-color: #667eea;
        }
        
        .config-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .config-item-title {
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .btn-primary {
            background: #667eea;
            color: white;
        }
        
        .btn-primary:hover {
            background: #5568d3;
        }
        
        .btn-danger {
            background: #ef4444;
            color: white;
        }
        
        .btn-danger:hover {
            background: #dc2626;
        }
        
        .btn-success {
            background: #10b981;
            color: white;
        }
        
        .btn-success:hover {
            background: #059669;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: 500;
            font-size: 14px;
        }
        
        .form-group input,
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
        }
        
        .form-group textarea {
            resize: vertical;
            min-height: 80px;
        }
        
        .form-group input:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        .add-btn {
            background: #10b981;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 500;
            margin-top: 20px;
            transition: all 0.3s;
        }
        
        .add-btn:hover {
            background: #059669;
            transform: translateY(-2px);
        }
        
        .alert {
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 20px;
        }
        
        .alert-success {
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #10b981;
        }
        
        .alert-error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #ef4444;
        }
        
        .codex-folder-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .codex-folder-item {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            border: 2px solid transparent;
        }
        
        .codex-folder-item:hover {
            border-color: #667eea;
            transform: translateY(-2px);
        }
        
        .codex-folder-item.active {
            background: #667eea;
            color: white;
        }
        
        .toml-editor {
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
        }
        
        .json-editor {
            font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 AI 配置编辑器</h1>
            <p>管理和编辑 AI 配置管理工具的所有配置文件</p>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('claude')">Claude 配置</button>
            <button class="tab" onclick="showTab('codex')">Codex 配置</button>
            <button class="tab" onclick="showTab('health')">健康检查</button>
            <button class="tab" onclick="showTab('codex-files')">Codex 文件</button>
        </div>
        
        <div id="claude" class="tab-content active">
            <div id="claude-alert"></div>
            <div id="claude-configs"></div>
            <button class="add-btn" onclick="addClaudeConfig()">+ 添加 Claude 配置</button>
        </div>
        
        <div id="codex" class="tab-content">
            <div id="codex-alert"></div>
            <div id="codex-configs"></div>
            <div style="display: flex; gap: 10px; margin-top: 20px;">
                <button class="add-btn" onclick="addCodexConfig()">+ 添加 Codex 配置</button>
                <button class="btn btn-danger" onclick="clearAllCodexConfigs()" style="padding: 12px 24px; font-size: 16px; font-weight: 500;">清除所有配置</button>
            </div>
        </div>
        
        <div id="health" class="tab-content">
            <div id="health-alert"></div>
            <div id="health-configs"></div>
        </div>
        
        <div id="codex-files" class="tab-content">
            <div id="codex-files-alert"></div>
            <div class="codex-folder-list" id="codex-folders"></div>
            <div id="codex-file-editor"></div>
        </div>
    </div>
    
    <script>
        function showTab(tabName) {
            // 隐藏所有标签页内容
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // 移除所有标签的 active 类
            document.querySelectorAll('.tab').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // 显示选中的标签页
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
            
            // 加载对应标签页的数据
            if (tabName === 'claude') {
                loadClaudeConfigs();
            } else if (tabName === 'codex') {
                loadCodexConfigs();
            } else if (tabName === 'health') {
                loadHealthConfigs();
            } else if (tabName === 'codex-files') {
                loadCodexFolders();
            }
        }
        
        function showAlert(containerId, message, type = 'success') {
            const container = document.getElementById(containerId);
            container.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
            setTimeout(() => {
                container.innerHTML = '';
            }, 3000);
        }
        
        // Claude 配置
        async function loadClaudeConfigs() {
            try {
                const response = await fetch('/api/claude');
                const data = await response.json();
                renderClaudeConfigs(data.configs || []);
            } catch (error) {
                showAlert('claude-alert', '加载配置失败: ' + error.message, 'error');
            }
        }
        
        function renderClaudeConfigs(configs) {
            const container = document.getElementById('claude-configs');
            if (configs.length === 0) {
                container.innerHTML = '<p>暂无配置</p>';
                return;
            }
            
            container.innerHTML = configs.map((config, index) => `
                <div class="config-item">
                    <div class="config-item-header">
                        <div class="config-item-title">${config.name || '未命名配置'}</div>
                        <div>
                            <button class="btn btn-primary" onclick="editClaudeConfig(${index})">编辑</button>
                            <button class="btn btn-danger" onclick="deleteClaudeConfig(${index})">删除</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Token:</label>
                        <input type="text" id="claude-token-${index}" value="${config.token || ''}" readonly>
                    </div>
                    <div class="form-group">
                        <label>URL:</label>
                        <input type="text" id="claude-url-${index}" value="${config.url || ''}" readonly>
                    </div>
                    <div class="form-group">
                        <label>Channel ID:</label>
                        <input type="text" id="claude-channel-${index}" value="${config.channel_id || ''}" readonly>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>输入价格:</label>
                            <input type="text" id="claude-input-${index}" value="${config.pricing?.input || ''}" readonly>
                        </div>
                        <div class="form-group">
                            <label>输出价格:</label>
                            <input type="text" id="claude-output-${index}" value="${config.pricing?.output || ''}" readonly>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>描述:</label>
                        <textarea id="claude-desc-${index}" readonly>${config.pricing?.description || ''}</textarea>
                    </div>
                    <div id="claude-edit-${index}" style="display: none;">
                        <button class="btn btn-success" onclick="saveClaudeConfig(${index})">保存</button>
                        <button class="btn" onclick="cancelEditClaude(${index})">取消</button>
                    </div>
                </div>
            `).join('');
        }
        
        function editClaudeConfig(index) {
            // 移除 readonly 属性
            document.getElementById(`claude-token-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-url-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-channel-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-input-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-output-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-desc-${index}`).removeAttribute('readonly');
            document.getElementById(`claude-edit-${index}`).style.display = 'block';
        }
        
        function cancelEditClaude(index) {
            loadClaudeConfigs();
        }
        
        async function saveClaudeConfig(index) {
            try {
                const config = {
                    name: document.getElementById(`claude-token-${index}`).value.split('-')[0] + '...',
                    token: document.getElementById(`claude-token-${index}`).value,
                    url: document.getElementById(`claude-url-${index}`).value,
                    channel_id: document.getElementById(`claude-channel-${index}`).value || null,
                    pricing: {
                        input: document.getElementById(`claude-input-${index}`).value,
                        output: document.getElementById(`claude-output-${index}`).value,
                        description: document.getElementById(`claude-desc-${index}`).value
                    }
                };
                
                const response = await fetch('/api/claude', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({index, config})
                });
                
                if (response.ok) {
                    showAlert('claude-alert', '配置已保存', 'success');
                    loadClaudeConfigs();
                } else {
                    throw new Error('保存失败');
                }
            } catch (error) {
                showAlert('claude-alert', '保存失败: ' + error.message, 'error');
            }
        }
        
        async function deleteClaudeConfig(index) {
            if (!confirm('确定要删除这个配置吗？')) return;
            
            try {
                const response = await fetch('/api/claude', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({index})
                });
                
                if (response.ok) {
                    showAlert('claude-alert', '配置已删除', 'success');
                    loadClaudeConfigs();
                } else {
                    throw new Error('删除失败');
                }
            } catch (error) {
                showAlert('claude-alert', '删除失败: ' + error.message, 'error');
            }
        }
        
        function addClaudeConfig() {
            const container = document.getElementById('claude-configs');
            const newConfig = {
                name: '新配置',
                token: '',
                url: '',
                channel_id: null,
                pricing: {input: '', output: '', description: ''}
            };
            container.innerHTML = `
                <div class="config-item">
                    <div class="form-group">
                        <label>配置名称:</label>
                        <input type="text" id="new-claude-name" placeholder="输入配置名称">
                    </div>
                    <div class="form-group">
                        <label>Token:</label>
                        <input type="text" id="new-claude-token" placeholder="输入 Token">
                    </div>
                    <div class="form-group">
                        <label>URL:</label>
                        <input type="text" id="new-claude-url" placeholder="输入 URL">
                    </div>
                    <div class="form-group">
                        <label>Channel ID:</label>
                        <input type="text" id="new-claude-channel" placeholder="输入 Channel ID (可选)">
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>输入价格:</label>
                            <input type="text" id="new-claude-input" placeholder="例如: ¥1.5/1M tokens">
                        </div>
                        <div class="form-group">
                            <label>输出价格:</label>
                            <input type="text" id="new-claude-output" placeholder="例如: ¥1.5/1M tokens">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>描述:</label>
                        <textarea id="new-claude-desc" placeholder="输入描述 (可选)"></textarea>
                    </div>
                    <div>
                        <button class="btn btn-success" onclick="saveNewClaudeConfig()">保存</button>
                        <button class="btn" onclick="loadClaudeConfigs()">取消</button>
                    </div>
                </div>
            ` + container.innerHTML;
        }
        
        async function saveNewClaudeConfig() {
            try {
                const config = {
                    name: document.getElementById('new-claude-name').value,
                    token: document.getElementById('new-claude-token').value,
                    url: document.getElementById('new-claude-url').value,
                    channel_id: document.getElementById('new-claude-channel').value || null,
                    pricing: {
                        input: document.getElementById('new-claude-input').value,
                        output: document.getElementById('new-claude-output').value,
                        description: document.getElementById('new-claude-desc').value
                    }
                };
                
                const response = await fetch('/api/claude', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(config)
                });
                
                if (response.ok) {
                    showAlert('claude-alert', '配置已添加', 'success');
                    loadClaudeConfigs();
                } else {
                    throw new Error('添加失败');
                }
            } catch (error) {
                showAlert('claude-alert', '添加失败: ' + error.message, 'error');
            }
        }
        
        // Codex 配置 (类似 Claude)
        async function loadCodexConfigs() {
            try {
                const response = await fetch('/api/codex');
                const data = await response.json();
                renderCodexConfigs(data.configs || []);
            } catch (error) {
                showAlert('codex-alert', '加载配置失败: ' + error.message, 'error');
            }
        }
        
        function renderCodexConfigs(configs) {
            const container = document.getElementById('codex-configs');
            if (configs.length === 0) {
                container.innerHTML = '<p>暂无配置</p>';
                return;
            }
            
            container.innerHTML = configs.map((config, index) => `
                <div class="config-item">
                    <div class="config-item-header">
                        <div class="config-item-title">${config.name || '未命名配置'}</div>
                        <div>
                            <button class="btn btn-primary" onclick="editCodexConfig(${index})">编辑</button>
                            <button class="btn btn-danger" onclick="deleteCodexConfig(${index})">删除</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>API Key:</label>
                        <input type="text" id="codex-key-${index}" value="${config.api_key || ''}" readonly>
                    </div>
                    <div class="form-group">
                        <label>Base URL:</label>
                        <input type="text" id="codex-url-${index}" value="${config.base_url || ''}" readonly>
                    </div>
                    <div class="form-group">
                        <label>Channel ID:</label>
                        <input type="text" id="codex-channel-${index}" value="${config.channel_id || ''}" readonly>
                    </div>
                    <div class="form-group">
                        <label>Codex Folder:</label>
                        <input type="text" id="codex-folder-${index}" value="${config.codex_folder || ''}" placeholder="例如: anyrouter" readonly>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>输入价格:</label>
                            <input type="text" id="codex-input-${index}" value="${config.pricing?.input || ''}" readonly>
                        </div>
                        <div class="form-group">
                            <label>输出价格:</label>
                            <input type="text" id="codex-output-${index}" value="${config.pricing?.output || ''}" readonly>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>描述:</label>
                        <textarea id="codex-desc-${index}" readonly>${config.pricing?.description || ''}</textarea>
                    </div>
                    <div id="codex-edit-${index}" style="display: none;">
                        <button class="btn btn-success" onclick="saveCodexConfig(${index})">保存</button>
                        <button class="btn" onclick="cancelEditCodex(${index})">取消</button>
                    </div>
                </div>
            `).join('');
        }
        
        function editCodexConfig(index) {
            document.getElementById(`codex-key-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-url-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-channel-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-folder-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-input-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-output-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-desc-${index}`).removeAttribute('readonly');
            document.getElementById(`codex-edit-${index}`).style.display = 'block';
        }
        
        function cancelEditCodex(index) {
            loadCodexConfigs();
        }
        
        async function saveCodexConfig(index) {
            try {
                const config = {
                    name: document.getElementById(`codex-key-${index}`).value.split('-')[0] + '...',
                    api_key: document.getElementById(`codex-key-${index}`).value,
                    base_url: document.getElementById(`codex-url-${index}`).value,
                    channel_id: document.getElementById(`codex-channel-${index}`).value || null,
                    codex_folder: document.getElementById(`codex-folder-${index}`).value || null,
                    pricing: {
                        input: document.getElementById(`codex-input-${index}`).value,
                        output: document.getElementById(`codex-output-${index}`).value,
                        description: document.getElementById(`codex-desc-${index}`).value
                    }
                };
                
                const response = await fetch('/api/codex', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({index, config})
                });
                
                if (response.ok) {
                    showAlert('codex-alert', '配置已保存', 'success');
                    loadCodexConfigs();
                } else {
                    throw new Error('保存失败');
                }
            } catch (error) {
                showAlert('codex-alert', '保存失败: ' + error.message, 'error');
            }
        }
        
        async function deleteCodexConfig(index) {
            if (!confirm('确定要删除这个配置吗？')) return;
            
            try {
                const response = await fetch('/api/codex', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({index})
                });
                
                if (response.ok) {
                    showAlert('codex-alert', '配置已删除', 'success');
                    loadCodexConfigs();
                } else {
                    throw new Error('删除失败');
                }
            } catch (error) {
                showAlert('codex-alert', '删除失败: ' + error.message, 'error');
            }
        }
        
        function addCodexConfig() {
            const container = document.getElementById('codex-configs');
            container.innerHTML = `
                <div class="config-item">
                    <div class="form-group">
                        <label>配置名称:</label>
                        <input type="text" id="new-codex-name" placeholder="输入配置名称">
                    </div>
                    <div class="form-group">
                        <label>API Key:</label>
                        <input type="text" id="new-codex-key" placeholder="输入 API Key">
                    </div>
                    <div class="form-group">
                        <label>Base URL:</label>
                        <input type="text" id="new-codex-url" placeholder="输入 Base URL">
                    </div>
                    <div class="form-group">
                        <label>Channel ID:</label>
                        <input type="text" id="new-codex-channel" placeholder="输入 Channel ID (可选)">
                    </div>
                    <div class="form-group">
                        <label>Codex Folder:</label>
                        <input type="text" id="new-codex-folder" placeholder="例如: anyrouter (可选)">
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>输入价格:</label>
                            <input type="text" id="new-codex-input" placeholder="例如: ¥1.5/1M tokens">
                        </div>
                        <div class="form-group">
                            <label>输出价格:</label>
                            <input type="text" id="new-codex-output" placeholder="例如: ¥1.5/1M tokens">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>描述:</label>
                        <textarea id="new-codex-desc" placeholder="输入描述 (可选)"></textarea>
                    </div>
                    <div>
                        <button class="btn btn-success" onclick="saveNewCodexConfig()">保存</button>
                        <button class="btn" onclick="loadCodexConfigs()">取消</button>
                    </div>
                </div>
            ` + container.innerHTML;
        }
        
        async function saveNewCodexConfig() {
            try {
                const config = {
                    name: document.getElementById('new-codex-name').value,
                    api_key: document.getElementById('new-codex-key').value,
                    base_url: document.getElementById('new-codex-url').value,
                    channel_id: document.getElementById('new-codex-channel').value || null,
                    codex_folder: document.getElementById('new-codex-folder').value || null,
                    pricing: {
                        input: document.getElementById('new-codex-input').value,
                        output: document.getElementById('new-codex-output').value,
                        description: document.getElementById('new-codex-desc').value
                    }
                };
                
                const response = await fetch('/api/codex', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(config)
                });
                
                if (response.ok) {
                    showAlert('codex-alert', '配置已添加', 'success');
                    loadCodexConfigs();
                } else {
                    throw new Error('添加失败');
                }
            } catch (error) {
                showAlert('codex-alert', '添加失败: ' + error.message, 'error');
            }
        }
        
        async function clearAllCodexConfigs() {
            if (!confirm('确定要清除所有 Codex 配置吗？此操作不可恢复！')) return;
            
            try {
                const response = await fetch('/api/codex/clear', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'}
                });
                
                if (response.ok) {
                    showAlert('codex-alert', '所有配置已清除', 'success');
                    loadCodexConfigs();
                } else {
                    throw new Error('清除失败');
                }
            } catch (error) {
                showAlert('codex-alert', '清除失败: ' + error.message, 'error');
            }
        }
        
        // 健康检查配置
        async function loadHealthConfigs() {
            try {
                const response = await fetch('/api/health');
                const data = await response.json();
                renderHealthConfigs(data.urls || []);
            } catch (error) {
                showAlert('health-alert', '加载配置失败: ' + error.message, 'error');
            }
        }
        
        function renderHealthConfigs(urls) {
            const container = document.getElementById('health-configs');
            container.innerHTML = `
                <div class="config-item">
                    <h3 style="margin-bottom: 15px;">健康检查 URL 列表</h3>
                    ${urls.map((url, index) => `
                        <div class="form-group" style="display: flex; gap: 10px; align-items: center;">
                            <input type="text" id="health-url-${index}" value="${url}" style="flex: 1;">
                            <button class="btn btn-danger" onclick="removeHealthUrl(${index})">删除</button>
                        </div>
                    `).join('')}
                    <div class="form-group" style="display: flex; gap: 10px; align-items: center;">
                        <input type="text" id="new-health-url" placeholder="输入新的健康检查 URL" style="flex: 1;">
                        <button class="btn btn-success" onclick="addHealthUrl()">添加</button>
                    </div>
                    <div style="margin-top: 20px;">
                        <button class="btn btn-primary" onclick="saveHealthConfigs()">保存所有更改</button>
                    </div>
                </div>
            `;
        }
        
        async function addHealthUrl() {
            const url = document.getElementById('new-health-url').value.trim();
            if (!url) return;
            
            const urls = Array.from(document.querySelectorAll('[id^="health-url-"]')).map(input => input.value);
            urls.push(url);
            
            try {
                const response = await fetch('/api/health', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({urls})
                });
                
                if (response.ok) {
                    showAlert('health-alert', 'URL 已添加', 'success');
                    loadHealthConfigs();
                } else {
                    throw new Error('添加失败');
                }
            } catch (error) {
                showAlert('health-alert', '添加失败: ' + error.message, 'error');
            }
        }
        
        async function removeHealthUrl(index) {
            const urls = Array.from(document.querySelectorAll('[id^="health-url-"]')).map(input => input.value);
            urls.splice(index, 1);
            
            try {
                const response = await fetch('/api/health', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({urls})
                });
                
                if (response.ok) {
                    showAlert('health-alert', 'URL 已删除', 'success');
                    loadHealthConfigs();
                } else {
                    throw new Error('删除失败');
                }
            } catch (error) {
                showAlert('health-alert', '删除失败: ' + error.message, 'error');
            }
        }
        
        async function saveHealthConfigs() {
            const urls = Array.from(document.querySelectorAll('[id^="health-url-"]')).map(input => input.value.trim()).filter(url => url);
            
            try {
                const response = await fetch('/api/health', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({urls})
                });
                
                if (response.ok) {
                    showAlert('health-alert', '配置已保存', 'success');
                    loadHealthConfigs();
                } else {
                    throw new Error('保存失败');
                }
            } catch (error) {
                showAlert('health-alert', '保存失败: ' + error.message, 'error');
            }
        }
        
        // Codex 文件编辑
        async function loadCodexFolders() {
            try {
                const response = await fetch('/api/codex-folders');
                const data = await response.json();
                renderCodexFolders(data.folders || []);
            } catch (error) {
                showAlert('codex-files-alert', '加载文件夹列表失败: ' + error.message, 'error');
            }
        }
        
        function renderCodexFolders(folders) {
            const container = document.getElementById('codex-folders');
            container.innerHTML = folders.map(folder => `
                <div class="codex-folder-item" onclick="loadCodexFolder('${folder}')">
                    ${folder}
                </div>
            `).join('');
        }
        
        async function loadCodexFolder(folderName) {
            try {
                const response = await fetch(`/api/codex-files/${folderName}`);
                const data = await response.json();
                renderCodexFileEditor(folderName, data);
            } catch (error) {
                showAlert('codex-files-alert', '加载文件失败: ' + error.message, 'error');
            }
        }
        
        function renderCodexFileEditor(folderName, data) {
            const container = document.getElementById('codex-file-editor');
            container.innerHTML = `
                <div class="config-item">
                    <h3 style="margin-bottom: 20px;">编辑 ${folderName} 配置</h3>
                    <div class="form-group">
                        <label>config.toml:</label>
                        <textarea id="codex-toml" class="toml-editor" style="min-height: 200px;">${data.config_toml || ''}</textarea>
                    </div>
                    <div class="form-group">
                        <label>auth.json:</label>
                        <textarea id="codex-auth" class="json-editor" style="min-height: 150px;">${data.auth_json || ''}</textarea>
                    </div>
                    <div>
                        <button class="btn btn-success" onclick="saveCodexFiles('${folderName}')">保存</button>
                    </div>
                </div>
            `;
            
            // 高亮选中的文件夹
            document.querySelectorAll('.codex-folder-item').forEach(item => {
                item.classList.remove('active');
                if (item.textContent.trim() === folderName) {
                    item.classList.add('active');
                }
            });
        }
        
        async function saveCodexFiles(folderName) {
            try {
                const config_toml = document.getElementById('codex-toml').value;
                const auth_json = document.getElementById('codex-auth').value;
                
                const response = await fetch(`/api/codex-files/${folderName}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({config_toml, auth_json})
                });
                
                if (response.ok) {
                    showAlert('codex-files-alert', '文件已保存', 'success');
                } else {
                    throw new Error('保存失败');
                }
            } catch (error) {
                showAlert('codex-files-alert', '保存失败: ' + error.message, 'error');
            }
        }
        
        // 页面加载时初始化
        window.onload = function() {
            loadClaudeConfigs();
        };
    </script>
</body>
</html>
"""

# API 路由
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# Claude 配置 API
@app.route('/api/claude', methods=['GET'])
def get_claude_configs():
    try:
        if CLAUDE_CONFIG.exists():
            with open(CLAUDE_CONFIG, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({"configs": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/claude', methods=['POST'])
def add_claude_config():
    try:
        config = request.json
        if CLAUDE_CONFIG.exists():
            with open(CLAUDE_CONFIG, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"configs": []}
        
        data["configs"].append(config)
        
        with open(CLAUDE_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/claude', methods=['PUT'])
def update_claude_config():
    try:
        index = request.json.get('index')
        config = request.json.get('config')
        
        with open(CLAUDE_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data["configs"][index] = config
        
        with open(CLAUDE_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/claude', methods=['DELETE'])
def delete_claude_config():
    try:
        index = request.json.get('index')
        
        with open(CLAUDE_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data["configs"].pop(index)
        
        with open(CLAUDE_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Codex 配置 API (类似 Claude)
@app.route('/api/codex', methods=['GET'])
def get_codex_configs():
    try:
        if CODEX_CONFIG.exists():
            with open(CODEX_CONFIG, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({"configs": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex', methods=['POST'])
def add_codex_config():
    try:
        config = request.json
        if CODEX_CONFIG.exists():
            with open(CODEX_CONFIG, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"configs": []}
        
        data["configs"].append(config)
        
        with open(CODEX_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex', methods=['PUT'])
def update_codex_config():
    try:
        index = request.json.get('index')
        config = request.json.get('config')
        
        with open(CODEX_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data["configs"][index] = config
        
        with open(CODEX_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex', methods=['DELETE'])
def delete_codex_config():
    try:
        index = request.json.get('index')
        
        with open(CODEX_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data["configs"].pop(index)
        
        with open(CODEX_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex/clear', methods=['DELETE'])
def clear_all_codex_configs():
    try:
        data = {"configs": []}
        
        with open(CODEX_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 健康检查配置 API
@app.route('/api/health', methods=['GET'])
def get_health_configs():
    try:
        if HEALTH_CHECK_CONFIG.exists():
            with open(HEALTH_CHECK_CONFIG, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify({"health_check_urls": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['PUT'])
def update_health_configs():
    try:
        urls = request.json.get('urls', [])
        data = {"health_check_urls": urls}
        
        with open(HEALTH_CHECK_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Codex 文件 API
@app.route('/api/codex-folders', methods=['GET'])
def get_codex_folders():
    try:
        folders = []
        if CODEX_DIR.exists():
            for item in CODEX_DIR.iterdir():
                if item.is_dir():
                    folders.append(item.name)
        return jsonify({"folders": sorted(folders)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex-files/<folder_name>', methods=['GET'])
def get_codex_files(folder_name):
    try:
        folder_path = CODEX_DIR / folder_name
        config_toml_path = folder_path / "config.toml"
        auth_json_path = folder_path / "auth.json"
        
        config_toml = ""
        auth_json = ""
        
        if config_toml_path.exists():
            with open(config_toml_path, 'r', encoding='utf-8') as f:
                config_toml = f.read()
        
        if auth_json_path.exists():
            with open(auth_json_path, 'r', encoding='utf-8') as f:
                auth_json = f.read()
        
        return jsonify({
            "config_toml": config_toml,
            "auth_json": auth_json
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/codex-files/<folder_name>', methods=['PUT'])
def update_codex_files(folder_name):
    try:
        folder_path = CODEX_DIR / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        
        config_toml = request.json.get('config_toml', '')
        auth_json = request.json.get('auth_json', '')
        
        # 保存 config.toml
        config_toml_path = folder_path / "config.toml"
        with open(config_toml_path, 'w', encoding='utf-8') as f:
            f.write(config_toml)
        
        # 保存 auth.json (验证 JSON 格式)
        auth_json_path = folder_path / "auth.json"
        try:
            json.loads(auth_json)  # 验证 JSON
            with open(auth_json_path, 'w', encoding='utf-8') as f:
                f.write(auth_json)
        except json.JSONDecodeError:
            return jsonify({"error": "auth.json 格式错误"}), 400
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_server(host='127.0.0.1', port=5000):
    """在后台线程中运行服务器"""
    server = make_server(host, port, app)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    return server, server_thread

if __name__ == '__main__':
    import sys
    
    port = 5000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("端口号必须是数字")
            sys.exit(1)
    
    print(f"🚀 配置文件编辑器已启动")
    print(f"📝 访问地址: http://127.0.0.1:{port}")
    print(f"按 Ctrl+C 停止服务器")
    
    try:
        app.run(host='127.0.0.1', port=port, debug=False)
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")

