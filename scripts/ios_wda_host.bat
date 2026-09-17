@echo off
title iOS WDA Host (remote, for TestHub server)
setlocal EnableDelayedExpansion

REM ============================================================
REM iOS WDA Host - one-click launcher.
REM
REM Run this on the WORKING computer  [ the one the iPhone is plugged
REM into ] . The TestHub server connects to it over the LAN.
REM
REM MUST be run as Administrator: 'ios tunnel start' needs elevation.
REM
REM The sequence below is exactly the manual sequence that has been
REM verified to work end to end:
REM   1 ]  release leftover ports        2 ]  mount Developer Disk Image
REM   3 ]  start USB tunnel              4 ]  start WebDriverAgent
REM   5 ]  forward port 8100             6 ]  register on TestHub
REM
REM Rules that MUST NOT be broken [each was learned the hard way]:
REM   * Never 'taskkill /IM ios.exe /T': go-iOS is also the USB bridge,
REM     killing it drops the phone off the bus and the only fix is
REM     replugging the cable.
REM   * Never kill the agent on port 27015: it is restarted lazily and
REM     killing it makes the next command report
REM     'Device ... not found. Is it attached to the machine?'.
REM   * Only ports 60105 [tunnel] and 8100 [forward] are leftovers that
REM     need releasing between runs.
REM   * 'ios image auto' goes over lockdown and does NOT need a tunnel,
REM     so the DDI step comes first. Forward must always be last.
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
REM Load 2) here so a fresh device never needs manual setup. 1) is resolved
REM later, once the UDID is known (the UDID is not available yet at this point
REM - reading the cache here used to silently never match).
set "DEFAULT_WDA_BUNDLE="
if exist "%WDA_BUNDLE_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%WDA_BUNDLE_FILE%") do (
        if /i "%%A"=="default" set "DEFAULT_WDA_BUNDLE=%%B"
    )
)

REM Candidates tried in order when discovery fails.
REM EVERY device in this fleet is imaged with the same resigned WDA, so .yl2.
REM is the norm; the others are kept only as a safety net.
set "STD_WDA_BUNDLE=com.facebook.WebDriverAgentRunner.yl2.xctrunner"
set "ALT_WDA_BUNDLE=com.facebook.WebDriverAgentRunner.t.xctrunner"
set "XCTEST_CONFIG=WebDriverAgentRunner.xctest"
set "IOS_EXE="

REM ---- TestHub auto-registration [address is VERIFIED, not just remembered] ----
REM
REM Do NOT go back to "read server.txt and trust it". That is exactly what
REM broke on a new PC: copying the .testhub folder (the natural thing to do)
REM brings the OLD address along, the script never asks, and registration
REM fails later with a vague "unable to connect to the remote server".
REM
REM New contract, implemented in ios_resolve_server.ps1:
REM   cached address -> built-in default -> a few hosts on our own subnet -> ask
REM Only an address that actually ANSWERED is written back to the cache.
set "TESTHUB_URL="
set "TESTHUB_TOKEN="
set "TESTHUB_CFG=%USERPROFILE%\.testhub\server.txt"
set "TESTHUB_DEFAULT=http://192.168.8.75:18000"
set "TESTHUB_CACHED="
if exist "%TESTHUB_CFG%" (
    set /p TESTHUB_CACHED=<"%TESTHUB_CFG%"
)

