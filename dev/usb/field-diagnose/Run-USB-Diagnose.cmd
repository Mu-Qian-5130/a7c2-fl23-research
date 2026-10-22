@echo off
setlocal
rem Read-only USB diagnostic for A7C II Tools. Put this file and
rem usb_field_diagnose.py next to A7C2Tools.exe, close A7C II Tools, then run.
set "HERE=%~dp0"
set "APP=%HERE%A7C2Tools.exe"
set "SMOKE=%HERE%_internal\dev\desktop\offline_smoke.py"
if not exist "%APP%" (
  echo A7C2Tools.exe was not found next to this file.
  echo Copy Run-USB-Diagnose.cmd and usb_field_diagnose.py into the folder that contains A7C2Tools.exe.
  pause
  exit /b 1
)
if not exist "%HERE%usb_field_diagnose.py" (
  echo usb_field_diagnose.py is missing next to this file.
  pause
  exit /b 1
)
tasklist /fi "imagename eq A7C2Tools.exe" | find /i "A7C2Tools.exe" >nul && (
  echo Please close A7C II Tools first, then run this file again.
  pause
  exit /b 1
)
rem Restore a self-test left behind by an interrupted earlier run.
if exist "%SMOKE%.orig" copy /y "%SMOKE%.orig" "%SMOKE%" >nul
copy /y "%SMOKE%" "%SMOKE%.orig" >nul || (echo Could not back up the app self-test file. & pause & exit /b 1)
copy /y "%HERE%usb_field_diagnose.py" "%SMOKE%" >nul

set "OUT=%HERE%usb-diagnose"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
set "A7C2_DIAG_LOG=%OUT%\usb-diagnose.log"
set "PYUSB_DEBUG=debug"
set "PYUSB_LOG_FILENAME=%OUT%\pyusb.log"
set "LIBUSB_DEBUG=3"

echo.
echo Read-only USB diagnostic. Nothing is written to the camera.
echo Camera: switched on, Mass Storage mode, connected by USB.
echo This takes about 2 minutes. Do not unplug the cable.
echo.
"%APP%" --offline-self-test "%OUT%\usb-diagnose-result.json" 2> "%OUT%\libusb.log"
set "CODE=%ERRORLEVEL%"

copy /y "%SMOKE%.orig" "%SMOKE%" >nul && del "%SMOKE%.orig"

powershell -NoProfile -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath '%HERE%a7c2-usb-diagnose.zip' -Force" >nul 2>&1
echo.
echo Finished (exit code %CODE%).
echo Send this file back: %HERE%a7c2-usb-diagnose.zip
echo Then fully power-cycle the camera: unplug USB, switch off, remove the battery for 1 minute.
echo.
pause
