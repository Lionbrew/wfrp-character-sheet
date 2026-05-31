@echo off
title WFRP4e Character Sheet - Setup
color 0A
:: Run the PowerShell installer (handles Python install + app launch)
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_and_Run.ps1"
if errorlevel 1 pause
