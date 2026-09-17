# Detect installed WebDriverAgent bundle id(s) on the device.
# Prints candidates space-separated (best guess FIRST). Used by ios_wda_host.bat.
#
# Why needed: go-iOS only looks for the standard
#   com.facebook.WebDriverAgentRunner[.t].xctrunner
# but resigned WDA builds often use custom ids like
#   com.facebook.WebDriverAgentRunner.yl2.xctrunner
#   com.facebook.WebDriverAgentRunner1220.xctrunner
# so we must discover the real one from "ios apps".
#
# HISTORY (why this script got complicated - three separate incidents):
#   "ios apps" NEEDS a working USB tunnel (iOS 17+) AND a live go-iOS agent.
#   Right after "ios tunnel start" the agent is still starting up, so a single
#   enumeration attempt returns EMPTY and the caller fell back to a hard-coded
#   bundle id - which only happens to be right for ONE particular device.
#   Result: every device change ("t" -> "yl2" -> "t") broke the launcher.
#   Fixes below: (1) retry until the agent is up, (2) cache per UDID so we only
#   enumerate once per device, (3) return a CANDIDATE LIST so the caller can
#   try them in order instead of betting everything on one id.
#
# Output contract:
#   line 1 = space separated candidate bundle ids, most likely first
#   (nothing else - diagnostics go to stderr, the caller captures stdout)
# Kept ASCII-only on purpose (PowerShell 5.1 mangles BOM-less UTF-8).
param(
    [string]$udid,
    [int]$Retries = 6,
    [int]$DelaySec = 3,
    # Path to ios.exe. MUST be passed by the caller on machines where go-ios is
    # not on PATH (e.g. C:\tools\go-ios\ios.exe): this script used to call a
    # bare "ios", which then found nothing and made every WDA bundle id look
    # missing even though the tunnel was perfectly fine.
    [string]$iosExe = 'ios'
)

$ErrorActionPreference = 'SilentlyContinue'

# Resolve once: a real path if given, otherwise the bare command name.
$IOS = $iosExe
if (-not $IOS) { $IOS = 'ios' }
if ($IOS -ne 'ios' -and -not (Test-Path -LiteralPath $IOS)) {
    Write-Diag ('ios.exe not found at ' + $IOS + ' - falling back to bare "ios"')
    $IOS = 'ios'
}

function Write-Diag([string]$msg) {
    [Console]::Error.WriteLine('[wda] ' + $msg)
}

# ---- 0) per-device cache: enumerate once, reuse afterwards ----
# Cache file lines are "<udid>=<id1> <id2> ...". Deleting the file forces a rescan.
$cacheFile = Join-Path $env:USERPROFILE '.testhub\wda_bundle.txt'
if ($udid -and (Test-Path -LiteralPath $cacheFile)) {
    foreach ($line in (Get-Content -LiteralPath $cacheFile -Encoding UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -le 0) { continue }
        if ($t.Substring(0, $i).Trim() -eq $udid) {
            $cached = $t.Substring($i + 1).Trim()
            if ($cached) {
                Write-Diag ('cache hit for ' + $udid + ' -> ' + $cached)
                # Print ONE PER LINE: cmd splits "for ... in ('...')" on whitespace,
                # so a space separated list would be read as 6 separate lines and
                # collapsed into the LAST id (the standard one) - i.e. the cached
                # ".yl2" would be silently dropped and WDA would never start.
                foreach ($c in ($cached -split '\s+')) { if ($c) { $c } }
                exit 0
            }
        }
    }
}

function Get-WdaCandidates([string]$raw) {
    $ids = New-Object System.Collections.ArrayList

    # Preferred: identifiers that literally mention WebDriver
    foreach ($m in [regex]::Matches($raw, '"CFBundleIdentifier"\s*:\s*"(com\.[^"]*[Ww]eb[Dd]river[^"]*)"')) {
        $v = $m.Groups[1].Value
        if (-not $ids.Contains($v)) { [void]$ids.Add($v) }
    }
    # Also accept WDA builds whose id lacks the literal word "WebDriver"
    # (e.g. "com.xxx.Runner.xctrunner") when the payload clearly came from apps.
    if ($ids.Count -eq 0) {
        foreach ($m in [regex]::Matches($raw, '"CFBundleIdentifier"\s*:\s*"(com\.[^"]*[Rr]unner[^"]*xctrunner)"')) {
            $v = $m.Groups[1].Value
            if (-not $ids.Contains($v)) { [void]$ids.Add($v) }
        }
    }
    return $ids
}

# ---- 1) enumerate, retrying until the go-iOS agent has come up ----
# A cold agent can take several seconds; a single attempt is not a verdict.
$ids = @()
for ($attempt = 1; $attempt -le $Retries; $attempt++) {
    $raw = ''
    if ($udid) {
        $raw = (& ios apps --udid=$udid 2>&1 | Out-String)
    }
    if (-not $raw.Trim()) {
        $raw = (& ios apps 2>&1 | Out-String)
    }
    $ids = @(Get-WdaCandidates $raw)
    if ($ids.Count -gt 0) {
        Write-Diag ('attempt ' + $attempt + ': found ' + $ids.Count + ' candidate(s)')
        break
    }
    Write-Diag ('attempt ' + $attempt + '/' + $Retries + ': no candidates yet, waiting ' + $DelaySec + 's')
    if ($attempt -lt $Retries) { Start-Sleep -Seconds $DelaySec }
}

if ($ids.Count -eq 0) {
    Write-Diag 'enumeration failed after all retries (agent not ready / tunnel down).'
    # Return an empty line so the caller knows we tried but could not discover;
    # it will then fall back to its own candidate list + cache.
    ''
    exit 0
}

# ---- 2) write the per-device cache so we do not enumerate again ----
if ($udid) {
    try {
        $dir = Split-Path -Parent $cacheFile
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
        $lines = @()
        if (Test-Path -LiteralPath $cacheFile) {
            $lines = @(Get-Content -LiteralPath $cacheFile -Encoding UTF8 |
                Where-Object { $_.Trim() -and -not $_.Trim().StartsWith($udid + '=') })
        }
        $lines += ($udid + '=' + ($ids -join ' '))
        Set-Content -LiteralPath $cacheFile -Value $lines -Encoding UTF8
        Write-Diag ('cached for ' + $udid)
    }
    catch {
        Write-Diag ('cache write failed: ' + $_.Exception.Message)
    }
}

# One id per line on purpose - see the cache-hit comment above.
foreach ($id in $ids) { $id }


