@echo off
title iOS Device Service (TestHub Midscene)
setlocal EnableDelayedExpansion

REM ============================================================
REM TestHub iOS one-click launcher (double-click, no autostart)
REM v4: auto-detect UDID (supports switching devices)
REM      - set UDID below to a value to force a fixed device
REM      - leave it empty to auto-detect the connected iPhone
REM Stops with: ios_device_stop.bat
REM Files needed in the same folder: ios_detect_udid.ps1
REM ============================================================

set "UDID="
set "WDA_PORT=8100"
REM Leave WDA_BUNDLE empty to let go-iOS auto-detect the installed WDA.
REM If auto-detect fails, run:  ios apps --udid=<UDID>
REM then put the WebDriverAgent bundle id here, e.g.
REM   set "WDA_BUNDLE=com.facebook.WebDriverAgentRunner.xctrunner"
set "WDA_BUNDLE="
set "XCTEST_CONFIG=WebDriverAgentRunner.xctest"
set "IOS_EXE="
REM Tunnel mode (no admin rights needed):
REM   ENABLE_GO_IOS_AGENT=user  enables the userspace tunnel (go-iOS v1.3.2 way)
REM   TUNNEL_EXTRA              extra flags, e.g. --userspace for older builds
REM If userspace keeps failing, clear both and run this file as Administrator.
set "ENABLE_GO_IOS_AGENT=user"
set "TUNNEL_EXTRA="

echo ============================================
echo  TestHub iOS Device Service v4
echo  Port : %WDA_PORT%
echo ============================================
echo.

REM ---- 1) find ios.exe ----
if defined IOS_EXE goto :has_ios
where ios >nul 2>nul
if %errorlevel% equ 0 (
    set "IOS_EXE=ios"
    goto :has_ios
)
for %%P in (
    "%~dp0ios.exe"
    "%LOCALAPPDATA%\Programs\go-ios\ios.exe"
    "%LOCALAPPDATA%\Microsoft\WinGet\Links\ios.exe"
    "C:\tools\go-ios\ios.exe"
    "C:\go-ios\ios.exe"
    "D:\tools\go-ios\ios.exe"
    "D:\go-ios\ios.exe"
) do (
    if exist %%~P (
        set "IOS_EXE=%%~P"
        goto :has_ios
    )
)
echo [ERROR] ios.exe not found (go-iOS).
echo Check with:  where ios
echo Or edit this file:  set "IOS_EXE=D:\your\path\ios.exe"
echo.
pause
exit /b 1

:has_ios
echo [0/4] Using ios binary: %IOS_EXE%

REM ---- 2) auto detect UDID ----
if defined UDID goto :udid_done
echo [1/4] Detecting connected iOS device...
set "UDID_LIST="
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_udid.ps1"') do set "UDID_LIST=%%i"

set "UDID_COUNT=0"
for %%u in (%UDID_LIST%) do set /a UDID_COUNT+=1

if "%UDID_COUNT%"=="0" (
    echo        No device detected.
    echo        Check: phone unlocked, cable OK, "Trust this computer" tapped.
    echo        You can also set UDID manually at the top of this file.
    echo.
    pause
    exit /b 1
)

if %UDID_COUNT% GEQ 2 (
    echo        Multiple devices found:
    for %%u in (%UDID_LIST%) do echo          %%u
    set /p "UDID=Type the UDID to use (or press Enter for the first one): "
    if not defined UDID (
        for /f "tokens=1" %%u in ("%UDID_LIST%") do set "UDID=%%u"
    )
) else (
    for %%u in (%UDID_LIST%) do set "UDID=%%u"
)

:udid_done
echo        UDID = %UDID%
echo.

REM ---- 3) already running? ----
call :probe
if "%WDA_OK%"=="1" (
    echo [OK] WDA already running: http://127.0.0.1:%WDA_PORT%/status
    goto :show_ip
)

