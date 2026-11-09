@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包 工位伴侣 ...
echo 提示：改版本号要同时改 config.py 的 APP_VERSION 和 version_info.txt
echo.
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "DeskMate" ^
  --icon "app.ico" ^
  --version-file "version_info.txt" ^
  --add-data "assets;assets" ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtSql ^
  --exclude-module PySide6.QtTest ^
  --exclude-module PySide6.QtDBus ^
  --exclude-module PySide6.QtOpenGL ^
  --exclude-module PySide6.QtPrintSupport ^
  --exclude-module tkinter ^
  main.py
echo.
echo 完成：dist\DeskMate.exe
pause
