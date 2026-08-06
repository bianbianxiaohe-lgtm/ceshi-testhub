param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$template = Join-Path $ProjectRoot ".env.dev.example"
$target = Join-Path $ProjectRoot ".env.dev"

if (-not (Test-Path -LiteralPath $template)) {
    throw "Missing template: $template"
}
if (Test-Path -LiteralPath $target) {
    Write-Host ".env.dev already exists; no changes made."
    exit 0
}

function New-RandomSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).Replace("+", "A").Replace("/", "B").TrimEnd("=")
}

$content = Get-Content -LiteralPath $template -Raw -Encoding UTF8
$content = $content.Replace("SECRET_KEY=GENERATED_BY_INIT_SCRIPT", "SECRET_KEY=$(New-RandomSecret 48)")
$content = $content.Replace("MYSQL_ROOT_PASSWORD=GENERATED_BY_INIT_SCRIPT", "MYSQL_ROOT_PASSWORD=$(New-RandomSecret 32)")
$dbPassword = New-RandomSecret 32
$content = $content.Replace("MYSQL_PASSWORD=GENERATED_BY_INIT_SCRIPT", "MYSQL_PASSWORD=$dbPassword")
$content = $content.Replace("DB_PASSWORD=GENERATED_BY_INIT_SCRIPT", "DB_PASSWORD=$dbPassword")
[IO.File]::WriteAllText($target, $content, [Text.UTF8Encoding]::new($false))
Write-Host "Created .env.dev with generated development-only secrets."
