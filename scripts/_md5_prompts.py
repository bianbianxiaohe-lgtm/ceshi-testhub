# -*- coding: utf-8 -*-
"""计算墨刀线提示词的两种口径 md5：bin(原始字节) / text(文本模式，\r\n归一为\n)。

用于更新 _verify_modao_prompts.py 与 rebuild_prod_backend.ps1 的期望表。
结果同时打印并写入 /tmp/_md5_prompts.txt（容器内）以便 docker cp 回传。
"""
import hashlib
import os
import sys

NAMES = [
    'p0_requirement_struct',
    'p1_module_split',
    'p2_testpoint_gen',
    'p3_case_gen',
    'p4_smoke_extract',
    'p5_risk_identify',
    'p6_pci_identify',
    'p7_merge_dedup',
    'p8_quality_check',
]

BASE = os.path.join('/app', 'apps', 'requirement_analysis', 'modao_skill', 'prompts')

lines = []
for n in NAMES:
    p = os.path.join(BASE, n + '.md')
    if not os.path.exists(p):
        lines.append(f'{n}: MISSING')
        continue
    with open(p, 'rb') as f:
        raw = f.read()
    bin_md5 = hashlib.md5(raw).hexdigest().upper()
    txt_md5 = hashlib.md5(raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')).hexdigest().upper()
    lines.append(f'{n}: bin={bin_md5} text={txt_md5}')

out = '\n'.join(lines)
print(out)
try:
    with open('/tmp/_md5_prompts.txt', 'w', encoding='utf-8') as f:
        f.write(out)
except Exception as e:
    sys.stderr.write(f'write failed: {e}\n')
