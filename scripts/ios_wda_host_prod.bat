@echo off
title iOS WDA Host (PRODUCTION, port 8080)
setlocal EnableDelayedExpansion

REM ============================================================
REM iOS WDA Host - PRODUCTION launcher.
REM
REM Same as ios_wda_host.bat EXCEPT it registers the device on the
REM PRODUCTION TestHub (frontend/nginx on port 8080) instead of the
REM dev instance (18000).
REM
REM WHY A SEPARATE FILE INSTEAD OF A FLAG:
REM   The two environments must be usable independently and must not
REM   fight over the cached server address. Using one shared script with
REM   a switch means switching back and forth, and it is easy to forget
REM   which mode you are in. Two files = no state to remember.
REM
REM Three deliberate differences from ios_wda_host.bat:
REM   1. TESTHUB_DEFAULT   -> http://192.168.8.75:8080   (prod nginx)
REM   2. TESTHUB_CFG       -> %USERPROFILE%\.testhub\server_prod.txt
REM                           (separate cache => dev cache stays intact)
REM   3. banner text says PRODUCTION
REM Everything else - the whole go-ios sequence, the port rules, the
REM WDA bundle discovery, the subroutines - is identical on purpose.
REM Keep this file in sync when ios_wda_host.bat changes.
REM
REM Run this on the WORKING computer [the one the iPhone is plugged
REM into]. MUST be run as Administrator: 'ios tunnel start' needs it.
REM
REM Rules that MUST NOT be broken [each was learned the hard way]:
REM   * Never 'taskkill /IM ios.exe /T': go-iOS is also the USB bridge,
REM     killing it drops the phone off the bus and the only fix is
REM     replugging the cable.
REM   * Never kill the agent on port 27015.
REM   * Only ports 60105 [tunnel] and 8100 [forward] are leftovers.
REM   * Forward port 8100 BEFORE probing WDA, never after.
REM
REM Stop with ios_device_stop.bat, or just close the 3 windows.
REM ASCII-only, CRLF - do not let an editor convert the line endings.
REM ============================================================

set "UDID="
set "WDA_PORT=8100"
set "WDA_BUNDLE="
set "WDA_BUNDLE_FILE=%USERPROFILE%\.testhub\wda_bundle.txt"

REM ---- WDA bundle id: where it comes from ----
REM Priority (first hit wins):
REM   1. <udid>=<id>   line in wda_bundle.txt   -> per-device override
REM   2. default=<id>  line in wda_bundle.txt   -> fleet-wide default
REM   3. auto-discovery via "ios apps" (done later, once the tunnel is up)
REM   4. the candidate list below               -> last-resort fallbacks
REM
REM wda_bundle.txt is SHARED with the dev launcher on purpose: the WDA
REM build on a given phone is the same regardless of which TestHub you
REM register it with, so the cache is still valid.
set "DEFAULT_WDA_BUNDLE="
if exist "%WDA_BUNDLE_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%WDA_BUNDLE_FILE%") do (
        if /i "%%A"=="default" set "DEFAULT_WDA_BUNDLE=%%B"
    )
)

set "STD_WDA_BUNDLE=com.facebook.WebDriverAgentRunner.yl2.xctrunner"
set "ALT_WDA_BUNDLE=com.facebook.WebDriverAgentRunner.t.xctrunner"
set "XCTEST_CONFIG=WebDriverAgentRunner.xctest"
set "IOS_EXE="

REM ---- TestHub PRODUCTION auto-registration [address is VERIFIED] ----
REM
REM Port 8080 is the PRODUCTION frontend (nginx). nginx reverse-proxies
REM /api/ to the backend container on 8000, so 8080 is a valid API entry
REM point and is the address a device PC should use.
REM
REM The cache file is server_prod.txt, NOT server.txt: the dev launcher
REM owns server.txt. Sharing it would make each launcher overwrite the
REM other's address, costing an extra failed probe every run.
REM
REM Only an address that actually ANSWERED is written back to the cache.
set "TESTHUB_URL="
set "TESTHUB_TOKEN="
set "TESTHUB_CFG=%USERPROFILE%\.testhub\server_prod.txt"
set "TESTHUB_DEFAULT=http://192.168.8.75:8080"
set "TESTHUB_CACHED="
if exist "%TESTHUB_CFG%" (
    set /p TESTHUB_CACHED=<"%TESTHUB_CFG%"
)

