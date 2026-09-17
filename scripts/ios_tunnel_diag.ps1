<#
 TestHub - iOS tunnel DEEP diagnostic.

 Run this ON THE PC THE IPHONE IS PLUGGED INTO, as Administrator.

 Why this exists: `ios apps` reports
     Device 'xxx' not found. Is it attached to the machine?
 while `ios list` happily prints the same UDID. Those two use DIFFERENT paths:
     ios list  -> USB/lockdown            (works with a dead tunnel)
     ios apps  -> the USB tunnel          (needs a LIVE tunnel context)
 so "list works but apps fails" means the tunnel is up but has no device
 context. This script collects everything needed to tell those apart in ONE
 run, instead of one question per round trip.

 It is READ-ONLY apart from killing ios.exe when you pass -KillStale.
 Everything is time-boxed so it always finishes.

 Output is deliberately verbose and ASCII-only (Windows PowerShell 5.1 safe).
#>
param(
    [switch]$KillStale,
    [switch]$StartTunnel,
    [string]$Udid = '00008110-001E791122A0A01E'
)

$ErrorActionPreference = 'SilentlyContinue'
$WdaPort = 8100

function Section([string]$t) { Write-Host ''; Write-Host ('==== ' + $t + ' ====') -ForegroundColor Cyan }
function Ok([string]$t)      { Write-Host ('  [OK]   ' + $t) -ForegroundColor Green }
function Bad([string]$t)     { Write-Host ('  [FAIL] ' + $t) -ForegroundColor Red }
function Warn2([string]$t)   { Write-Host ('  [WARN] ' + $t) -ForegroundColor Yellow }
function Info([string]$t)    { Write-Host ('  ' + $t) }
function Run([string]$exe, [string[]]$args2, [int]$timeoutSec = 25) {
    # Always prints the command, its exit code and its raw output.
    Write-Host ('  > ' + $exe + ' ' + ($args2 -join ' ')) -ForegroundColor DarkGray
    try {
        $out = & $exe @args2 2>&1 | Out-String
        Write-Host ('    exit=' + $LASTEXITCODE + ' len=' + $out.Trim().Length)
        foreach ($line in ($out.Trim() -split "`r?`n")) {
            if ($line.Trim()) { Write-Host ('      ' + $line.Substring(0, [Math]::Min(300, $line.Length))) }
        }
        return $out
    } catch {
        Write-Host ('    EXCEPTION: ' + $_.Exception.Message) -ForegroundColor Red
        return ''
    }
}

Write-Host '================================================='
Write-Host ' TestHub - iOS TUNNEL DEEP diagnostic'
Write-Host (' time: ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host '================================================='

# ---------------------------------------------------------------- 0) elevation
Section '0/7 elevation + environment'
$high = (whoami /groups | Out-String) -match 'S-1-16-12288'
if ($high) { Ok 'running with High Mandatory Level (elevated)' }
else { Bad 'NOT elevated - "ios tunnel start" will fail. Re-run as Administrator.' }
Info ('USERPROFILE = ' + $env:USERPROFILE)
Info ('ENABLE_GO_IOS_AGENT = ' + $(if ($env:ENABLE_GO_IOS_AGENT) { $env:ENABLE_GO_IOS_AGENT } else { '<not set>' }))

# ------------------------------------------------------------------ 1) go-ios
Section '1/7 go-ios + wintun.dll (the userspace fallback)'
$iosExe = $null
$cmd = Get-Command 'ios.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cmd) { $iosExe = $cmd.Source }
if (-not $iosExe) {
    foreach ($c in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\go-ios\ios.exe'),
        'C:\tools\go-ios\ios.exe',
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ios.exe')
    )) { if (Test-Path -LiteralPath $c) { $iosExe = $c; break } }
}
if ($iosExe) {
    Ok ('ios.exe = ' + $iosExe)
    Run $iosExe @('version')
    $dll = Join-Path (Split-Path -Parent $iosExe) 'wintun.dll'
    if (Test-Path -LiteralPath $dll) {
        Ok ('wintun.dll present -> kernel tunnel mode is possible')
    } else {
        Warn2 ('wintun.dll MISSING next to ios.exe')
        Info  'Without it the kernel tunnel fails with:'
        Info  '  "Error loading wintun.dll DLL: The specified module could not be found."'
        Info  '=> you MUST start the tunnel with --userspace'
    }
} else {
    Bad 'ios.exe not found'; Info 'winget install --id danielpaulus.go-ios-agent -e'
}

# ------------------------------------------------------- 2) stale ios processes
Section '2/7 all running ios.exe processes (stale ones steal port 60105)'
$procs = @(Get-Process ios -ErrorAction SilentlyContinue)
if ($procs.Count -eq 0) {
    Ok 'no ios.exe running'
} else {
    foreach ($p in $procs) {
        Warn2 ('pid=' + $p.Id + ' started=' + $p.StartTime + ' path=' + $p.Path)
    }
    if ($KillStale) {
        Info 'killing them all (-KillStale) ...'
        $procs | Stop-Process -Force
        Start-Sleep -Seconds 2
        Ok ('remaining: ' + @(Get-Process ios -ErrorAction SilentlyContinue).Count)
    } else {
        Info 're-run with -KillStale to terminate them'
    }
}

