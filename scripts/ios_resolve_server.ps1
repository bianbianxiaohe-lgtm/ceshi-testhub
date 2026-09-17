<#
 Resolve the TestHub server address, verifying it actually answers.

 WHY THIS EXISTS
 ---------------
 The old flow read %USERPROFILE%\.testhub\server.txt and trusted it blindly.
 That works on the machine you first typed the address into, and breaks the
 moment you move to a NEW PC: if you copy the whole .testhub folder along
 (which is the natural thing to do), the new PC inherits the old address,
 never asks, and dies later with "unable to connect to the remote server".

 So the contract is now:
   1. try the cached address                     -> accept if it answers
   2. try the built-in default                   -> accept if it answers
   3. probe a few likely hosts on our own subnet -> accept if one answers
   4. otherwise ask the user, and only save what actually answered

 Step 3 is deliberately narrow. Sweeping a whole /24 (254 hosts) would take
 the better part of a minute even with a short timeout, and in practice the
 server sits on the same subnet as the phone host. We try the cached address's
 last octet, then a small list of common ones, then give up and ask.

 OUTPUT
 ------
 One line of plain text on stdout, so cmd's `for /f` can capture it:
   OK <url>      an address that answered /health or /api/
   ASK <reason>  nothing answered - the caller should prompt the user
 Anything else (diagnostics) goes to stderr, so it never pollutes the value.

 ASCII-only, CRLF (Windows PowerShell 5.1 / cmd safe).
#>

param(
    [string]$ServerUrl = '',
    [string]$DefaultUrl = 'http://192.168.8.75:18000',
    [int]$TimeoutSec = 3,
    [switch]$Verbose
)

$ErrorActionPreference = 'SilentlyContinue'

function Log([string]$m) {
    if ($Verbose) { [Console]::Error.WriteLine('  [resolve] ' + $m) }
}

# A server is "alive" if /health or /api/ answers at all.
# Note: the Django dev server returns 404 on /api/ (no route), and that still
# proves the host:port is a TestHub backend, so anything below 500 counts.
function Test-Server([string]$url) {
    if (-not $url) { return $false }
    $base = $url.TrimEnd('/')
    foreach ($path in @('/health', '/api/')) {
        try {
            $r = Invoke-WebRequest -Uri ($base + $path) -TimeoutSec $TimeoutSec `
                                   -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $true }
        } catch [System.Net.WebException] {
            # 404/401 come back as WebException on PS 5.1 - still means "alive"
            $resp = $_.Exception.Response
            if ($resp -and [int]$resp.StatusCode -lt 500) { return $true }
        } catch {
            # connection refused / timeout / DNS -> this address is no good
        }
    }
    return $false
}

function Get-Port([string]$url) {
    try { return ([uri]$url).Port } catch { return 18000 }
}

function Get-HostPart([string]$url) {
    try { return ([uri]$url).Host } catch { return '' }
}

function Get-EffectivePort([string]$url) {
    # [uri] gives -1 for an unspecified port; fall back to the scheme default
    $p = Get-Port $url
    if ($p -gt 0) { return $p }
    try { if (([uri]$url).Scheme -eq 'https') { return 443 } } catch { }
    return 80
}

# ---- step 1 + 2: cached address, then built-in default ----------------------
$candidates = New-Object System.Collections.ArrayList
if ($ServerUrl) { [void]$candidates.Add($ServerUrl.Trim()) }
if ($DefaultUrl -and $DefaultUrl.Trim() -ne ($ServerUrl.Trim())) {
    [void]$candidates.Add($DefaultUrl.Trim())
}

foreach ($c in $candidates) {
    Log ('trying ' + $c)
    if (Test-Server $c) { Write-Output ('OK ' + $c); exit 0 }
}

# ---- step 3: a few likely hosts on our own subnet ---------------------------
# Only worth doing for private 192.168.x.x / 10.x addresses. We reuse the port
# from the default URL (falling back to the cached one), and try the default's
# last octet first because that is usually the real server.
if ($DefaultUrl) { $port = Get-EffectivePort $DefaultUrl }
elseif ($ServerUrl) { $port = Get-EffectivePort $ServerUrl }
else { $port = 18000 }

# Which /24 are we on? Ask the LAN-IP helper the bat file already ships with.
$lanIp = ''
$helper = Join-Path $PSScriptRoot 'ios_detect_lan_ip.ps1'
if (Test-Path -LiteralPath $helper) {
    $lanIp = (& powershell -NoProfile -ExecutionPolicy Bypass -File $helper 2>&1 | Out-String).Trim()
}
Log ('our LAN ip = ' + $lanIp)

$prefix = ''
if ($lanIp -match '^(\d+\.\d+\.\d+)\.\d+$') { $prefix = $Matches[1] }
if ($prefix) {
    $lastOctets = New-Object System.Collections.ArrayList
    $defaultHost = Get-HostPart $DefaultUrl
    if ($defaultHost -match '\.(\d+)$') { [void]$lastOctets.Add($Matches[1]) }
    foreach ($o in @('75', '1', '100', '10', '2')) {
        if (-not $lastOctets.Contains($o)) { [void]$lastOctets.Add($o) }
    }
    foreach ($o in $lastOctets) {
        $url = 'http://' + $prefix + '.' + $o + ':' + $port
        if ($candidates.Contains($url)) { continue }
        Log ('probing ' + $url)
        if (Test-Server $url) { Write-Output ('OK ' + $url); exit 0 }
    }
}

# ---- step 4: nothing answered ----------------------------------------------
Write-Output 'ASK no-address-answered'
exit 1