echo [pre] Resolving TestHub server address ...
REM 'tokens=1,*' is required: the OK line is "OK <url>", and %%B holds the
REM whole URL. Only the OK branch assigns; ASK just leaves TESTHUB_URL empty,
REM which the "if not defined" block below turns into a prompt.
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
    echo  TestHub server address needed
    echo ============================================
    echo  Could not auto-detect one. Example:
    echo    http://192.168.8.75:18000
    echo  Press Enter to skip [the device will not be
    echo  registered automatically; you can still add
    echo  it by hand in TestHub - Device Management].
    echo(
    set /p "TESTHUB_INPUT=TestHub server address: "
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
            echo               Check: is the TestHub backend running, and is
            echo               port 18000 reachable from this PC?
        )
    )
)
if not defined TESTHUB_URL (
    echo        Continuing without auto-registration.
    echo(
)

echo ============================================
echo  iOS WDA Host [remote for TestHub]  v5
echo  Port : %WDA_PORT%
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
REM Delegated to a PowerShell helper on purpose. 'where ios' alone is not
REM reliable: it also looks for ios.ps1/ios.cmd, and a machine that HAS
REM go-ios but did not add it to PATH reports 'Could not find files' even
REM though ios.exe sits in a standard folder. That used to abort the whole
REM launcher with a misleading 'go-ios missing' error.
if defined IOS_EXE goto :has_ios
echo [1/6] Locating go-ios [ios.exe] ...
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_find_exe.ps1"') do set "IOS_EXE=%%i"
if defined IOS_EXE (
    if exist "%IOS_EXE%" goto :has_ios
    REM 'ios' from PATH is a bare command name, not a path - accept it as-is
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
REM Reject anything that is not a real UDID [xxxx-xxxxxxxxxxxxxxxx or 40 hex]
echo %UDID%| findstr /r /i "^[0-9a-f][0-9a-f]*-[0-9a-f][0-9a-f]*$ ^[0-9a-f][0-9a-f]*$" >nul
if errorlevel 1 (
    echo        [ERROR] Invalid UDID: "%UDID%"
    echo        Run "ios list" manually and check the output.
    echo(
    pause
    exit /b 1
)
echo        UDID = %UDID%

REM Per-device override now that the UDID is known (step 1 of the priority
REM list at the top). A "default=" line loaded earlier still wins if this
REM device has no entry of its own.
if exist "%WDA_BUNDLE_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%WDA_BUNDLE_FILE%") do (
        if /i "%%A"=="%UDID%" set "WDA_BUNDLE=%%B"
    )
)
if not defined WDA_BUNDLE set "WDA_BUNDLE=%DEFAULT_WDA_BUNDLE%"
if defined WDA_BUNDLE echo        WDA bundle pinned: !WDA_BUNDLE!

REM ---- 2b ]  iOS version note ----
REM This launcher targets iOS 17.4 and newer ONLY, so no version probing is
REM done here. Probing was REMOVED on purpose: it ran 'ios info', and when the
REM flags were wrong go-ios printed its whole USAGE text  [ full of brackets,
REM pipes and angle brackets ]  which cmd then tried to re-parse - that is what
REM produced the bogus 'then was not expected at this time'. Every iOS 17.4+
REM device uses the userspace tunnel and needs no wintun.dll.
echo        target: iOS 17.4 or newer  [ userspace tunnel ]
echo(

REM ---- 3 ]  release leftover services [60105 tunnel / 8100 forward] ----
REM ONLY these two. Do not touch 27015 [agent] and never kill by image
REM name - see the rules at the top of this file.
echo [2/6] Releasing leftover services ...
set "BUSY=0"
netstat -ano | findstr ":60105" | findstr LISTENING >nul
if %errorlevel% equ 0 set "BUSY=1"
netstat -ano | findstr ":8100" | findstr LISTENING >nul
if %errorlevel% equ 0 set "BUSY=1"
REM Same approach as [4/6]: the kill-and-wait is one PowerShell call.
REM No labels, no goto, no nested blocks - see the long explanation in [4/6]
REM for why the cmd label-loop version had to go.
if not "%BUSY%"=="1" echo        nothing to release
if "%BUSY%"=="1" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_release_ports.ps1" -Ports 60105,8100 -Timeout 20

