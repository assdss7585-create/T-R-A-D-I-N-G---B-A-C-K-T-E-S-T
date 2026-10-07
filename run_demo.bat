@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  set "PYTHON_RUN=python"
) else (
  set "PYTHON_RUN=py -3"
)
%PYTHON_RUN% -m unittest discover -s tests -v
if errorlevel 1 goto failed
%PYTHON_RUN% -m mtf_backtest demo
if errorlevel 1 goto failed
start "" "outputs\long_win\report.html"
pause
exit /b 0
:failed
echo Execution failed. Python 3.11 or later is required. Read the error above.
pause
exit /b 1
