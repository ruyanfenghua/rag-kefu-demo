@echo off
chcp 65001 >nul
cd /d %~dp0
echo.
echo   本地代理已启动：http://127.0.0.1:8890/v1
echo   保持窗口运行，关闭窗口即停止。
echo.
python sensenova-proxy.py
pause
