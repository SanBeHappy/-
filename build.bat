@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包 工位伴侣（目录模式）...
echo 提示：改版本号要同时改三处 —— config.py 的 APP_VERSION、version_info.txt、根目录 VERSION
echo.

rem 先把在跑的实例关掉，否则 dist 里的文件被占用，PyInstaller 写不进去，
rem 打出来的「新包」其实是旧的。
taskkill /f /im "DeskMate.exe" >nul 2>&1
if not errorlevel 1 (
  echo 已关闭正在运行的 工位伴侣，等待文件释放...
  ping -n 3 127.0.0.1 >nul
)

rem --onedir：产出 dist\DeskMate\ 目录，运行时不再往 Temp 解压 _MEI 临时目录
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --noconsole ^
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

rem 复核 + 打 zip + 写 SHA256SUMS
echo.
echo 正在核对版本并打包 zip...
".venv\Scripts\python.exe" "check_build.py"
if errorlevel 1 goto failed

echo.
echo 完成：dist\DeskMate\DeskMate.exe （发布用 dist\DeskMate.zip）
echo 别忘了把 dist\DeskMate.zip 传到 GitHub Release（附件名必须是 DeskMate.zip）
pause
exit /b 0

:failed
echo.
echo 打包失败：dist 里的东西不是这次要发的版本，不要上传。
pause
exit /b 1
