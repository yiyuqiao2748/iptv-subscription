#!/bin/bash
# macOS 双击版启动器，和 启动电视订阅服务.bat 做同一件事。
# Gatekeeper 第一次会拦：右键 → 打开；或执行 chmod +x 后双击。

cd "$(dirname "$0")" || exit 1
echo
echo "  正在启动局域网订阅服务..."
echo "  关掉这个窗口，电视上就订阅不成了，请一直开着。"
echo "  提示：这一步不会改动电视或路由器的任何设置，随时可以关掉。"
echo "  加不上时看 docs/电视订阅接入.md"
echo

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "  找不到 $PY —— 还没建虚拟环境。先跑这两条命令："
  echo
  echo "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  echo
  read -r -p "  按回车退出" _
  exit 1
fi

"$PY" -X utf8 scripts/serve_lan.py --port 8787

echo
echo "  服务已停止。"
read -r -p "  按回车关闭窗口" _
