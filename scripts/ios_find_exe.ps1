# Locate go-ios' ios.exe. Prints the result (a path, or the bare word "ios")
# and nothing else, so the caller can do:
#     for /f "delims=" %%i in ('powershell ... ios_find_exe.ps1') do set "IOS_EXE=%%i"
#
# Why this exists (2026-09-15): the launcher used to rely on "where ios" and
# then a short list of fixed folders. On a PC that HAS go-ios but never added
# it to PATH, "where ios" prints "Could not find files for the given pattern(s)"
# (it also searches for ios.ps1/ios.cmd), so the launcher aborted with a
# misleading "[ERROR] ios.exe not found [go-ios missing or not on PATH]" even
# though ios.exe was sitting in C:\tools\go-ios\. This script is stricter and
# much more thorough.
#
# Search order (first hit wins). Nothing is written to stdout except the answer;
# diagnostics go to stderr so they never pollute the value the caller reads.
#
# ASCII-only, CRLF.

$ErrorActionPreference = 'SilentlyContinue'

function Write-Diag([string]$msg) {
    [Console]::Error.WriteLine('[find] ' + $msg)
}

# ---- 0) explicit override file, so an unusual install can be pinned ----
$overrideFile = Join-Path $env:USERPROFILE '.testhub\ios_exe.txt'
if (Test-Path -LiteralPath $overrideFile) {
    $p = (Get-Content -LiteralPath $overrideFile -TotalCount 1).Trim()
    if ($p -and (Test-Path -LiteralPath $p)) {
        Write-Diag ('using override file -> ' + $p)
        $p
        exit 0
    }
    Write-Diag ('override file exists but path is not usable: ' + $p)
}

# ---- 1) already on PATH ----
# Use the application view, not "where": we only want real executables.
foreach ($name in @('ios.exe', 'ios')) {
    $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($cmd -and $cmd.Source) {
        Write-Diag ('found on PATH -> ' + $cmd.Source)
        $cmd.Source
        exit 0
    }
}

# ---- 2) well-known install locations ----
$candidates = @(
    (Join-Path $PSScriptRoot 'ios.exe'),
    (Join-Path $PSScriptRoot '..\ios.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\go-ios\ios.exe'),
    (Join-Path $env:LOCALAPPDATA 'go-ios\ios.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ios.exe'),
    (Join-Path $env:ProgramFiles 'go-ios\ios.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'go-ios\ios.exe'),
    (Join-Path $env:USERPROFILE 'go-ios\ios.exe'),
    (Join-Path $env:USERPROFILE 'scoop\shims\ios.exe'),
    'C:\tools\go-ios\ios.exe',
    'C:\go-ios\ios.exe',
    'C:\ProgramData\chocolatey\bin\ios.exe',
    'D:\tools\go-ios\ios.exe',
    'D:\go-ios\ios.exe'
)
foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) {
        Write-Diag ('found in a standard folder -> ' + $c)
        # Get-Item resolves to the full path so the caller always gets an absolute path
        (Get-Item -LiteralPath $c).FullName
        exit 0
    }
}

# ---- 3) scan the drives the machine actually has (bounded depth) ----
# Catches "I unzipped it into Downloads / Desktop / a project folder".
$roots = @()
foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null })) {
    if ($d.Root -match '^[A-Za-z]:\\$') { $roots += $d.Root }
}
$skip = 'Windows|ProgramData|node_modules|AppData'
$deadline = (Get-Date).AddSeconds(30)
foreach ($root in $roots) {
    if ((Get-Date) -gt $deadline) {
        Write-Diag 'scan deadline reached, stopping'
        break
    }
    Write-Diag ('scanning ' + $root)
    $hit = Get-ChildItem -LiteralPath $root -Filter 'ios.exe' -File -Recurse -Depth 4 -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch $skip } |
        Select-Object -First 1
    if ($hit) {
        Write-Diag ('found by scan -> ' + $hit.FullName)
        $hit.FullName
        exit 0
    }
}

Write-Diag 'ios.exe was not found anywhere'
exit 0