REM ---- 4) start services ----
echo [2/4] Starting USB tunnel ...
start "iOS-Tunnel" cmd /k "%IOS_EXE% tunnel start --udid=%UDID% %TUNNEL_EXTRA%"
echo        waiting 20s for the tunnel to come up (iOS 17+ needs it)...
timeout /t 20 /nobreak >nul

REM ---- 3.5) auto detect WDA bundle id ----
if not defined WDA_BUNDLE (
    echo [3/4] Detecting installed WebDriverAgent...
    set "WDA_LIST="
    for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_wda.ps1" -udid "%UDID%"') do set "WDA_LIST=%%i"
    set "WDA_COUNT=0"
    for %%w in (!WDA_LIST!) do set /a WDA_COUNT+=1
    if "!WDA_COUNT!"=="0" (
        echo        No WDA found on this device. Install it first.
        echo        You can also set WDA_BUNDLE manually at the top of this file.
        echo.
        pause
        exit /b 1
    )
    if !WDA_COUNT! GEQ 2 (
        echo        Multiple WDA builds found:
        for %%w in (!WDA_LIST!) do echo          %%w
        set /p "WDA_BUNDLE=Type the bundle id to use (or press Enter for the first one): "
        if not defined WDA_BUNDLE (
            for /f "tokens=1" %%w in ("!WDA_LIST!") do set "WDA_BUNDLE=%%w"
        )
    ) else (
        for %%w in (!WDA_LIST!) do set "WDA_BUNDLE=%%w"
    )
    echo        WDA = !WDA_BUNDLE!
)

echo [3/4] Starting WebDriverAgent (30-60s first time) ...
if defined WDA_BUNDLE (
    start "iOS-WDA" cmd /k "%IOS_EXE% runwda --udid=%UDID% --bundleid=%WDA_BUNDLE% --testrunnerbundleid=%WDA_BUNDLE% --xctestconfig=%XCTEST_CONFIG%"
) else (
    echo        (auto-detect mode: letting go-iOS find the installed WDA)
    start "iOS-WDA" cmd /k "%IOS_EXE% runwda --udid=%UDID%"
)
timeout /t 20 /nobreak >nul

echo [4/4] Forwarding port %WDA_PORT% ...
start "iOS-Forward" cmd /k "%IOS_EXE% forward %WDA_PORT% %WDA_PORT%"
timeout /t 5 /nobreak >nul

echo.
echo Waiting for WDA (max 2 minutes)...
for /l %%i in (1,1,40) do (
    call :probe
    if "!WDA_OK!"=="1" goto :ready
    timeout /t 3 /nobreak >nul
)

echo.
echo [FAILED] WDA not ready in 2 minutes. Check:
echo   1. Phone unlocked and trusted this PC
echo   2. Settings - Privacy - Developer Mode = ON
echo   3. Settings - Developer - UI Automation = ON
echo   4. iOS-Tunnel window shows "Tunnel server started"?
echo   5. iOS-WDA window shows "authorized:true"?
echo   6. WDA app installed and certificate trusted
echo      (Settings - General - VPN and Device Management)
echo.
pause
exit /b 1

:ready
echo.
echo ============================================
echo  [SUCCESS] WDA is ready
echo  Local URL: http://127.0.0.1:%WDA_PORT%/status

:show_ip
set "PS_CMD=(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } ^| Select-Object -First 1).IPAddress"
for /f "delims=" %%i in ('powershell -NoProfile -Command "%PS_CMD%"') do set "LOCAL_IP=%%i"
if defined LOCAL_IP echo  TestHub URL: http://%LOCAL_IP%:%WDA_PORT%
echo ============================================
echo.
echo Keep the 3 windows open (iOS-Tunnel / iOS-WDA / iOS-Forward).
echo Closing any of them disconnects the device.
echo Run ios_device_stop.bat to stop the service.
echo.
pause
exit /b 0

:probe
set "WDA_OK=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%WDA_PORT%/status' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if %errorlevel% equ 0 set "WDA_OK=1"
goto :eof
