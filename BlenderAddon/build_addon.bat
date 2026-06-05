@echo off
setlocal enabledelayedexpansion

REM Build a Blender-installable add-on zip from the BlenderAddon source folder.
REM Blender expects the zip to contain a single top-level folder whose name
REM matches the add-on package, with __init__.py inside it.

set "SCRIPT_DIR=%~dp0"
set "ADDON_NAME=Lj Environment Tools"
set "OUTPUT_ZIP=%SCRIPT_DIR%%ADDON_NAME%.zip"
set "STAGE_DIR=%TEMP%\ljaddon_%RANDOM%%RANDOM%"
set "PKG_DIR=%STAGE_DIR%\%ADDON_NAME%"

if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
mkdir "%PKG_DIR%"

REM Copy only top-level .py files. Skip .meta, __pycache__, and the prior zip.
set "FOUND_PY="
for %%F in ("%SCRIPT_DIR%*.py") do (
    copy /y "%%~fF" "%PKG_DIR%\" >nul
    set "FOUND_PY=1"
)

if not defined FOUND_PY (
    echo Error: no .py files found in %SCRIPT_DIR% 1>&2
    rmdir /s /q "%STAGE_DIR%"
    exit /b 1
)

if exist "%OUTPUT_ZIP%" del /q "%OUTPUT_ZIP%"

REM Use PowerShell's Compress-Archive to zip the staged folder so the archive's
REM top-level entry is "<ADDON_NAME>\...", which is what Blender requires.
powershell -NoProfile -Command "Compress-Archive -Path '%PKG_DIR%' -DestinationPath '%OUTPUT_ZIP%' -Force"
if errorlevel 1 (
    echo Error: Compress-Archive failed 1>&2
    rmdir /s /q "%STAGE_DIR%"
    exit /b 1
)

rmdir /s /q "%STAGE_DIR%"

echo Built: %OUTPUT_ZIP%
endlocal
