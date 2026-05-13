@echo off
setlocal
set "PY=C:\msys64\mingw32\bin\python.exe"
if not exist "%PY%" set "PY=python"
set "FULL_JSON=%~1"
if "%FULL_JSON%"=="" set "FULL_JSON=%~dp0builds\retro-010920-ru-patch\translation.json"
set "EDITOR_JSON=%~2"
if "%EDITOR_JSON%"=="" set "EDITOR_JSON=%~dp0builds\retro-010920-ru-patch\translation.translator.json"
"%PY%" "%~dp0tools\ff_translation_editor_json.py" import "%FULL_JSON%" "%EDITOR_JSON%"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%
