@echo off
rem Launch without Pinokio (Windows)
cd /d "%~dp0desktop"
set "PATH=%~dp0desktop\env;%~dp0desktop\env\Library\bin;%~dp0desktop\env\Scripts;%~dp0desktop\dependencies;%PATH%"
set KMP_DUPLICATE_LIB_OK=TRUE
"%~dp0desktop\env\python.exe" main.py
pause
