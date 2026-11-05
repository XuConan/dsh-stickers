@echo off
setlocal
chcp 936 >nul
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=desktop"
set "LOG=%TEMP%\sticker-setup.log"

echo.
echo ============================================================
echo   表情包插件 - 一键安装
echo   目录    : %HERE%
echo   profile : %PROFILE%
echo ============================================================
echo.

rem ---------------- 1/3 找 dsh 命令 ----------------
set "DSHCLI="
where dsh >nul 2>nul && set "DSHCLI=dsh"
if not defined DSHCLI if defined DSH_CLI if exist "%DSH_CLI%" set "DSHCLI=%DSH_CLI%"
if not defined DSHCLI if exist "%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI if exist "%ProgramFiles%\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=%ProgramFiles%\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI if exist "D:\Deepseeek Harness\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=D:\Deepseeek Harness\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI for /d %%D in ("%LOCALAPPDATA%\Programs\*") do if not defined DSHCLI if exist "%%D\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=%%D\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI for /d %%D in ("%ProgramFiles%\*") do if not defined DSHCLI if exist "%%D\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=%%D\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI for /d %%D in ("D:\*") do if not defined DSHCLI if exist "%%D\resources\runtime\cli\bin\dsh.cmd" set "DSHCLI=%%D\resources\runtime\cli\bin\dsh.cmd"
if not defined DSHCLI goto :nodsh
echo [1/3] dsh 命令: %DSHCLI%

rem ---------------- 2/3 Python 环境 ----------------
set "BACKEND=%HERE%\douyin-sticker-bot"
if not exist "%BACKEND%\run.bat" set "BACKEND=%HERE%\..\douyin-sticker-bot"
if not exist "%BACKEND%\run.bat" goto :nobackend
echo [2/3] 准备 Python 环境(首次约 1-2 分钟)...
call "%BACKEND%\run.bat" --help >"%LOG%" 2>&1
if errorlevel 1 goto :pythonfail
echo       完成

rem ---------------- 3/3 装插件 ----------------
echo [3/3] 安装插件到 profile "%PROFILE%" ...
set "PLUGIN=%HERE%\dsh-stickers"
if not exist "%PLUGIN%\package.json" set "PLUGIN=%HERE%"
call "%DSHCLI%" plugin --profile %PROFILE% add "%PLUGIN%"
if errorlevel 1 goto :installfail

echo.
echo ============================================================
echo   装好了
echo   1. 关掉 DSH 桌面应用再打开(profile 只在启动时生效)
echo   2. 左侧栏会出现「表情包」,点开就是面板
echo   3. 第一次用请点面板右上角「登录/检测」扫码(抖音、小红书各一次)
echo ============================================================
echo.
pause
exit /b 0

:nodsh
echo.
echo [X] 没找到 dsh 命令。
echo     1) 把 DSH 安装目录下的 resources\runtime\cli\bin 加进 PATH 后重跑
echo     2) 或者先 set DSH_CLI=完整的 dsh.cmd 路径 再重跑本脚本
echo.
pause
exit /b 1

:pythonfail
echo.
echo [X] Python 环境没装好,详细日志: %LOG%
echo     常见原因: 没装 Python,或者没联网装依赖。
echo.
pause
exit /b 1

:nobackend
echo.
echo [X] 找不到 Python 后端,应该在 %HERE%\douyin-sticker-bot
echo     请把整个 zip 完整解压(dsh-stickers / douyin-sticker-bot / install.bat 三个都要在)
echo.
pause
exit /b 1

:installfail
echo.
echo [X] 插件安装失败。上面是 pnpm 的输出。
echo     如果提示 tgz / file: 路径不存在,把整个目录挪回原位置重试。
echo.
pause
exit /b 1
