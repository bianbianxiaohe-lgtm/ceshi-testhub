#!/bin/sh
# 提示词 + zentao services 同步：先备份，再解包，最后打 md5 供核对
set -e

mkdir -p /tmp/rollback_prompts_$(date +%Y%m%d)
RB=$(ls -d /tmp/rollback_prompts_* | tail -n 1)

cp -f /app/tester.md "$RB/" 2>/dev/null || true
cp -f /app/tester_pro.md "$RB/" 2>/dev/null || true
cp -f /app/apps/requirement_analysis/independent_skill/prompts/tester.md "$RB/prompts_tester.md" 2>/dev/null || true
cp -f /app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md "$RB/prompts_tester_pro.md" 2>/dev/null || true
cp -f /app/apps/zentao/services.py "$RB/services.py" 2>/dev/null || true

tar -xf /tmp/_p.tar -C /app

find /app -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "rollback_dir=$RB"
md5sum /app/tester.md /app/tester_pro.md \
  /app/apps/requirement_analysis/independent_skill/prompts/tester.md \
  /app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md \
  /app/apps/zentao/services.py