# ------------------------------------------------------------------ 3) ports
Section '3/7 ports 60105 (tunnel) / 8100 (forward) / 27015 (agent)'
foreach ($port in @(60105, $WdaPort, 27015)) {
    $owners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -gt 0) {
        $desc = @()
        foreach ($o in $owners) {
            $pp = Get-Process -Id $o -ErrorAction SilentlyContinue
            $desc += ($o.ToString() + ':' + $pp.ProcessName + '@' + $pp.StartTime)
        }
        Ok ('port ' + $port + ' LISTENING -> ' + ($desc -join ', '))
    } else {
        if ($port -eq 27015) { Info 'port 27015 not listening (normal - agent starts on demand)' }
        else { Bad ('port ' + $port + ' NOT listening') }
    }
}

# ------------------------------------------------------------- 4) device list
Section '4/7 ios list  (USB/lockdown path - does NOT need a tunnel)'
if ($iosExe) {
    # First call often comes back EMPTY while the agent cold-starts. Never
    # treat a single empty answer as a verdict - always try twice.
    for ($i = 1; $i -le 2; $i++) {
        $out = Run $iosExe @('list')
        if ($out -match '\{"deviceList":\s*\[\s*\]\}') {
            Warn2 ('attempt ' + $i + ': deviceList is EMPTY')
        } elseif ($out -match '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}') {
            Ok ('attempt ' + $i + ': UDID visible')
            break
        } else {
            Warn2 ('attempt ' + $i + ': unrecognised answer')
        }
        Start-Sleep -Seconds 3
    }
}

# ------------------------------------------------- 5) THE KEY TEST: ios apps
Section '5/7 ios apps  (TUNNEL path - this is the one that fails)'
if ($iosExe) {
    for ($i = 1; $i -le 2; $i++) {
        Write-Host ('  -- attempt ' + $i) -ForegroundColor DarkGray
        $out = Run $iosExe @('apps', ('--udid=' + $Udid))
        if ($out -match 'Device .* not found') {
            Bad 'tunnel has NO device context (this is the "list works, apps fails" case)'
        } elseif ($out -match 'failed getting device list|actively refused') {
            Bad 'the go-iOS agent is not reachable on 27015'
        } elseif ($out -match 'CFBundleIdentifier') {
            $n = ([regex]::Matches($out, 'CFBundleIdentifier')).Count
            Ok ('tunnel is HEALTHY - enumerated ' + $n + ' apps')
            break
        } else {
            Warn2 'unexpected output (see above)'
        }
        Start-Sleep -Seconds 3
    }
}

# ------------------------------------------------------------ 6) tunnel start
Section '6/7 tunnel start (launch ONCE and keep the window open)'
if ($StartTunnel -and $iosExe) {
    Info 'set ENABLE_GO_IOS_AGENT=user and pass --userspace (wintun.dll fallback)'
    $env:ENABLE_GO_IOS_AGENT = 'user'
    Info 'starting in a NEW window so it keeps running ...'
    Start-Process -FilePath $iosExe -ArgumentList @('tunnel', 'start', ('--udid=' + $Udid), '--userspace')
    Info 'watch that new window: a healthy start ends with "Tunnel server started"'
    Info 'and must NOT be followed by "failed to start tunnel server ... 60105"'
} else {
    Info 'not started here. Do it manually (keep the window OPEN):'
    Info ('  $env:ENABLE_GO_IOS_AGENT = ''user''')
    Info ('  ' + $iosExe + ' tunnel start --udid=' + $Udid + ' --userspace')
    Info 'A stale process holding 60105 makes this fail with "Only one usage".'
}

# -------------------------------------------------------------------- 7) WDA
Section ('7/7 WDA http://127.0.0.1:' + $WdaPort + '/status')
try {
    $r = Invoke-WebRequest -Uri ('http://127.0.0.1:' + $WdaPort + '/status') -TimeoutSec 6 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Ok 'WDA answers'
        $j = $r.Content | ConvertFrom-Json
        Info ('ready=' + $j.value.ready + ' state=' + $j.value.state + ' device=' + $j.value.device)
    }
} catch {
    Warn2 ('no WDA on 8100: ' + $_.Exception.Message)
    Info 'Expected until runwda succeeds - the tunnel must be healthy FIRST.'
}

Write-Host ''
Write-Host '================================================='
Write-Host ' ORDER THAT MATTERS (each step needs the one before it):'
Write-Host '   1. no stale ios.exe        -> -KillStale'
Write-Host '   2. 60105 free              -> check section 3'
Write-Host '   3. ios list shows the UDID -> section 4 (may need 2 tries)'
Write-Host '   4. tunnel start --userspace-> section 6, keep window OPEN'
Write-Host '   5. ios apps enumerates     -> section 5  <-- the gate for WDA'
Write-Host '   6. runwda + forward 8100   -> then WDA is up on 8100'
Write-Host '================================================='
Write-Host ''
Read-Host 'Press Enter to close'
