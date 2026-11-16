#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 python3，请先安装 Python 3.11 或 3.12。"
  read -r -p "按回车退出..."
  exit 1
fi
if [ ! -d ".venv" ]; then
  echo "创建虚拟环境..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "安装/检查依赖..."
python -m pip install --upgrade pip
pip install -r requirements.txt
echo "启动 GOLD INTELLIGENCE..."
python -m streamlit run app.py
