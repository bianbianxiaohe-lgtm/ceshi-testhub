@echo off
title Stop iOS Device Service
setlocal EnableDelayedExpansion

REM ============================================================
REM Stop the services started by ios_wda_host.bat.
REM
REM Only the two SERVICE ports are released:
REM     60105  USB tunnel
REM     8100   port forward
REM
REM Port 27015 is deliberately LEFT ALONE. It belongs to the go-iOS
REM agent, which is restarted lazily by the next "ios" command; killing
REM it breaks device enumeration and the next command then fails with
REM   "Device '...' not found. Is it attached to the machine?".
REM
REM Never kill by image name either. "taskkill /F /IM ios.exe /T" also
REM tears down go-iOS' USB bridge, the iPhone disappears from
REM "ios list" [{"deviceList":[]}] and the ONLY recovery is unplugging
REM and replugging the cable.
REM
REM ASCII-only, CRLF.
REM ============================================================

set "PORTS=60105 8100"

REM ---- remember the device BEFORE the tunnel dies ----
REM After the tunnel is gone "ios list" returns {"deviceList":[]}, so the UDID
REM has to be captured now. It is used to mark the device offline on TestHub.
set "UDID="
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_udid.ps1"`) do (
    if not defined UDID set "UDID=%%i"
)

echo Stopping iOS device service...
echo.

REM ---- pass 1: close the helper windows ----
REM Safe: these are the 3 windows this toolset itself opens.
taskkill /F /FI "WINDOWTITLE eq iOS-Tunnel*" /T >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq iOS-WDA*" /T >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq iOS-Forward*" /T >nul 2>nul
echo   [1/3] helper windows closed [iOS-Tunnel / iOS-WDA / iOS-Forward]

REM ---- pass 2: release the service ports by PID ----
REM PowerShell is used because parsing netstat output is locale dependent.
set "KILLED=0"
for %%P in (%PORTS%) do (
    for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -join ' '"`) do (
        if not "%%I"=="" (
            for %%K in (%%I) do (
                if not "%%K"=="0" (
                    taskkill /F /PID %%K >nul 2>nul
                    echo   [2/3] released PID %%K on port %%P
                    set "KILLED=1"
                )
            )
        )
    )
)
if "!KILLED!"=="0" echo   [2/3] no service process was running

REM ---- pass 3: verify ----
echo.
echo   [3/3] verifying...
set "LEFTOVER=0"
for %%P in (%PORTS%) do (
    set "BUSY="
    for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"`) do set "BUSY=%%I"
    if "!BUSY!"=="0" (
        echo         port %%P  released
    ) else (
        echo         port %%P  STILL BUSY [count=!BUSY!]
        set "LEFTOVER=1"
    )
)
for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 27015 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"`) do set "AGENT=%%I"
if "!AGENT!"=="0" (
    echo         port 27015  agent idle [started on demand]
) else (
    echo         port 27015  go-iOS agent running [normal - left alone]
)

REM ---- pass 4: tell TestHub this device went offline ----
REM The device row is NEVER removed - the list keeps every device that was
REM ever registered. This only flips its status so the list stops showing
REM a stale "online" tag.
set "TESTHUB_URL="
set "TESTHUB_TOKEN="
set "TESTHUB_CFG=%USERPROFILE%\.testhub\server.txt"
if exist "%TESTHUB_CFG%" (
    set /p TESTHUB_URL=<"%TESTHUB_CFG%"
)
if not defined TESTHUB_URL (
    echo.
    echo   [4/4] skipped: TestHub server address not configured yet
    echo         [it is saved automatically the first time you run ios_wda_host.bat]
) else if not defined UDID (
    echo.
    echo   [4/4] skipped: no iPhone was detected, nothing to mark offline
) else (
    echo.
    echo   [4/4] marking device offline on TestHub ...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_register_device.ps1" -ServerUrl "!TESTHUB_URL!" -Udid "!UDID!" -Status offline -Token "!TESTHUB_TOKEN!"
)

echo.
if "!LEFTOVER!"=="1" (
    echo [WARN] A service port is still held. Run this file once more.
    echo        If it persists, find the owner manually:
    echo          netstat -ano ^| findstr ":60105"
    echo          netstat -ano ^| findstr ":8100"
    echo        then:  taskkill /F /PID ^<pid^>
    echo        [Do NOT kill the process holding 27015.]
) else (
    echo [OK] Services stopped. You can start again with ios_wda_host.bat
)
echo.
echo Tip: run this BEFORE starting a different iPhone, so the old tunnel
echo      does not keep port 60105 busy.
echo.
pause
exit /b 0
