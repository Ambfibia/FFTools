@echo off
setlocal
set "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1"
set "DOTNET_CLI_HOME=%~dp0work\.dotnet-home"
set "TOOL_PROJECT=%~dp0tools\FfPatchTool\FfPatchTool.csproj"
set "TOOL_DLL=%~dp0tools\FfPatchTool\bin\Release\net6.0\FfPatchTool.dll"
if not exist "%TOOL_DLL%" (
  dotnet build "%TOOL_PROJECT%" -c Release
  if errorlevel 1 exit /b %ERRORLEVEL%
)
dotnet "%TOOL_DLL%" %*
exit /b %ERRORLEVEL%
