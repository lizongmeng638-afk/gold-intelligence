#!/bin/bash
set -e
cd "$(dirname "$0")"
trap 'code=$?; if [ "$code" -ne 0 ]; then echo "启动失败，错误见上方。"; read -r -p "按回车退出..."; fi' EXIT
if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 Python，请先安装 Python 3.11 或更新版本。"
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "首次启动：创建虚拟环境..."
  python3 -m venv .venv
fi
source .venv/bin/activate
if ! cmp -s requirements.txt .venv/.gold-requirements-installed; then
  echo "首次启动或依赖发生变化，安装所需组件..."
  python -m pip install --disable-pip-version-check -r requirements.txt
  cp requirements.txt .venv/.gold-requirements-installed
fi
GOLD_PORT="$(python - <<'PY'
import socket
for port in range(8501, 8511):
    with socket.socket() as s:
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit('8501–8510 端口均被占用，请先关闭旧窗口。')
PY
)"
echo "GOLD INTELLIGENCE V1.5：http://127.0.0.1:$GOLD_PORT"
echo "按 Control + C 停止。缓存保存在本文件夹 data/cache。"
python -m streamlit run app.py --server.address=127.0.0.1 --server.port="$GOLD_PORT"
