@echo off
setlocal
chcp 936 >nul
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

rem 顶层转发器：真正的逻辑在 dsh-stickers\install.bat（由 make_install_bat.py 生成）
rem 有了它，GitHub 的 "Source code (zip)" 解压后也能直接双击本文件安装。

if not exist "%HERE%\dsh-stickers\install.bat" goto :missing
call "%HERE%\dsh-stickers\install.bat" %*
exit /b %errorlevel%

:missing
echo [错误] 找不到 dsh-stickers\install.bat
echo        请确认 zip 完整解压，且没有只解压了其中一部分。
pause
exit /b 1
