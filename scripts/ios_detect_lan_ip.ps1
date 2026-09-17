# Print this PC's LAN IPv4 address (nothing else). Used by ios_wda_host.bat.
#
# Why a separate script: an inline Get-NetIPAddress one-liner embedded in a
# .bat came back EMPTY on machines with virtual adapters (WSL / Hyper-V /
# Docker vEthernet), which made the launcher print "TestHub URL: http:// :8100"
# and register the iPhone with an empty wda_host - after that the TestHub
# server had no way to reach the phone.
#
# Resolution order (first hit wins):
#   1. a real physical NIC (skip loopback / APIPA / virtual adapters)
#   2. the NIC that owns the default route - the one the server must reach
#   3. the first IPv4 found in "ipconfig" output
#
# ASCII-only, CRLF.

$ErrorActionPreference = 'SilentlyContinue'

$skipAlias = 'Loopback|WSL|Hyper-V|VirtualBox|VMware|vEthernet|Docker|Bluetooth|Teredo|isatap'

function Test-UsableIp {
    param([string]$Ip)
    if (-not $Ip) { return $false }
    if ($Ip -like '127.*') { return $false }
    if ($Ip -like '169.254.*') { return $false }
    return $true
}

$ip = ''

# 1) physical NIC
foreach ($a in (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
    if (-not (Test-UsableIp $a.IPAddress)) { continue }
    if ($a.InterfaceAlias -match $skipAlias) { continue }
    $ip = $a.IPAddress
    break
}

# 2) NIC owning the default route
if (-not $ip) {
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric | Select-Object -First 1
    if ($route) {
        foreach ($a in (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
            if (Test-UsableIp $a.IPAddress) { $ip = $a.IPAddress; break }
        }
    }
}

# 3) ipconfig fallback
if (-not $ip) {
    $text = (& ipconfig) -join "`n"
    foreach ($m in [regex]::Matches($text, '([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})')) {
        if (Test-UsableIp $m.Groups[1].Value) { $ip = $m.Groups[1].Value; break }
    }
}

# 4) if only virtual adapters exist, accept one of them rather than nothing
if (-not $ip) {
    foreach ($a in (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
        if (Test-UsableIp $a.IPAddress) { $ip = $a.IPAddress; break }
    }
}

Write-Output $ip
