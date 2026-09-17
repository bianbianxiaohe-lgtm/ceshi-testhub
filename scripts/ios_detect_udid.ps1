# Detect connected iOS device UDID(s) and print them space-separated.
# Used by ios_wda_host.bat. ASCII-only output.
#
# IMPORTANT: keep the UDID case EXACTLY as reported by the tool.
# go-iOS matches devices case-sensitively; lowercasing the UDID makes
# "ios tunnel start --udid=..." fail with "Device not found".
#
# DESIGN NOTES (learned the hard way):
# 1. stdout must contain ONLY the UDIDs (space separated). The caller reads it
#    with "for /f", which treats EVERY line as a candidate device - so any
#    hint/diagnostic printed to stdout shows up as a bogus "device".
#    => all diagnostics go to stderr via [Console]::Error.WriteLine().
# 2. "ios list" (JSON: {"deviceList":["<udid>"]}) is the reliable format and
#    is parsed with ConvertFrom-Json first.
# 3. The first "ios" call after a cleanup spawns the go-iOS agent and prints
#    warnings before the payload, so retry until a UDID is actually found -
#    never decide based on "is the output empty".
# 4. "--details" prints a TABLE whose header row contains the literal words
#    UDID / SerialNumber / NAME / ... - those must never be treated as ids.
# 5. Do NOT rely on $ErrorActionPreference = 'SilentlyContinue' to hide
#    problems: if "ios" cannot even be resolved, everything goes empty and
#    the caller just says "no device detected". Resolve the binary first and
#    report the exit code + both streams when nothing is found.
$ErrorActionPreference = 'Continue'

$UDID_PATTERN = '[0-9a-fA-F]{8}-[0-9a-fA-F]{16}|[0-9a-fA-F]{40}'
$BLOCKLIST = @('udid', 'serialnumber', 'name', 'marketname', 'productversion',
    'conntype', 'deviceid', 'devicename')

function Write-Diag {
    param([string]$Message)
    [Console]::Error.WriteLine('[detect] ' + $Message)
}

function Get-UdidsFromText {
    param([string]$Text)
    $found = @()
    $seen = @{}
    foreach ($line in ($Text -split "`r?`n")) {
        foreach ($m in [regex]::Matches($line, $UDID_PATTERN)) {
            $v = $m.Value
            $key = $v.ToLower()
            if ($BLOCKLIST -contains $key) { continue }
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                $found += $v
            }
        }
    }
    return $found
}

function Get-UdidsFromJson {
    param([string]$Text)
    $found = @()
    foreach ($m in [regex]::Matches($Text, '\{[^{}]*"deviceList"[^{}]*\}')) {
        try { $obj = $m.Value | ConvertFrom-Json } catch { continue }
        foreach ($d in $obj.deviceList) {
            $v = "$d"
            if ($v -match "^$UDID_PATTERN$") { $found += $v }
        }
    }
    return $found
}

# ---- 1) is the go-iOS binary reachable at all? ----
# Get-Command only sees PATH. A PC that has go-ios in a standard folder but
# never added it to PATH would otherwise be reported as "not installed", so
# fall back to the shared locator (same one ios_wda_host.bat uses).
$iosExe = $env:IOS_EXE
if (-not $iosExe -or -not (Test-Path -LiteralPath $iosExe)) {
    $iosExe = $null
    $found = Get-Command ios -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found -and $found.Source) {
        $iosExe = $found.Source
    }
    else {
        $finder = Join-Path $PSScriptRoot 'ios_find_exe.ps1'
        if (Test-Path -LiteralPath $finder) {
            $cand = (& powershell -NoProfile -ExecutionPolicy Bypass -File $finder |
                Select-Object -First 1)
            if ($cand -and (Test-Path -LiteralPath $cand)) { $iosExe = $cand }
        }
    }
}
if (-not $iosExe) {
    Write-Diag 'ERROR: go-ios [ios.exe] was not found on this computer.'
    Write-Diag '       Install it with:  winget install --id danielpaulus.go-ios-agent -e'
    Write-Diag '       Or drop ios.exe into C:\tools\go-ios\ , then run this again.'
    Write-Diag ('       PATH = ' + $env:PATH)
    exit 0
}
Write-Diag ('using ios binary: ' + $iosExe)

# ---- 2) query the device ----
$udids = @()
$raw = ''
$lastOut = ''
$lastErr = ''
$lastCode = -1

for ($attempt = 1; $attempt -le 3; $attempt++) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()

    # preference order: JSON (most reliable) -> table -> details table
    & $iosExe list > $outFile 2> $errFile
    $lastCode = $LASTEXITCODE
    $out = (Get-Content -Path $outFile -Raw -Encoding UTF8)
    $err = (Get-Content -Path $errFile -Raw -Encoding UTF8)
    Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue

    if (-not $out) { $out = '' }
    if (-not $err) { $err = '' }
    $lastOut = $out
    $lastErr = $err
    $raw += $out + "`n" + $err + "`n"

    $udids = Get-UdidsFromJson $out
    if ($udids.Count -eq 0) { $udids = Get-UdidsFromText ($out + "`n" + $err) }

    if ($udids.Count -eq 0) {
        Write-Diag ("attempt $attempt : exit=$lastCode  stdout=" +
            ($out.Trim().Length) + " chars  stderr=" + ($err.Trim().Length) + " chars")
        # keep these referenced so the diagnostic stays meaningful
        $null = $lastOut; $null = $lastErr
    }

    if ($udids.Count -gt 0) { break }
    if ($attempt -lt 3) { Start-Sleep -Seconds 4 }
}

if ($udids.Count -eq 0) {
    Write-Diag 'no UDID found. Raw output tail:'
    $tail = ($raw -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 10)
    if ($tail.Count -eq 0) { Write-Diag '  <both stdout and stderr were EMPTY>' }
    foreach ($line in $tail) { Write-Diag ('  ' + $line.Trim()) }
}

$udids -join ' '
