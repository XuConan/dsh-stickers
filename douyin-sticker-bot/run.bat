@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"

if not exist ".venv\Scripts\python.exe" goto :make_venv
if not exist ".venv\Lib\site-packages\playwright" goto :make_pip
goto :run

:make_venv
echo [1/3] 创建虚拟环境 .venv ...
%PY% -m venv .venv
if exist ".venv\Scripts\python.exe" goto :make_pip
echo      普通创建失败，改用 --without-pip 方式重试 ...
%PY% -m venv --without-pip .venv
if not exist ".venv\Scripts\python.exe" goto :no_python

:make_pip
".venv\Scripts\python.exe" -m pip -V >nul 2>nul
if not errorlevel 1 goto :check_pw
echo [2/3] 准备 pip ...
".venv\Scripts\python.exe" -m ensurepip --upgrade
".venv\Scripts\python.exe" -m pip -V >nul 2>nul
if errorlevel 1 goto :fail

:check_pw
if exist ".venv\Lib\site-packages\playwright" goto :run
echo [3/3] 安装依赖，首次需要联网下载，请耐心等待 ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:run
echo 启动控制台，稍后会自动打开网页 ...
".venv\Scripts\python.exe" -m app %*
if errorlevel 1 pause
exit /b 0

:no_python
echo.
echo 没找到可用的 Python。请先安装 Python 3.10+ ，安装时勾选 "Add python.exe to PATH"。
pause
exit /b 1

:fail
echo.
echo 依赖安装失败。请手动执行下面三条命令（在本目录下）：
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m ensurepip --upgrade
echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
