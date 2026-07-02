#!/bin/bash

# 检查 Python 是否已安装 / Check if Python is installed
if ! command -v python3 &>/dev/null; then
    echo "当前设备未安装Python, 请安装后重试。/ Python not installed, please install Python before retrying."
    echo "可参考./python-setup.md 安装Python。/ Please refer to./Python-setup.md to install Python."
    exit 1
else
    echo "Python 已安装，版本: $(python3 --version) / Python is already installed, version: $(python3 --version)"
fi

# 检查 pip 是否已安装 / Check if pip is installed
if ! command -v pip3 &>/dev/null; then
    echo "pip 未安装，开始安装 pip... / pip not installed, starting pip installation..."
    python3 -m ensurepip --upgrade
    if ! command -v pip3 &>/dev/null; then
        echo "pip 安装失败，请检查问题。/ pip installation failed, please check the issue."
        exit 1
    fi
else
    echo "pip 已安装，版本: $(pip3 --version) / pip is already installed, version: $(pip3 --version)"
fi

# 安装项目依赖 / Install project dependencies
if [ -f "pyproject.toml" ]; then
    echo "开始安装项目依赖... / Installing project dependencies..."
    uv sync
else
    echo "未找到 pyproject.toml 文件，跳过依赖安装。/ No pyproject.toml file found, skipping dependency installation."
fi

config_not_set=false
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ".env 文件已创建，请编辑 .env 文件并配置相关环境变量。/ .env file has been created, please edit the .env file and configure the related environment variables."
    config_not_set=true
fi

if [ ! -f "feishu_mapping.json" ]; then
    cp feishu_mapping.json.example feishu_mapping.json
    echo "feishu_mapping.json 文件已创建，请编辑 feishu_mapping.json 文件并配置相关环境变量。/ feishu_mapping.json file has been created, please edit the feishu_mapping.json file and configure the related environment variables."
    config_not_set=true
fi

if [ ! -f "codebase_configs.json" ]; then
    cp codebase_configs.example.json codebase_configs.json
    echo "codebase_configs.json 文件已创建，请编辑 codebase_configs.json 文件并配置相关环境变量。/ codebase_configs.json file has been created, please edit the codebase_configs.json file and configure the related environment variables."
    config_not_set=true
fi

if [ "$config_not_set" = true ]; then
    echo "请配置相关环境变量后重试。/ Please configure the related environment variables and try again."
    exit 1
fi

# 启动项目 / Start the project
echo "启动项目... / Starting the project..."

