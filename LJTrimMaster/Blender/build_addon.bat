@echo off
setlocal

REM Build lj_trim_master into an installable Blender extension zip, written
REM next to this .bat.
REM
REM   build_addon.bat
REM   build_addon.bat -Blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
REM   build_addon.bat -Output C:\some\folder
REM
REM All the work is in build.ps1 (validates the manifest with Blender's own
REM packer, falls back to a plain zip). This just runs it without needing to
REM change the PowerShell execution policy.

set "SCRIPT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build.ps1" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo Build FAILED with exit code %CODE% 1>&2
)

REM Keep the window open when double-clicked from Explorer.
echo %CMDCMDLINE% | find /i "/c" >nul && pause

exit /b %CODE%
