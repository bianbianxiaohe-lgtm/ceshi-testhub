# -*- coding: utf-8 -*-
"""核验画布 718 结构化结果：批注规则是否被吸收底/模 OCR 噪声是否被误当需求。"""
import re

summary = open('tmp/_p718_summary.txt', encoding='utf-8').read()

# A 组：批注中的真实业务规则（应被吸收）
A = ['BMI', '减重率', '目标体重', '代谢能力', '代谢情况', '动效',
     '固定文案', '【x性】', '【xx岁】', '当前体重', '身高', '年龄']
# B 组：OCR 视觉底模上的 UI 固有元素（不应被当作"新增需求"）
B = ['我是男生', '我是女生', '下一步', '9:41', '163cm',
     '偏瘦', '偏胖', '肥胖', '我来目睹', '身体数据 1 2 3']

out = []
out.append('summary 总字符=%d' % len(summary))
out.append('')
out.append('=== A 组：批注业务规则是否落进结构化结果 ===')
for k in A:
    n = summary.count(k)
    hit = '✔' if n else '✘未出现'
    out.append('  %-10s 出现%d次 %s' % (k, n, hit))
out.append('')
out.append('=== B 组：OCR 底模 UI 噪声是否渗入 ===')
for k in B:
    n = summary.count(k)
    out.append('  %-14s 出现%d次 %s' % (k, n, '（有渗入，需看语境）' if n else '（未渗透 OK）'))
    if n:
        i = summary.find(k)
        out.append('       上下文: ...%s...' % summary[max(0, i - 70):i + 70].replace('\n', ' '))
out.append('')
out.append('=== 结构化结果是否含 key_features / 是否为空 ===')
for tag in ['key_features', 'modules:', 'decision_tables:', 'version_goals:',
            'requirement_overview:', 'clarifications:']:
    out.append('  %-22s %s' % (tag, summary.count(tag)))
open('tmp/_noise_check.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('OK')
