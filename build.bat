@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包 工位伴侣 ...
echo 提示：改版本号要同时改三处 —— config.py 的 APP_VERSION、version_info.txt、根目录 VERSION
echo.

rem 先把在跑的实例关掉，否则 dist\DeskMate.exe 被占用，PyInstaller 会写不进去，
rem 而 dist 里留下的还是上一版 —— 打出来的「新包」其实是旧的。
taskkill /f /im "DeskMate.exe" >nul 2>&1
if not errorlevel 1 (
  echo 已关闭正在运行的 工位伴侣，等待文件释放...
  ping -n 3 127.0.0.1 >nul
)

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
if errorlevel 1 goto failed

rem 复核：dist 里的 exe 版本必须等于 config.APP_VERSION，否则说明这次没写成功
echo.
echo 正在核对版本号...
".venv\Scripts\python.exe" "check_build.py"
if errorlevel 1 goto failed

echo.
echo 完成：dist\DeskMate.exe
echo 别忘了把 dist\DeskMate.exe 传到 GitHub Release（附件名必须是 DeskMate.exe）
pause
exit /b 0

:failed
echo.
echo 打包失败：dist\DeskMate.exe 不是这次要发的版本，不要上传。
pause
exit /b 1
