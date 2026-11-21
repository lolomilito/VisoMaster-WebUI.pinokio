@echo off
rem Launch without Pinokio (Windows)
cd /d "%~dp0webui"
set "PATH=%~dp0webui\env;%~dp0webui\env\Library\bin;%~dp0webui\env\Scripts;%~dp0webui\dependencies;%PATH%"
set KMP_DUPLICATE_LIB_OK=TRUE
"%~dp0webui\env\python.exe" main.py --host 0.0.0.0 --port 7860
pause
