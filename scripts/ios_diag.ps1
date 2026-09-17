<#
 iOS WDA diagnostic - run this ON THE PC THAT THE IPHONE IS PLUGGED INTO.

 Two situations it is designed for:

   A. ios_wda_host.bat seems to hang ("no result for a long time")
   B. you just moved to a NEW PC and want to know what is missing BEFORE
      running the launcher (certificates, go-ios version, server address...)

 It answers, in order, the questions that actually decide whether TestHub
 can drive the device:

   0. is this PC ready at all?     certificates / go-ios version / DDI cache
   1. is go-ios (ios.exe) installed and where?  (and is it new enough?)
   2. does Windows see the iPhone at all?      [ios list]
   3. are the service ports up?                60105 tunnel / 8100 forward
   4. does WDA answer, and which bundle id?    [http://127.0.0.1:8100/status]
   5. can we reach the TestHub server?         (the address auto-register uses)

 Every step is time-boxed, so the whole script always finishes.
 Paste the output when reporting a problem.

 ASCII-only, CRLF (Windows PowerShell 5.1 / cmd safe).
#>

$ErrorActionPreference = 'SilentlyContinue'
$WdaPort = 8100

function Section([string]$t) {
    Write-Host ''
    Write-Host ('==== ' + $t + ' ====') -ForegroundColor Cyan
}
function Ok([string]$t)   { Write-Host ('  [OK]   ' + $t) -ForegroundColor Green }
function Bad([string]$t)  { Write-Host ('  [FAIL] ' + $t) -ForegroundColor Red }
function Warn2([string]$t) { Write-Host ('  [WARN] ' + $t) -ForegroundColor Yellow }
function Info([string]$t) { Write-Host ('  ' + $t) }

Write-Host '================================================='
Write-Host ' TestHub - iOS WDA diagnostic'
Write-Host (' time: ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host '================================================='

# ------------------------------------------------- 0) new-PC readiness checks
# These are the things that are FINE on the machine you first set up, and
# MISSING on a fresh PC. Checking them here turns "image auto failed with a
# cryptic SEC_E_UNTRUSTED_ROOT" into a clear one-line answer.
Section '0/5 new-PC readiness'

# ---- 0a) Apple certificates -------------------------------------------------
# 'ios image auto' talks to gs.apple.com over TLS to get the DDI signed.
# A fresh Windows install has no Apple intermediates, so that call fails with
# SEC_E_UNTRUSTED_ROOT. Browsers hide this (Chrome fetches missing certs via
# AIA), which is why "curl works in the browser" is not a valid test.
$authCa = Get-ChildItem -Path 'Cert:\LocalMachine\CA', 'Cert:\CurrentUser\CA' -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -match 'Apple Server Authentication' }
$rootCa = Get-ChildItem -Path 'Cert:\LocalMachine\Root', 'Cert:\CurrentUser\Root' -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -match 'Apple (Root|Root CA)' }
if ($authCa -and $rootCa) {
    Ok 'Apple certificates present (Server Authentication CA + Root CA)'
} else {
    if (-not $authCa) {
        Bad 'Apple "Server Authentication CA" NOT installed (needed in: Intermediate CAs)'
    }
    if (-not $rootCa) {
        Bad 'Apple "Root CA" NOT installed (needed in: Trusted Root CAs)'
    }
    Info 'Symptom if missing: "ios image auto" fails with SEC_E_UNTRUSTED_ROOT'
    Info 'FIX: install both certificates via certmgr.msc'
    Info '     Apple Server Authentication CA -> Intermediate Certification Authorities'
    Info '     Apple Root CA                   -> Trusted Root Certification Authorities'
    Info 'NOTE: being able to open gs.apple.com in a browser proves NOTHING.'
}

# ---- 0b) DDI cache freshness ------------------------------------------------
# go-ios caches developer disk images under ./devimages (relative to the
# CURRENT DIRECTORY). An image copied from an older device can be wrong for a
# newer chip and fails with:
#   could not find identity for ApBoardId 0x.. and ApChipId 0x..
$ddiDirs = @()
foreach ($c in @((Join-Path $PSScriptRoot 'devimages'), (Join-Path (Get-Location).Path 'devimages'))) {
    if (Test-Path -LiteralPath $c) { $ddiDirs += (Resolve-Path -LiteralPath $c).Path }
}
$ddiDirs = $ddiDirs | Select-Object -Unique
if ($ddiDirs.Count -eq 0) {
    Info 'no local DDI cache (devimages) - will be downloaded on first run'
} else {
    foreach ($d in $ddiDirs) {
        $imgs = Get-ChildItem -LiteralPath $d -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'ddi-*' }
        if ($imgs) {
            Ok ('DDI cache: ' + ($imgs.Name -join ', ') + '   [' + $d + ']')
            Info 'if mounting fails with "could not find identity for ApBoardId/ApChipId",'
            Info 'move this devimages folder away and let go-ios download a fresh one'
        } else {
            Warn2 ('devimages exists but holds no ddi-* folder: ' + $d)
        }
    }
}