echo [pre] Resolving TestHub PRODUCTION server address ...
for /f "tokens=1,*" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_resolve_server.ps1" -ServerUrl "!TESTHUB_CACHED!" -DefaultUrl "!TESTHUB_DEFAULT!"') do (
    if /i "%%A"=="OK" set "TESTHUB_URL=%%B"
)
if defined TESTHUB_URL echo        using !TESTHUB_URL!
if defined TESTHUB_CACHED (
    if /i "!TESTHUB_CACHED!"=="!TESTHUB_URL!" (
        echo        [cached address verified]
    ) else (
        if defined TESTHUB_URL echo        [cached address failed - switched to the verified one]
    )
)

if not defined TESTHUB_URL (
    echo ============================================
    echo  TestHub PRODUCTION address needed
    echo ============================================
    echo  Could not auto-detect one. Example:
    echo    http://192.168.8.75:8080
    echo  Press Enter to skip [the device will not be
    echo  registered automatically; you can still add
    echo  it by hand in TestHub - Device Management].
    echo(
    set /p "TESTHUB_INPUT=TestHub PRODUCTION address: "
    if defined TESTHUB_INPUT (
        echo !TESTHUB_INPUT!| findstr /i /r "^http:// ^https://" >nul
        if errorlevel 1 (
            set "TESTHUB_TRY=http://!TESTHUB_INPUT!"
        ) else (
            set "TESTHUB_TRY=!TESTHUB_INPUT!"
        )
        echo        checking !TESTHUB_TRY! ...
        for /f "tokens=1,*" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_resolve_server.ps1" -ServerUrl "!TESTHUB_TRY!"') do (
            if /i "%%A"=="OK" set "TESTHUB_URL=%%B"
        )
        if defined TESTHUB_URL (
            if not exist "%USERPROFILE%\.testhub" mkdir "%USERPROFILE%\.testhub"
            >"%TESTHUB_CFG%" echo !TESTHUB_URL!
            echo        verified and saved to %TESTHUB_CFG%
        ) else (
            echo        [WARN] that address did not answer - NOT saved.
            echo               Check: is the PRODUCTION TestHub running, and
            echo               is port 8080 reachable from this PC?
        )
    )
)
if not defined TESTHUB_URL (
    echo        Continuing without auto-registration.
    echo(
)

echo ============================================
echo  iOS WDA Host [PRODUCTION TestHub]  v1
echo  Port : %WDA_PORT%
echo  Target: !TESTHUB_URL!
echo ============================================
echo(

REM ---- 0 ]  admin check ----
set "ADMIN_SHELL="
net session >nul 2>nul
if %errorlevel% equ 0 set "ADMIN_SHELL=1"
if not defined ADMIN_SHELL (
    echo [WARN] Not running as Administrator.
    echo        "ios tunnel start" needs elevation on Windows.
    echo        Right-click this file and pick "Run as administrator".
    echo(
    echo        Continuing in 8 seconds ^(Ctrl+C to abort^) ...
    timeout /t 8 /nobreak >nul
    echo(
)

REM ---- 1 ]  locate ios.exe ----
if defined IOS_EXE goto :has_ios
echo [1/6] Locating go-ios [ios.exe] ...
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_find_exe.ps1"') do set "IOS_EXE=%%i"
if defined IOS_EXE (
    if exist "%IOS_EXE%" goto :has_ios
    if /i "%IOS_EXE%"=="ios" goto :has_ios
)
echo [ERROR] ios.exe not found [go-ios is not installed on this PC].
echo(
echo   This computer has never been set up for iOS testing. Install go-ios:
echo(
echo     winget install --id danielpaulus.go-ios-agent -e
echo(
echo    - or download ios.exe from https://github.com/danielpaulus/go-ios/releases
echo    and put it into one of:  C:\tools\go-ios\   or   %%LOCALAPPDATA%%\Programs\go-ios\  - 
echo(
echo   Then close this window and run this file again [no reboot needed].
echo(
echo   If you installed it somewhere else, tell the script where it is by
echo   creating this file with the full path inside:
echo     %%USERPROFILE%%\.testhub\ios_exe.txt
echo(
pause
exit /b 1

:has_ios
echo [0/6] Using ios binary: %IOS_EXE%

REM ---- 2 ]  detect UDID ----
if defined UDID goto :udid_done
echo [1/6] Detecting connected iOS device...
set "UDID_LIST="
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_udid.ps1"') do set "UDID_LIST=%%i"
set "UDID_COUNT=0"
for %%u in (%UDID_LIST%) do set /a UDID_COUNT+=1

if "%UDID_COUNT%"=="0" (
    echo        No device on the first attempt. Retrying once ...
    timeout /t 5 /nobreak >nul
    set "UDID_LIST="
    for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_udid.ps1"') do set "UDID_LIST=%%i"
    set "UDID_COUNT=0"
    for %%u in (!UDID_LIST!) do set /a UDID_COUNT+=1
)

if "%UDID_COUNT%"=="0" (
    echo(
    echo [ERROR] No iPhone detected.
    echo         - Is the cable plugged in and the phone unlocked?
    echo         - Did you tap "Trust this computer"?
    echo         - If you saw deviceList:[] , unplug and replug the cable:
    echo           that means the USB session was lost earlier.
    echo         - Manual check:  ios list
    echo(
    pause
    exit /b 1
)

if %UDID_COUNT% GEQ 2 (
    echo        Multiple devices found:
    for %%u in (%UDID_LIST%) do echo          %%u
    set /p "UDID=Type the UDID to use [Enter = first one]: "
    if not defined UDID (
        for /f "tokens=1" %%u in ("%UDID_LIST%") do set "UDID=%%u"
    )
) else (
    for %%u in (%UDID_LIST%) do set "UDID=%%u"
)

:udid_done
echo %UDID%| findstr /r /i "^[0-9a-f][0-9a-f]*-[0-9a-f][0-9a-f]*$ ^[0-9a-f][0-9a-f]*$" >nul
if errorlevel 1 (
    echo        [ERROR] Invalid UDID: "%UDID%"
    echo        Run "ios list" manually and check the output.
    echo(
    pause
    exit /b 1
)
echo        UDID = %UDID%

if exist "%WDA_BUNDLE_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%WDA_BUNDLE_FILE%") do (
        if /i "%%A"=="%UDID%" set "WDA_BUNDLE=%%B"
    )
)
if not defined WDA_BUNDLE set "WDA_BUNDLE=%DEFAULT_WDA_BUNDLE%"
if defined WDA_BUNDLE echo        WDA bundle pinned: !WDA_BUNDLE!

REM ---- 2b ]  iOS version note ----
REM This launcher targets iOS 17.4 and newer ONLY, so no version probing.
echo        target: iOS 17.4 or newer  [ userspace tunnel ]
echo(

REM ---- 3 ]  release leftover services [60105 tunnel / 8100 forward] ----
echo [2/6] Releasing leftover services ...
set "BUSY=0"
netstat -ano | findstr ":60105" | findstr LISTENING >nul
if %errorlevel% equ 0 set "BUSY=1"
netstat -ano | findstr ":8100" | findstr LISTENING >nul
if %errorlevel% equ 0 set "BUSY=1"
if not "%BUSY%"=="1" echo        nothing to release
if "%BUSY%"=="1" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_release_ports.ps1" -Ports 60105,8100 -Timeout 20

REM ---- 4 ]  Developer Disk Image [iOS 17+ needs it] ----
echo [3/6] Mounting Developer Disk Image [mandatory on iOS 17+] ...
%IOS_EXE% image auto --udid=%UDID%
echo(

REM ---- 5 ]  USB tunnel ----
echo [4/6] Starting USB tunnel ...
set "OLD_TUNNEL_PID="
for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 60105 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -join ' '"`) do set "OLD_TUNNEL_PID=%%I"
if defined OLD_TUNNEL_PID echo        port 60105 is held by PID !OLD_TUNNEL_PID! - releasing it first

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_release_ports.ps1" -Ports 60105 -Timeout 20
set "TUNNEL_ENV=user"
set "TUNNEL_MODE=--userspace"
echo        tunnel mode = userspace
echo(
start "iOS-Tunnel" cmd /k "set ENABLE_GO_IOS_AGENT=user&& %IOS_EXE% tunnel start --udid=%UDID% --userspace"
echo        waiting for port 60105 ...
echo(
call :waitport 60105 90
set "NEW_TUNNEL_PID="
for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 60105 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -join ' '"`) do set "NEW_TUNNEL_PID=%%I"
if "!PORT_OK!"=="1" (
    if "!NEW_TUNNEL_PID!"=="!OLD_TUNNEL_PID!" (
        echo(
        echo [ERROR] Port 60105 is still held by the OLD process [PID !NEW_TUNNEL_PID!].
        echo         Our "tunnel start" therefore did NOT take effect.
        echo         Look at the "iOS-Tunnel" window for the real error, usually:
        echo           "Only one usage of each socket address ... 60105"
        echo              - a tunnel from a previous run is still alive
        echo           "Failed to connect to the device"
        echo              - unplug and replug the USB cable, then retry
        echo         You may also run ios_device_stop.bat first and retry.
        echo(
        pause
        exit /b 1
    )
    echo        tunnel is up on 60105 [after !WAITED!s, pid !NEW_TUNNEL_PID!]
) else (
    echo(
    echo [ERROR] The tunnel never came up [port 60105].
    echo         Look at the "iOS-Tunnel" window:
    echo           "Only one usage ... 60105"  -^> a tunnel is still running,
    echo              close everything and run ios_device_stop.bat first
    echo           "needs elevated privileges"  -^> run this as Administrator
    echo(
    pause
    exit /b 1
)

REM ---- 6 ]  WebDriverAgent ----
if not defined WDA_BUNDLE (
    echo [5/6] Detecting installed WebDriverAgent...
    set "WDA_LIST="
    for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_wda.ps1" -udid "%UDID%"') do set "WDA_LIST=%%i"
    set "WDA_COUNT=0"
    for %%w in (!WDA_LIST!) do set /a WDA_COUNT+=1
    if !WDA_COUNT! GEQ 1 (
        echo        found !WDA_COUNT! candidate^(s^):
        for %%w in (!WDA_LIST!) do echo          %%w
        for /f "tokens=1" %%w in ("!WDA_LIST!") do set "WDA_BUNDLE=%%w"
    ) else (
        echo        Could not enumerate apps [agent not ready] - will try known ids
    )
)

REM ---- 6a ]  forward port 8100 FIRST ----
REM ORDER IS CRITICAL: the WDA probe below hits http://127.0.0.1:8100/status,
REM which only exists once 'ios forward' is running.
echo [6/6] Forwarding port %WDA_PORT% [before probing WDA] ...
taskkill /F /FI "WINDOWTITLE eq iOS-Forward*" >nul 2>nul
timeout /t 1 /nobreak >nul
start "iOS-Forward" cmd /k "%IOS_EXE% forward %WDA_PORT% %WDA_PORT%"
echo        waiting for port %WDA_PORT% to listen ...
call :waitport %WDA_PORT% 30
if "!PORT_OK!"=="1" (
    echo        forward is up on %WDA_PORT%
) else (
    echo        [WARN] port %WDA_PORT% never started listening.
    echo               Look at the "iOS-Forward" window.
)

REM ---- 6b ]  start WDA, trying candidates until one answers ----
set "WDA_TRY=!WDA_BUNDLE!"
if not defined WDA_TRY set "WDA_TRY=!STD_WDA_BUNDLE!"
set "WDA_TRY=!WDA_TRY! !STD_WDA_BUNDLE! !ALT_WDA_BUNDLE! com.facebook.WebDriverAgentRunner.xctrunner"
set "WDA_WORKED="
set "TRIED= "

for %%B in (!WDA_TRY!) do (
    if not defined WDA_WORKED (
        echo !TRIED! | findstr /C:" %%B " >nul
        if errorlevel 1 (
            set "TRIED=!TRIED!%%B "
            echo [5/6] Starting WebDriverAgent [bundle=%%B] ...
            taskkill /F /FI "WINDOWTITLE eq iOS-WDA*" >nul 2>nul
            timeout /t 2 /nobreak >nul
            start "iOS-WDA" cmd /k "%IOS_EXE% runwda --udid=!UDID! --bundleid=%%B --testrunnerbundleid=%%B --xctestconfig=%XCTEST_CONFIG%"
            echo        waiting 25s for the runner to boot ...
            timeout /t 25 /nobreak >nul
            for /l %%i in (1,1,20) do (
                call :probe
                if "!WDA_OK!"=="1" (
                    set "WDA_WORKED=%%B"
                ) else (
                    timeout /t 3 /nobreak >nul
                )
            )
            if defined WDA_WORKED (
                echo        [OK] bundle %%B works
                set "WDA_BUNDLE=%%B"
            ) else (
                echo        bundle %%B did not answer - trying next candidate
            )
        ) else (
            echo        skipping %%B [already tried]
        )
    )
)

if not defined WDA_WORKED goto :wda_failed
set "WDA_BUNDLE=!WDA_WORKED!"
goto :fwd_port

:wda_failed
echo(
echo [FAILED] WDA did not answer for ANY of these bundle ids:
for %%B in (!WDA_TRY!) do echo            %%B
echo(
echo          Look at the "iOS-WDA" window; the usual errors are:
echo            "Did not find test app for ..."  -^> wrong bundle id:
echo                run  ios apps --udid=%UDID%  to list the real one
echo            "Device not found"               -^> USB session lost: REPLUG the cable
echo            "Only one usage ... 27015"       -^> stale agent: run
echo                ios_device_stop.bat, then start again
echo(
echo          To pin the correct id manually, put it in:
echo            %USERPROFILE%\.testhub\wda_bundle.txt
echo            format:  %UDID%=com.facebook.WebDriverAgentRunner.xxx.xctrunner
echo(
pause
exit /b 1

:fwd_port
echo(
echo Waiting for WDA to answer [max 2 minutes]...
for /l %%i in (1,1,40) do (
    call :probe
    if "!WDA_OK!"=="1" goto :ready
    timeout /t 3 /nobreak >nul
)

echo(
echo [RETRY] No answer yet - restarting WebDriverAgent once ...
taskkill /F /FI "WINDOWTITLE eq iOS-WDA*" >nul 2>nul
timeout /t 5 /nobreak >nul
start "iOS-WDA" cmd /k "%IOS_EXE% runwda --udid=%UDID% --bundleid=%WDA_BUNDLE% --testrunnerbundleid=%WDA_BUNDLE% --xctestconfig=%XCTEST_CONFIG%"
echo Waiting for WDA [one more minute]...
for /l %%i in (1,1,20) do (
    call :probe
    if "!WDA_OK!"=="1" goto :ready
    timeout /t 3 /nobreak >nul
)
goto :wda_failed

:ready
echo(
echo ============================================
echo  [SUCCESS] WDA is ready   [PRODUCTION mode]
echo  Local URL: http://127.0.0.1:%WDA_PORT%/status

:show_ip
set "LOCAL_IP="
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_detect_lan_ip.ps1"') do set "LOCAL_IP=%%i"
if defined LOCAL_IP (
    echo  TestHub URL: http://!LOCAL_IP!:%WDA_PORT%
) else (
    echo  [WARN] Could not detect this PC's LAN IP.
    echo         Find it with: ipconfig   [look for "IPv4 Address"]
    echo         The device will still register, but WITHOUT wda_host -
    echo         open it in TestHub - Device Management and fill the IP in.
)
echo ============================================
echo(
echo Keep the 3 windows open [iOS-Tunnel / iOS-WDA / iOS-Forward].
echo Closing any of them disconnects the device.
if defined TESTHUB_URL (
    echo Registering this device on PRODUCTION TestHub ...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_register_device.ps1" -ServerUrl "!TESTHUB_URL!" -Udid "!UDID!" -WdaHost "!LOCAL_IP!" -WdaPort !WDA_PORT! -Token "!TESTHUB_TOKEN!"
)
echo(
echo Device should now appear in PRODUCTION TestHub - Device Management.
echo If auto-registration is off or failed, add it by hand:
echo    platform = iOS , udid = !UDID!
echo    wda_host = !LOCAL_IP! , wda_port = !WDA_PORT!
echo(
pause
exit /b 0

REM =================== subroutines ===================
REM These return with 'exit /b' and NOT 'goto :eof' on purpose - see the
REM long explanation in ios_wda_host.bat.

:waitport
set "PORT_OK=0"
set "WAITED=0"
:waitport_loop
set "PORT_CNT="
for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"`) do set "PORT_CNT=%%I"
if not "!PORT_CNT!"=="0" goto :waitport_up
set /a WAITED+=3
if !WAITED! GEQ %~2 exit /b 0
timeout /t 3 /nobreak >nul
goto :waitport_loop
:waitport_up
set "PORT_OK=1"
exit /b 0

:probe
set "WDA_OK=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%WDA_PORT%/status' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if %errorlevel% equ 0 set "WDA_OK=1"
exit /b 0
