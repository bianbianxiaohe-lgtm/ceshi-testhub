<#
 Kill whatever is listening on the given TCP ports, then wait until the ports
 are actually free.

 Called by ios_wda_host.bat for the two leftover services (60105 tunnel and
 8100 forward). It exists as a FILE rather than an inline
 "powershell -Command ..." because a long inline command is full of special
 characters, and cmd has been observed to mis-tokenise it on some machines -
 which then surfaced as a bogus "then was not expected at this time" on the
 NEXT line of the .bat. Keeping the cmd-side invocation short and boring
 removes that whole class of failure.

 ASCII-only, CRLF. Prints one line per action so the .bat output stays useful.
#>
param(
    # NOTE: deliberately typed [string], not [int[]].
    # cmd passes "-Ports 60105,8100" and depending on the calling convention
    # PowerShell may bind the whole thing as ONE int (601058100) instead of a
    # two-element array, which silently leaked garbage into the output. Parsing
    # the string ourselves is predictable on every host.
    [string]$Ports = '60105',
    [int]$Timeout = 20
)

$ErrorActionPreference = 'SilentlyContinue'

# normalise "60105,8100" / "60105 8100" / "60105" -> int[]
$PortList = @(
    ($Ports -split '[,;\s]+') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -match '^\d+$' } |
        ForEach-Object { [int]$_ }
)
if ($PortList.Count -eq 0) { $PortList = @(60105) }

function Get-ListenerPids([int]$port) {
    @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique) | Where-Object { $_ -ne 0 }
}

foreach ($port in $Ports) {
    foreach ($procId in (Get-ListenerPids $port)) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host ('        released PID ' + $procId + ' on port ' + $port)
        }
        catch {
            Write-Host ('        could not release PID ' + $procId + ' on port ' + $port + ' : ' + $_.Exception.Message)
        }
    }
}

$waited = 0
while ($waited -lt $Timeout) {
    $busy = 0
    foreach ($port in $Ports) {
        if ((Get-ListenerPids $port).Count -gt 0) { $busy++ }
    }
    if ($busy -eq 0) {
        # Report which ports we actually handled. Note: cmd passes
        # "-Ports 60105,8100" and PowerShell binds that to the int[] array
        # correctly, so use the real list rather than guessing from Count.
        Write-Host ('        ports released: ' + (($Ports | ForEach-Object { $_ }) -join ', ') + ' [after ' + $waited + 's]')
        exit 0
    }
    Start-Sleep -Seconds 2
    $waited += 2
}

Write-Host ('        ports still busy after ' + $Timeout + 's [continuing anyway]')
exit 0
