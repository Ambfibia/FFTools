@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\export_texture_patch_beta20100104.ps1" %*
