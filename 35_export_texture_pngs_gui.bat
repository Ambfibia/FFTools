@echo off
setlocal
powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0tools\ff_texture_export_gui.ps1" -RepoRoot "%~dp0."
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%