# ---- 0c) our own LAN address ------------------------------------------------
# Needed both for the TestHub registration and for the server probe below.
$ownLanIp = ''
foreach ($c in @('ios_detect_lan_ip.ps1', 'scripts\ios_detect_lan_ip.ps1')) {
    $p = Join-Path $PSScriptRoot $c
    if (Test-Path -LiteralPath $p) {
        $ownLanIp = (& powershell -NoProfile -ExecutionPolicy Bypass -File $p 2>&1 | Out-String).Trim()
        break
    }
}
if ($ownLanIp) { Ok ('this PC LAN ip = ' + $ownLanIp) }
else { Warn2 'could not detect this PC LAN ip - run ipconfig' }

# ---------------------------------------------------------------- 1) go-ios
Section '1/5 go-ios (ios.exe)'
$iosExe = $null
$overrideFile = Join-Path $env:USERPROFILE '.testhub\ios_exe.txt'
if (Test-Path -LiteralPath $overrideFile) {
    $p = (Get-Content -LiteralPath $overrideFile -TotalCount 1).Trim()
    if ($p -and (Test-Path -LiteralPath $p)) { $iosExe = $p; Info ('from override file: ' + $p) }
}
if (-not $iosExe) {
    $cmd = Get-Command 'ios.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $iosExe = $cmd.Source }
}
if (-not $iosExe) {
    foreach ($c in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\go-ios\ios.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ios.exe'),
        'C:\tools\go-ios\ios.exe'
    )) { if (Test-Path -LiteralPath $c) { $iosExe = $c; break } }
}
if ($iosExe) {
    Ok ('ios.exe = ' + $iosExe)
    $v = & $iosExe version 2>&1 | Out-String
    if ($v.Trim()) {
        $first = $v.Trim().Split("`n")[0]
        Info ('version: ' + $first)
        # v1.0.x cannot mount the DDI for A18-era chips (iOS 26) and fails with
        # "could not find identity for ApBoardId ... / ApChipId 0x8150".
        # 1.3.2 is the first version known to work across this fleet.
        $m = [regex]::Match($first, '(\d+)\.(\d+)\.(\d+)')
        if ($m.Success) {
            $major = [int]$m.Groups[1].Value
            $minor = [int]$m.Groups[2].Value
            $patch = [int]$m.Groups[3].Value
            if ($major -lt 1 -or ($major -eq 1 -and $minor -lt 3)) {
                Bad ('go-ios ' + $m.Value + ' is TOO OLD - iOS 26 DDI mounting will fail.')
                Info 'Upgrade to 1.3.2 or newer:'
                Info '  winget upgrade --id danielpaulus.go-ios-agent -e'
            } elseif ($major -eq 1 -and $minor -eq 3 -and $patch -lt 2) {
                Warn2 ('go-ios ' + $m.Value + ' - 1.3.2 or newer recommended for iOS 26 devices.')
            } else {
                Ok ('go-ios ' + $m.Value + ' - new enough for iOS 17.4+ devices.')
            }
        }
    }
} else {
    Bad 'ios.exe not found. Install go-ios:'
    Info 'winget install --id danielpaulus.go-ios-agent -e'
}

# ------------------------------------------------------------ 2) device list
Section '2/5 iPhone visible to Windows'
if ($iosExe) {
    $raw = (& $iosExe list 2>&1 | Out-String).Trim()
    if ($raw -match '\{"deviceList":\s*\[\s*\]\}') {
        Bad 'ios list returned {"deviceList":[]} - the USB session is dead.'
        Info 'FIX: unplug and replug the cable (nothing else recovers this).'
        Info 'Also check: phone unlocked? "Trust this computer" tapped?'
    } elseif ($raw -match '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}') {
        $udids = [regex]::Matches($raw, '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}') | ForEach-Object { $_.Value } | Select-Object -Unique
        Ok ('detected UDID(s): ' + ($udids -join ' '))
    } elseif (-not $raw) {
        Bad 'ios list printed nothing (go-iOS agent may be stuck).'
        Info 'Delete stale processes by PORT only (never by image name):'
        Info 'Get-NetTCPConnection -LocalPort 27015 -State Listen'
    } else {
        Warn2 ('unrecognised output: ' + $raw.Substring(0, [Math]::Min(200, $raw.Length)))
    }
}

