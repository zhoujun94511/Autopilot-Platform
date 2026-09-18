@echo off
rem AutoPilot Platform 新设备一键安装：Platform Web + Runner 宿主依赖全部安装。
rem 本仓库 resources/ 已有二进制则跳过，不重复下载。

chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title AutoPilot Platform 依赖安装

cd /d "%~dp0"

echo ======================================================
echo       AutoPilot Platform 新设备一键安装
echo ======================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_deps.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 安装过程出现错误，请查看上方输出。
    pause
    exit /b %ERRORLEVEL%
)
