# 墨刀线新旧提示词对比 —— 触发重跑（dev）
# 用法: powershell -File scripts\_modao_rerun.ps1 design
#       powershell -File scripts\_modao_rerun.ps1 cases
$ErrorActionPreference = 'Continue'
$step = if ($args.Count -gt 0) { $args[0] } else { 'design' }

$base  = 'http://localhost:18000'
$proto = 65
$page  = 722
$out   = 'C:\TestHub\tmp\modao_rerun_20261013'

# ---------- 登录 ----------
$loginBody = '{"username":"admin","password":"admin123"}'
$lr = Invoke-RestMethod -Uri "$base/api/auth/login/" -Method Post -Body $loginBody -ContentType 'application/json'
$token = $null
foreach ($k in 'access', 'token') {
    if ($lr.PSObject.Properties.Name -contains $k) { $token = $lr.$k; break }
}
if (-not $token -and $lr.data) {
    foreach ($k in 'access', 'token') {
        if ($lr.data.PSObject.Properties.Name -contains $k) { $token = $lr.data.$k; break }
    }
}
if (-not $token) {
    "LOGIN_FAIL: $($lr | ConvertTo-Json -Compress -Depth 5)"
    exit 1
}
"TOKEN_OK len=$($token.Length)"

$hdr = @{ 'Authorization' = "Bearer $token" }

# ---------- 触发 ----------
if ($step -eq 'design') {
    $uri  = "$base/api/requirement-analysis/api/modao/$proto/design/"
    $body = "{`"page_ids`":[$page]}"
} else {
    $uri  = "$base/api/requirement-analysis/api/modao/$proto/generate-cases/"
    $body = "{`"page_ids`":[$page]}"
}

try {
    $r = Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType 'application/json' -Headers $hdr
    "TRIGGER_OK $step"
    ($r | ConvertTo-Json -Depth 6)
} catch {
    "TRIGGER_FAIL $step"
    $_.Exception.Message
    if ($_.ErrorDetails.Message) { "BODY: " + $_.ErrorDetails.Message }
}
