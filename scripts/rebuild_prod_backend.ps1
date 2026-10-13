# Rebuild TestHub PRODUCTION backend image.
# Root fix for: docker-cp'ed .py files are lost whenever the container is recreated,
# because /app/apps is NOT a bind mount (code comes from the image only).
#
# Usage:  powershell -ExecutionPolicy Bypass -File C:\TestHub\scripts\rebuild_prod_backend.ps1
# Notes:  ASCII only, CRLF required. Stops immediately on the first failed step.

$ErrorActionPreference = 'Stop'
$Repo = 'C:\TestHub'
$LogDir = Join-Path $Repo 'logs'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$Log = Join-Path $LogDir "rebuild_prod_$Stamp.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Say($m) {
  $t = Get-Date -Format 'HH:mm:ss'
  $line = "$t $m"
  Write-Output $line
  Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Fail($m) {
  Say "FATAL: $m"
  Say '=== ABORTED, no further step executed ==='
  exit 1
}

Say '=== STEP 0 precheck ==='
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'docker command not found' }
Set-Location $Repo
Say "repo=$Repo"

Say '--- baseline md5 (prod modao_workflow.py) ---'
docker exec testhub-backend md5sum /app/apps/requirement_analysis/modao_workflow.py
Say "baseline_exit=$LASTEXITCODE"

Say '--- baseline md5 (2026-10-13 prompt + zentao coverage fix) ---'
docker exec testhub-backend md5sum /app/tester.md /app/tester_pro.md /app/apps/requirement_analysis/independent_skill/prompts/tester.md /app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md /app/apps/zentao/services.py

Say '--- recent modao tasks ---'
docker exec testhub-backend python -c "import os,sys,django;sys.path.insert(0,'/app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');django.setup();from apps.requirement_analysis.models import ModaoPrototype;print(ModaoPrototype.objects.filter(status__in=['running','processing','extracting']).count());print(list(ModaoPrototype.objects.order_by('-id').values_list('id','status','current_stage')[:3]))"

Say '=== STEP 1 backup ==='
$bk = "/tmp/rollback_$Stamp"
docker exec testhub-backend mkdir -p $bk
if ($LASTEXITCODE -ne 0) { Fail 'mkdir backup dir failed' }
docker exec testhub-backend tar -czf "$bk/apps.tar.gz" -C /app apps backend
if ($LASTEXITCODE -ne 0) { Fail 'tar backup failed' }
Say "container backup -> $bk/apps.tar.gz"

$mp = (docker exec testhub-mysql printenv MYSQL_ROOT_PASSWORD).Trim()
Say "mysql root password length=$($mp.Length)"
docker exec testhub-mysql mysqldump -uroot "-p$mp" --result-file=/tmp/testhub_dump.sql testhub
if ($LASTEXITCODE -ne 0) { Fail 'mysqldump failed' }
$dumpDir = Join-Path $Repo '_db_backup'
if (-not (Test-Path $dumpDir)) { New-Item -ItemType Directory -Path $dumpDir -Force | Out-Null }
docker cp testhub-mysql:/tmp/testhub_dump.sql (Join-Path $dumpDir "testhub_$Stamp.sql")
Say "db dump -> $dumpDir\testhub_$Stamp.sql"

Say '=== STEP 2 docker compose build backend (40-70 min, no --no-cache) ==='
# 2026-10-10: build output MUST be captured. Previously it went to the (hidden) console only,
# so two consecutive pip failures left us with no error text at all and cost ~2h of guessing.
$BuildLog = Join-Path $LogDir "build_$Stamp.log"
Say "build output -> $BuildLog"
docker compose build backend *> $BuildLog
$buildRc = $LASTEXITCODE
Say "build exit=$buildRc ; tail of build log:"
if (Test-Path $BuildLog) {
  $tail = Get-Content -Path $BuildLog -Tail 40
  Add-Content -Path $Log -Value $tail -Encoding UTF8
}
if ($buildRc -ne 0) { Fail "build failed (exit $buildRc), full output in $BuildLog" }
Say 'build OK'

Say '=== STEP 3 recreate container ==='
docker rm -f testhub-backend
if ($LASTEXITCODE -ne 0) { Fail 'rm container failed' }
docker compose up -d backend
if ($LASTEXITCODE -ne 0) { Fail 'up -d failed' }
Say 'container recreated, waiting 35s'
Start-Sleep -Seconds 35

Say '=== STEP 4 verify ==='
$code = curl.exe -s -o NUL -w '%{http_code}' http://localhost:8000/api/
Say "GET /api/ -> $code   (expect 404 = healthy, 000 = process dead)"
if ($code -ne '404') { Fail "health check returned $code" }

Say '--- modao_workflow.py ---'
docker exec testhub-backend md5sum /app/apps/requirement_analysis/modao_workflow.py
docker exec testhub-backend wc -l /app/apps/requirement_analysis/modao_workflow.py
docker exec testhub-backend grep -c vision_scope /app/apps/requirement_analysis/modao_workflow.py

