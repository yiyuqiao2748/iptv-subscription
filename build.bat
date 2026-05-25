@echo off
chcp 65001 >nul
title IPTV Desktop Build

echo ========================================
echo   IPTV Desktop - Windows Build Script
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ first.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/4] Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

:: Clean previous build
echo [2/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: Build with PyInstaller
echo [3/4] Building executable...
pyinstaller ^
    --name "IPTV订阅" ^
    --onefile ^
    --noconsole ^
    --add-data "config.py;." ^
    --add-data "scanner.py;." ^
    --add-data "dedup.py;." ^
    --add-data "tester.py;." ^
    --add-data "filter.py;." ^
    --add-data "generator.py;." ^
    --add-data "server.py;." ^
    --add-data "scheduler.py;." ^
    --add-data "desktop.py;." ^
    --hidden-import "apscheduler.schedulers.background" ^
    --hidden-import "apscheduler.triggers.interval" ^
    --hidden-import "apscheduler.triggers.cron" ^
    --hidden-import "waitress" ^
    --hidden-import "aiohttp" ^
    --hidden-import "pystray._win32" ^
    --collect-all "apscheduler" ^
    main.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

:: Create distribution package
echo [4/4] Creating distribution package...
set DIST_DIR=dist\IPTV订阅
mkdir "%DIST_DIR%" 2>nul
copy /y "dist\IPTV订阅.exe" "%DIST_DIR%\"
mkdir "%DIST_DIR%\output" 2>nul
mkdir "%DIST_DIR%\cache" 2>nul
mkdir "%DIST_DIR%\logs" 2>nul

:: Create 使用说明
(
echo IPTV 订阅服务 - 使用说明
echo ========================
echo.
echo 1. 双击 "IPTV订阅.exe" 启动服务
echo 2. 浏览器会自动打开管理面板
echo 3. 右下角托盘图标可控制：
echo    - 打开面板：重新打开浏览器
echo    - 立即更新：手动触发频道更新
echo    - 退出：停止服务
echo.
echo 频道列表每 6 小时自动更新一次。
echo 订阅地址：http://本机IP:8899/iptv.m3u
echo.
echo 如有问题请查看 logs/ 目录下的日志文件。
) > "%DIST_DIR%\使用说明.txt"

:: Create zip
cd dist
powershell -Command "Compress-Archive -Path 'IPTV订阅' -DestinationPath 'IPTV-Desktop-v1.0.zip' -Force"
cd ..

echo.
echo ========================================
echo   Build Complete!
echo   Output: dist\IPTV-Desktop-v1.0.zip
echo ========================================
pause
