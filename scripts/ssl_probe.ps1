<#
 Show WHO is intercepting HTTPS on this machine.

 Symptom this diagnoses: "ios image auto" fails to mount the Developer Disk Image with
     failed to get signature from Apple: Post "https://gs.apple.com/TSS/controller?action=2":
     tls: failed to verify certificate: x509: certificate signed by unknown authority
 and curl shows
     schannel: SEC_E_UNTRUSTED_ROOT (0x80090325)

 That means something between this PC and Apple is terminating TLS and re-signing it.
 This script prints the issuer of the certificate that is actually presented, which
 normally names the culprit (a corporate SSL-inspection gateway, or an antivirus
 HTTPS scanner). It also lists non-mainstream root CAs installed on the machine.

 Read-only. ASCII-only, CRLF. Run as Administrator for the full root store listing.
#>

$ErrorActionPreference = 'SilentlyContinue'
$Target = 'https://gs.apple.com/TSS/controller?action=2'

function Section([string]$t) { Write-Host ''; Write-Host ('==== ' + $t + ' ====') -ForegroundColor Cyan }
function Info([string]$t) { Write-Host ('  ' + $t) }

Write-Host '================================================='
Write-Host ' TestHub - HTTPS interception probe'
Write-Host (' time  : ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host (' target: ' + $Target)
Write-Host '================================================='

# ---------------------------------------------------- 1) what cert is presented
Section '1/3 certificate actually presented by gs.apple.com'

$captured = $null
try {
    # Accept everything ON PURPOSE - we want to SEE the interceptor's certificate,
    # not fail on it.
    [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $req = [Net.HttpWebRequest]::Create($Target)
    $req.Timeout = 12000
    $req.UserAgent = 'testhub-ssl-probe'

    try { $resp = $req.GetResponse(); Info ('HTTP ' + [int]$resp.StatusCode); $resp.Close() }
    catch { Info ('request error (expected): ' + $_.Exception.Message) }

    $captured = $req.ServicePoint.Certificate
} catch {
    Info ('probe failed: ' + $_.Exception.Message)
}

if ($captured) {
    Info ''
    Info ('Subject : ' + $captured.Subject)
    Info ('Issuer  : ' + $captured.Issuer)
    Info ''
    if ($captured.Issuer -match 'Apple') {
        Write-Host '  RESULT: certificate looks like the REAL Apple certificate.' -ForegroundColor Green
        Info 'The problem is most likely a missing/expired root CA in the local store,'
        Info 'not an interception proxy.'
    } else {
        Write-Host '  RESULT: the issuer is NOT Apple -> TLS is being INTERCEPTED.' -ForegroundColor Red
        Info ('Interceptor identity is in the Issuer field above: ' + $captured.Issuer)
    }
} else {
    Write-Host '  RESULT: could not capture a certificate (connection blocked before TLS?).' -ForegroundColor Yellow
}

# ------------------------------------------------------------ 2) proxy settings
Section '2/3 proxy configuration'
$w = (netsh winhttp show proxy 2>&1 | Out-String)
foreach ($l in ($w -split "`r?`n")) { if ($l.Trim()) { Info $l.Trim() } }
$ie = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
Info ('IE ProxyEnable   = ' + $ie.ProxyEnable)
Info ('IE ProxyServer   = ' + $ie.ProxyServer)
Info ('IE AutoConfigURL = ' + $ie.AutoConfigURL)
if (-not $ie.ProxyServer -and -not $ie.AutoConfigURL) {
    Info 'No user-level proxy: interception (if any) happens at the GATEWAY/firewall,'
    Info 'not via a Windows proxy setting. A proxy setting change will NOT help.'
}

# ------------------------------------------------- 3) non-mainstream root CAs
Section '3/3 non-mainstream root CAs in the machine store'
$known = 'Microsoft|VeriSign|DigiCert|GlobalSign|Baltimore|Entrust|Sectigo|COMODO|Symantec|Apple|Thawte|GeoTrust|Go Daddy|USERTrust|ISRG|Certum|QuoVadis|D-TRUST|T-Systems|SwissSign|Actalis|Buypass|Hongkong|SecureTrust|XRamp|Starfield|Amazon|Google Trust|Let''s Encrypt|AAA Certificate|Network Solutions|AffirmTrust'
$roots = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
    Where-Object { $_.Issuer -notmatch $known }
if (-not $roots) {
    Info 'none found - no obvious interception CA installed.'
} else {
    Write-Host ('  Found ' + @($roots).Count + ' candidate(s):') -ForegroundColor Yellow
    foreach ($c in $roots) {
        Info ''
        Info ('Subject : ' + $c.Subject)
        Info ('Issuer  : ' + $c.Issuer)
        Info ('Expires : ' + $c.NotAfter)
    }
    Info ''
    Info 'If one of the above is your company / antivirus vendor, THAT is the'
    Info 'interceptor. Fix it by either:'
    Info '  * switching that product''s "HTTPS scanning" off, or'
    Info '  * getting ITS root CA trusted (ask IT), or'
    Info '  * using a completely different network (phone hotspot / 4G dongle).'
}

Write-Host ''
Write-Host '================================================='
Write-Host ' Bottom line: mounting a Developer Disk Image requires talking to'
Write-Host ' gs.apple.com over real TLS. If TLS is intercepted here, "ios image auto"'
Write-Host ' CANNOT succeed on this network - no script change can work around it.'
Write-Host ' Devices that ALREADY have a DDI mounted (see "already a developer image'
Write-Host ' mounted" in the log) are unaffected, because they never re-sign.'
Write-Host '================================================='
Write-Host ''
Read-Host 'Press Enter to close'
