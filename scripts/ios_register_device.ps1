param(
    [string]$ServerUrl = '',
    [string]$Udid = '',
    [string]$WdaHost = '',
    [int]$WdaPort = 8100,
    [string]$Token = '',
    [string]$Status = 'online'
)

# Register / refresh this iPhone on TestHub.
# Called by ios_wda_host.bat (Status=online) right after WDA is up, and by
# ios_device_stop.bat (Status=offline) when the service is stopped.
#
# IDENTITY CONTRACT (must match the backend):
#   the UDID is the device's unique identity. The TestHub device list always
#   shows every device ever registered; reconnecting (even from another PC)
#   refreshes the SAME row - status + the latest host IP - and never creates
#   a duplicate. Records are never deleted.
#
# ASCII-ONLY OUTPUT ON PURPOSE: the caller is a .bat running under a legacy
# codepage, so any non-ASCII text would come out as mojibake.
#
# Why the LAN IP fallback: Get-NetIPAddress can come back empty on machines
# with virtual adapters (WSL / VMs / Hyper-V), which used to make the caller
# print "TestHub URL: http:// :8100" and register the device with an EMPTY
# wda_host - the platform then could not reach the phone at all.
# We now fall back to the IP of the interface that owns the default route,
# because that is the one the TestHub server must reach us on.
function Get-LanIp {
    # 1) "real" NIC that is up and is not loopback / virtual / APIPA
    try {
        $cand = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*' -and
                $_.PrefixOrigin -ne 'WellKnown' -and
                $_.InterfaceAlias -notmatch 'Loopback|WSL|Hyper-V|VirtualBox|VMware|vEthernet|Docker'
            } |
            Select-Object -First 1
        if ($cand) { return $cand.IPAddress }
    }
    catch { }

    # 2) interface that owns the default route (most likely the LAN NIC)
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Sort-Object RouteMetric | Select-Object -First 1
        if ($route) {
            $ip = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
                Select-Object -First 1
            if ($ip) { return $ip.IPAddress }
        }
    }
    catch { }

    # 3) last resort: ipconfig output
    try {
        $lines = (& ipconfig) -join "`n"
        $m = [regex]::Match($lines, 'IPv4[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)')
        if ($m.Success) { return $m.Groups[1].Value }
    }
    catch { }

    return ''
}

if (-not $ServerUrl) {
    Write-Host '  [skip] TESTHUB_URL is empty (device NOT registered)'
    exit 0
}
if (-not $Udid) {
    Write-Host '  [skip] no UDID, device NOT registered'
    exit 0
}

$isOnline = ($Status -ne 'offline')

# Caller normally passes the IP; resolve it here if it came through empty.
# Offline reports go out from a machine that may no longer be the one hosting
# the device, so never overwrite wda_host in that case.
if ($isOnline -and -not $WdaHost) {
    $WdaHost = Get-LanIp
    Write-Host ('  [info] caller did not supply the LAN IP, resolved locally: ' + $WdaHost)
}
if ($isOnline -and -not $WdaHost) {
    Write-Host '  [WARN] could not determine this PC LAN IP - register manually'
}

$version = ''
if ($isOnline -and $WdaHost) {
    try {
        $st = Invoke-RestMethod -Uri "http://$($WdaHost):$($WdaPort)/status" -TimeoutSec 5 -UseBasicParsing
        if ($st.value) { $version = $st.value.os.version }
    }
    catch {
        Write-Host '  [warn] could not read /status, registering without iOS version'
    }
}

$body = @{
    platform    = 'ios'
    udid        = $Udid
    wda_port    = $WdaPort
    device_type = 'real'
    status      = $Status
}
# Only a live report carries the host IP / version; an offline report must
# keep the address of the PC that actually hosts the phone.
if ($isOnline) {
    $body.wda_host = $WdaHost
    $body.platform_version = "$version"
    $body.notes = 'auto-registered by ios_wda_host.bat'
}
else {
    $body.notes = 'marked offline by ios_device_stop.bat'
}
$body = $body | ConvertTo-Json

$headers = @{}
if ($Token) { $headers['X-Device-Token'] = $Token }

$base = $ServerUrl.TrimEnd('/')
try {
    $r = Invoke-RestMethod -Uri "$base/api/ui-automation/device-agent/register/" `
        -Method Post -Body $body -ContentType 'application/json' `
        -Headers $headers -TimeoutSec 15
    if ($r.success) {
        # NOTE: the server returns a Chinese message, but this script runs under a
        # legacy OEM codepage, so printing $r.message came out as mojibake
        # (garbled CJK). Report in English instead and keep raw fields visible.
        $action = 'updated'
        if ($r.created) { $action = 'CREATED new' }
        elseif (-not $r.online) { $action = 'marked OFFLINE' }
        Write-Host ('  [OK] ' + $action + ' device on TestHub  (id=' + $r.data.id + ', status=' + $r.data.status + ')')
        Write-Host ('       name   = ' + $r.data.name)
        Write-Host ('       udid   = ' + $r.data.udid)
        if ($isOnline) {
            Write-Host ('       wda    = ' + $WdaHost + ':' + $WdaPort)
        }
    }
    else {
        Write-Host ('  [WARN] register rejected: ' + $r.message)
    }
}
catch {
    Write-Host ('  [WARN] register failed: ' + $_.Exception.Message)
    Write-Host '        (device still usable; add it manually in TestHub if needed)'
}
exit 0
