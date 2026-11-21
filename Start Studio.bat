@echo off
REM ============================================================
REM  HTML Video Studio - double-click to open the export app
REM  (No coding needed. First run installs everything automatically.)
REM  This launcher automatically finds a Python that can open the GUI.
REM ============================================================
cd /d "%~dp0"
setlocal
set LAUNCH=

pyw.exe -c "import tkinter" >nul 2>nul
if not errorlevel 1 set LAUNCH=pyw.exe
if defined LAUNCH goto launch

pythonw.exe -c "import tkinter" >nul 2>nul
if not errorlevel 1 set LAUNCH=pythonw.exe
if defined LAUNCH goto launch

py.exe -c "import tkinter" >nul 2>nul
if not errorlevel 1 set LAUNCH=py.exe
if defined LAUNCH goto launch

python.exe -c "import tkinter" >nul 2>nul
if not errorlevel 1 set LAUNCH=python.exe
if defined LAUNCH goto launch

echo ============================================================
echo  Python with GUI support was not found on this computer.
echo  Please install Python 3.10 or newer from https://www.python.org
echo  (tick "Add python.exe to PATH" during install - the default
echo  installer includes everything needed), then run this again.
echo ============================================================
pause
exit /b 1

:launch
start "" %LAUNCH% studio.pyw
endlocal
