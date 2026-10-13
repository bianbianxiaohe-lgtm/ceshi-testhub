# Run the post-rebuild verification for the PRODUCTION backend image.
# Why: execute_command times out randomly; this runs detached and writes a log.
# Output: C:\TestHub\_verify_img_out.txt

$ErrorActionPreference = 'Continue'
$Out = 'C:\TestHub\_verify_img_out.txt'
Remove-Item $Out -ErrorAction SilentlyContinue

function Say($m) {
  $line = (Get-Date -Format 'HH:mm:ss') + " $m"
  Add-Content -Path $Out -Value $line -Encoding UTF8
}

Say '--- docker cp _verify_img.py ---'
docker cp C:\TestHub\scripts\_verify_img.py testhub-backend:/tmp/_verify_img.py 2>&1 | ForEach-Object { Say "  $_" }

Say '--- run inside container ---'
docker exec testhub-backend python /tmp/_verify_img.py 2>&1 | ForEach-Object { Say "  $_" }

Say '--- cat /tmp/_verify_img.txt ---'
docker exec testhub-backend cat /tmp/_verify_img.txt 2>&1 | ForEach-Object { Say "  $_" }

Say '--- container status ---'
docker ps --format '{{.Names}} | {{.Status}}' 2>&1 | Select-String testhub | ForEach-Object { Say "  $_" }

Say '--- image ---'
docker images --format '{{.Repository}}:{{.Tag}} | {{.ID}} | {{.CreatedSince}}' 2>&1 | Select-String 'testhub-backend' | ForEach-Object { Say "  $_" }

Say '=== DONE ==='