Say '--- modao_extractor.py ---'
docker exec testhub-backend md5sum /app/apps/requirement_analysis/modao_extractor.py
docker exec testhub-backend wc -l /app/apps/requirement_analysis/modao_extractor.py

Say '--- playwright chromium (its install is wrapped in || echo, so failure is SILENT) ---'
# 2026-10-10: must run through sh -c; docker exec does NOT expand globs, so a bare
# `ls -d .../chromium*` always exits 2 (false alarm). Also print the binary version.
docker exec testhub-backend sh -c "ls -d /root/.cache/ms-playwright/chromium*/chrome-linux64 && /root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --version"
if ($LASTEXITCODE -ne 0) { Fail "chromium MISSING in image (exit $LASTEXITCODE), modao reading will break" }
Say 'chromium check OK'

Say '--- files that were missing on prod ---'
docker exec testhub-backend ls -la /app/apps/ui_automation/element_provider.py
docker exec testhub-backend ls -la /app/apps/ui_automation/element_picker_views.py
docker exec testhub-backend ls -la /app/apps/projects/migrations/0009_projectrole_project_role.py
docker exec testhub-backend ls -la /app/apps/ui_automation/migrations/0015_aiexecutionrecord_replay_degraded.py

$roles = curl.exe -s -o NUL -w '%{http_code}' http://localhost:8000/api/projects/roles/
Say "GET /api/projects/roles/ -> $roles   (expect 401 = route exists, 404 = still old code)"

Say '=== STEP 5 verify 2026-10-13 prompt + zentao coverage fix ==='
# Expected md5 = host files via: Get-FileHash <file> -Algorithm MD5
# If a host file changes on purpose, update the hash below in the same commit.
$Expect = @{
  '/app/tester.md'                                                        = 'B929122FFFC6E4D224279E2AF087215F';
  '/app/tester_pro.md'                                                    = '147696BB6324666F7005FB50971AB56D';
  '/app/apps/requirement_analysis/independent_skill/prompts/tester.md'     = 'ABFDD8548E5B852C3143F844EED62764';
  '/app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md' = 'FAF9D37D6361CD1A7C1F9089A40A433E';
  '/app/apps/zentao/services.py'                                          = '7FBAD39D20E81331E890FCC63F3A5E61'
}
$md5Raw = docker exec testhub-backend md5sum /app/tester.md /app/tester_pro.md /app/apps/requirement_analysis/independent_skill/prompts/tester.md /app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md /app/apps/zentao/services.py
$md5Bad = 0
foreach ($line in $md5Raw) {
  $parts = ($line -split '\s+') | Where-Object { $_ -ne '' }
  if ($parts.Count -lt 2) { continue }
  $h = $parts[0].ToUpper(); $f = $parts[1]
  if (-not $Expect.ContainsKey($f)) { Say "MD5 UNKNOWN-PATH $f = $h"; continue }
  if ($Expect[$f] -eq $h) { Say "MD5 OK   $f = $h" }
  else { Say "MD5 MISMATCH $f : image=$h expected=$($Expect[$f])"; $md5Bad++ }
}
if ($md5Bad -gt 0) { Fail "$md5Bad file(s) did NOT make it into the image" }
Say 'all 5 md5 match -> prompts + zentao/services.py are baked into the image'

Say '--- runtime constants loaded by the rebuilt image (expect 600 / 600 / 0.0) ---'
docker exec testhub-backend python -c "import os,sys;sys.path.insert(0,'/app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');import django;django.setup();from apps.zentao import services as s;print('JUDGE_CASE_CHARS=%s'%s.JUDGE_CASE_CHARS);print('JUDGE_BUG_CHARS=%s'%s.JUDGE_BUG_CHARS);print('JUDGE_TEMPERATURE=%s'%s.JUDGE_TEMPERATURE)"
if ($LASTEXITCODE -ne 0) { Fail 'failed to read JUDGE_* constants from apps.zentao.services' }

Say '--- PromptConfig lengths (expect writer 3089 / reviewer 1012 / analyzer 1466-custom) ---'
docker exec testhub-backend python -c "import os,sys;sys.path.insert(0,'/app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');import django;django.setup();from apps.requirement_analysis.models import PromptConfig;[print('%s len=%d'%(p.prompt_type,len(p.content or ''))) for p in PromptConfig.objects.filter(is_active=True).order_by('prompt_type')]"

Say '--- cross-version knowledge entries (expect >= 16 after report#29 promote) ---'
docker exec testhub-backend python -c "import os,sys;sys.path.insert(0,'/app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');import django;django.setup();from apps.projects.models import ProjectKnowledge;print('global=%d'%ProjectKnowledge.objects.filter(version__isnull=True).count());print('confirmed=%d'%ProjectKnowledge.objects.filter(needs_review=False).count())"

Say '=== DONE ==='
Say "log file = $Log"