REM ---- 4 ]  Developer Disk Image [iOS 17+ needs it] ----
REM Comes BEFORE the tunnel on purpose: 'ios image auto' works over
REM lockdown and does not need a tunnel. A mounted DDI stays valid until
REM the phone reboots, so this is idempotent and a failure is survivable.
echo [3/6] Mounting Developer Disk Image [mandatory on iOS 17+] ...
%IOS_EXE% image auto --udid=%UDID%
echo(

REM ---- 5 ]  USB tunnel ----
REM CRITICAL: port 60105 must be EMPTY before we start, and the process that
REM ends up holding it must be the one WE started.
REM
REM Why [this was a real, very expensive bug]: 'start' launches the tunnel in a
REM separate window and we cannot read its output. The old code then just polled
REM 'is 60105 listening?' - and if a STALE tunnel was already holding the port,
REM the poll succeeded after 0s while our own 'tunnel start' had actually FAILED
REM with 'Only one usage of each socket address ... 60105'. The script reported
REM 'tunnel is up on 60105 [after 0s]' and carried on with a dead tunnel, which
REM then made 'runwda' fail with
REM   'cannot create a tunnel connection to testmanagerd ... missing tunnel address and RSD port'
REM and every WDA bundle id look broken. Always release 60105 first and verify
REM the OWNING PID CHANGED.
echo [4/6] Starting USB tunnel ...
REM ---------------------------------------------------------------------------
REM Everything below is done in ONE PowerShell call on purpose.
REM
REM Why: this section used to be a cmd label loop  [ ':tunnel_waitgone_loop' with
REM 'goto' jumps back and forth ] . On the target machine cmd kept dying with
REM     'then was not expected at this time'
REM right after the loop's first echo, even though there is no 'if ... then'
REM anywhere in this file. The message is bogus - cmd simply mis-parses blocks
REM that mix forward and backward label jumps. Doing the kill+wait in
REM PowerShell removes every label, every goto, every nested block, and the
REM whole class of error with them. Do NOT 'simplify' this back into cmd.
set "OLD_TUNNEL_PID="
for /f "usebackq tokens=*" %%I in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 60105 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -join ' '"`) do set "OLD_TUNNEL_PID=%%I"
if defined OLD_TUNNEL_PID echo        port 60105 is held by PID !OLD_TUNNEL_PID! - releasing it first
REM The kill+wait logic lives in a helper .ps1 next to this file, NOT inline.
REM A long 'powershell -Command ...' line is a liability here: it is full of
REM special characters and cmd has been seen to mis-tokenise it, which then
REM surfaces as an unrelated parse error on the FOLLOWING line. Keeping the
REM cmd line short and boring removes that risk entirely.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_release_ports.ps1" -Ports 60105 -Timeout 20
REM ---- tunnel mode ----
REM Hardcoded userspace on purpose.
REM This launcher supports iOS 17.4 and newer only, and every 17.4+ device
REM works with the userspace tunnel. That means:
REM   * no wintun.dll needed
REM   * no wintun.dll probing
REM   * no iOS version probing
REM   * no kernel/userspace decision tree
REM All of that used to live here and it is what broke the script: the probes
REM printed text full of brackets and angle brackets which cmd re-parsed, and
REM the nested if-blocks lost track of their parentheses. None of it is
REM needed for 17.4+, so none of it is here any more.
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
        REM The listener is the STALE process we just tried to kill - our own
        REM 'tunnel start' must have failed  [ usually 'Only one usage' ] . Refuse
        REM to continue: a dead tunnel silently breaks WDA and wastes minutes.
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
REM Bundle id discovery is the single most fragile step: WDA builds are resigned
REM with ids that differ per device  [ .t. / .yl2. / ... ] , and 'ios apps' only works
REM once the go-iOS agent is up. So:
REM   - ios_detect_wda.ps1 retries until the agent answers, and caches per UDID
REM   - if discovery still fails we do NOT bet on one hard-coded id; we try a
REM     candidate list in order and keep the first one that actually boots WDA.
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
REM ORDER IS CRITICAL and this used to be a real bug: the WDA probe below
REM hits http://127.0.0.1:8100/status, which only exists once 'ios forward'
REM is running. The forward used to be started AFTER the probe loop, so the
REM probe could never succeed - every candidate bundle id was reported as
REM 'did not answer' and the script always ended in [FAILED], even though
REM WDA was running fine on the phone. Forward first, then probe.
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
REM Candidates: discovered id first, then the well-known ids as fallback.
set "WDA_TRY=!WDA_BUNDLE!"
if not defined WDA_TRY set "WDA_TRY=!STD_WDA_BUNDLE!"
set "WDA_TRY=!WDA_TRY! !STD_WDA_BUNDLE! !ALT_WDA_BUNDLE! com.facebook.WebDriverAgentRunner.xctrunner"
set "WDA_WORKED="
REM TRIED holds the ids already attempted  [ with spaces on both sides so we can do
REM an exact substring test ] . The discovered id often EQUALS one of the fallbacks,
REM so a plain '!=  previous' check would retry it and waste another 25s+60s.
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
REM Every candidate bundle id failed. Report which ones were tried so the next
REM person knows exactly where it stopped, then point at the WDA window.
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
REM ---- 7 ]  the forward is ALREADY running [started before the probe at 6a] ----
REM The probe reads http://127.0.0.1:8100/status, so 8100 MUST be forwarded
REM before WDA is probed. Starting it here  [ after the probe ]  was the bug that
REM made every candidate bundle id look dead. Nothing to do but wait now.

echo(
echo Waiting for WDA to answer [max 2 minutes]...
for /l %%i in (1,1,40) do (
    call :probe
    if "!WDA_OK!"=="1" goto :ready
    timeout /t 3 /nobreak >nul
)

REM ---- one recovery pass ----
REM NOTE: no /T here. /T kills the whole child process tree, which has
REM previously taken go-iOS' USB bridge down with it and left the device
REM invisible  [ ios list -^ gt  {'deviceList':[]} ]  until the cable was replugged.
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
echo  [SUCCESS] WDA is ready
echo  Local URL: http://127.0.0.1:%WDA_PORT%/status

:show_ip
REM Resolve this PC's LAN IP via the helper script. Doing it inline used to
REM come back EMPTY on machines with virtual adapters  [ WSL / Hyper-V /
REM Docker ] , producing 'TestHub URL: http:// :8100' and registering the
REM device with an empty wda_host - then the platform could not reach it.
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
    echo Registering this device on TestHub ...
    REM The register script resolves the LAN IP itself when LOCAL_IP is empty,
    REM so pass whatever we have and let it fill the gap.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_register_device.ps1" -ServerUrl "!TESTHUB_URL!" -Udid "!UDID!" -WdaHost "!LOCAL_IP!" -WdaPort !WDA_PORT! -Token "!TESTHUB_TOKEN!"
)
echo(
echo Device should now appear in TestHub - Device Management.
echo If auto-registration is off or failed, add it by hand:
echo    platform = iOS , udid = !UDID!
echo    wda_host = !LOCAL_IP! , wda_port = !WDA_PORT!
echo(
pause
exit /b 0

REM =================== subroutines ===================

REM IMPORTANT - why these subroutines return with 'exit /b' and NOT 'goto :eof':
REM on several Windows builds a 'goto :eof' that ends a called subroutine makes
REM the CALLER's very next line fail with the useless message
REM     'then was not expected at this time'
REM even though this file contains no 'if ... then' anywhere. 'exit /b' returns
REM from a call in a clean, well-defined way and does not trigger it. Keep it.
:waitport
REM Wait until TCP port %~1 listens. Sets PORT_OK [1/0] and WAITED [seconds].
REM Read PORT_OK immediately after the call.
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