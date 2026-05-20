@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo Gemini Image Auto Downloader
echo.

where python >nul 2>nul
if not errorlevel 1 goto RUN_PYTHON

where py >nul 2>nul
if not errorlevel 1 goto RUN_PY

echo Python을 찾을 수 없습니다. Python 3 설치와 PATH 설정을 확인해 주세요.
goto END

:RUN_PYTHON
python autodown.py %*
goto END

:RUN_PY
py -3 autodown.py %*
goto END

:END

echo.
echo 로그 파일: "%~dp0autodown.log"
pause