# ------------------------------------------------------------------ 3) ports
Section '3/5 service ports'
foreach ($port in @(60105, $WdaPort, 27015)) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    if ($owners) {
        $names = @()
        foreach ($o in $owners) { $names += (Get-Process -Id $o -ErrorAction SilentlyContinue).ProcessName }
        Ok ('port ' + $port + ' LISTENING (pid ' + ($owners -join ',') + ' ' + ($names -join ',') + ')')
    } else {
        if ($port -eq 27015) { Info 'port 27015 not listening (normal - agent starts on demand)' }
        else { Bad ('port ' + $port + ' NOT listening') }
    }
}

# -------------------------------------------------------------------- 4) WDA
Section ('4/5 WebDriverAgent http://127.0.0.1:' + $WdaPort + '/status')
$wdaOk = $false
$lanIp = $null
foreach ($ip in @('127.0.0.1')) {
    try {
        $r = Invoke-WebRequest -Uri ('http://' + $ip + ':' + $WdaPort + '/status') -TimeoutSec 6 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            $wdaOk = $true
            Ok ('WDA answers on ' + $ip)
            $json = $r.Content | ConvertFrom-Json
            Info ('ready  = ' + $json.value.ready)
            Info ('state  = ' + $json.value.state)
            Info ('device = ' + $json.value.device)
        }
    } catch {
        Bad ('no answer on ' + $ip + ' : ' + $_.Exception.Message)
    }
}
if (-not $wdaOk) {
    Info ''
    Info 'WDA is not reachable. Usual causes, cheapest first:'
    Info '  * the "iOS-WDA" window printed "Did not find test app"  -> wrong bundle id'
    Info '  * the "iOS-WDA" window printed "Device not found"       -> replug the cable'
    Info '  * the "iOS-Forward" window is closed or died            -> restart ios_wda_host.bat'
    Info '  * WDA takes 1-3 minutes on first run after a phone reboot'
}

# ------------------------------------------------- 5) TestHub server address
# This is the check that would have caught "register failed: unable to connect
# to the remote server" on a new PC: the address was remembered from the old
# machine and never verified.
Section '5/5 TestHub server reachability'
$cfgFile = Join-Path $env:USERPROFILE '.testhub\server.txt'
$cachedUrl = ''
if (Test-Path -LiteralPath $cfgFile) {
    $cachedUrl = (Get-Content -LiteralPath $cfgFile -TotalCount 1).Trim()
    Info ('cached address (' + $cfgFile + '): ' + $cachedUrl)
} else {
    Info 'no cached address yet (will be asked once on first run)'
}

$resolver = Join-Path $PSScriptRoot 'ios_resolve_server.ps1'
if (Test-Path -LiteralPath $resolver) {
    $line = (& powershell -NoProfile -ExecutionPolicy Bypass -File $resolver -ServerUrl $cachedUrl 2>&1 | Out-String).Trim()
    if ($line -match '^OK\s+(.+)$') {
        $resolved = $Matches[1].Trim()
        Ok ('server answers: ' + $resolved)
        if ($cachedUrl -and ($cachedUrl -ne $resolved)) {
            Bad ('the CACHED address does NOT answer - it is stale.')
            Info 'This is what makes auto-registration fail on a moved/copied setup.'
            Info ('FIX: run ios_wda_host.bat again - it will switch to ' + $resolved + ' by itself,')
            Info '     or edit the file above and put that URL in it.'
        }
    } elseif ($line -match '^ASK') {
        Bad 'no TestHub server answered (tried the cache, the built-in default, and nearby hosts)'
        Info ('built-in default is http://192.168.8.75:18000 - if your server sits elsewhere,')
        Info 'edit it in ios_resolve_server.ps1 or type it when ios_wda_host.bat asks (only once).'
        Info 'Also confirm: same LAN as the server, and port 18000 allowed through its firewall.'
    } else {
        Warn2 ('resolver output was not understood: ' + $line)
    }
} else {
    Warn2 'ios_resolve_server.ps1 is missing next to this script - cannot verify the address'
}

# --------------------------------------------------------------- LAN IP last
Section 'LAN address for TestHub'
if ($ownLanIp) {
    Ok ('put this into TestHub - Device Management (iOS):')
    Info ('  wda_host = ' + $ownLanIp)
    Info ('  wda_port = ' + $WdaPort)
} else {
    Warn2 'could not detect the LAN IP - run ipconfig and use the IPv4 address'
}

Write-Host ''
Write-Host '================================================='
if ($wdaOk) {
    Write-Host ' RESULT: WDA is UP - TestHub should be able to drive it.' -ForegroundColor Green
} else {
    Write-Host ' RESULT: WDA is DOWN - see the notes above.' -ForegroundColor Red
}
Write-Host '================================================='
Write-Host ''
# Pause only in an interactive console. Set TESTHUB_NOPAUSE=1 to skip it
# (used by automation and by the self-check in ios_diag.bat).
if (-not $env:TESTHUB_NOPAUSE) {
    Read-Host 'Press Enter to close'
}
