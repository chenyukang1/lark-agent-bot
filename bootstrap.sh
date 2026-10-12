#!/bin/bash

# Check if Python is installed
if ! command -v python3 &>/dev/null; then
    echo "Python not installed, please install Python before retrying."
    exit 1
else
    echo "Python is already installed, version: $(python3 --version)"
fi

# Check if uv is installed
if ! command -v uv &>/dev/null; then
    echo "uv not installed, please install uv before retrying."
    exit 1
else
    echo "uv is already installed, version: $(uv --version)"
fi

# Install project dependencies
if [ -f "pyproject.toml" ]; then
    echo "Installing project dependencies..."
    uv sync
else
    echo "No pyproject.toml file found, skipping dependency installation."
fi

config_not_set=false
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ".env file has been created, please edit the .env file and configure the related environment variables."
    config_not_set=true
fi

if [ ! -f "user_mapping.json" ]; then
    cp user_mapping.example.json user_mapping.json
    echo "user_mapping.json file has been created, please edit the user_mapping.json file and configure the related environment variables."
    config_not_set=true
fi

if [ ! -f "codebase_configs.json" ]; then
    cp codebase_configs.example.json codebase_configs.json
    echo "codebase_configs.json file has been created, please edit the codebase_configs.json file and configure the related environment variables."
    config_not_set=true
fi

if [ "$config_not_set" = true ]; then
    echo "Please configure the related environment variables and try again."
    exit 1
fi

# 启动项目 / Start the project
echo "Starting the project..."

uv run main.py
