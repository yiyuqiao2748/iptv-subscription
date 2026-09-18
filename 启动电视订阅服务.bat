@echo off
chcp 65001 >nul
title APTV 局域网订阅服务
cd /d "%~dp0"

echo.
echo   正在启动局域网订阅服务...
echo   关掉这个窗口，电视上就订阅不成了，请一直开着。
echo   提示：这一步不会改动电视或路由器的任何设置，随时可以关掉。
echo   加不上时看 docs\电视订阅接入.md
echo.

".venv\Scripts\python.exe" -X utf8 scripts\serve_lan.py --port 8787

echo.
echo   服务已停止。
pause
