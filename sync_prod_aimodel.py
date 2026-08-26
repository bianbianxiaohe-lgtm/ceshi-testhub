"""生产库同步 AIModelConfig：新建/确保 writer_vision_ocr -> qwen-vl-plus（克隆视觉模型 provider）"""
import sys
import os

# 容器内 WORKDIR=/app，确保 backend.settings 可被找到
sys.path.insert(0, '/app')

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from apps.requirement_analysis.models import AIModelConfig

OCR_ROLE = 'writer_vision_ocr'
OCR_MODEL = 'qwen-vl-plus'

existing = AIModelConfig.objects.filter(role=OCR_ROLE, is_active=True).first()
if existing:
    existing.model_name = OCR_MODEL
    existing.is_active = True
    existing.save()
    print(f'UPDATED id={existing.id} {OCR_ROLE} -> {OCR_MODEL}')
else:
    # 克隆一个已有视觉模型配置的 provider（优先 qwen-vl-max），新建 OCR 专用角色
    src = (
        AIModelConfig.objects.filter(role='writer_vision', is_active=True, model_name='qwen-vl-max').first()
        or AIModelConfig.objects.filter(role='writer_vision', is_active=True).first()
    )
    if not src:
        print('ERROR: 找不到可克隆的 writer_vision 配置，无法创建 OCR 角色')
    else:
        new = AIModelConfig(
            name='视觉分析专家(OCR专用-qwen-vl-plus)',
            model_type=src.model_type,
            role=OCR_ROLE,
            api_key=src.api_key,
            base_url=src.base_url,
            model_name=OCR_MODEL,
            max_tokens=src.max_tokens or 4096,
            temperature=src.temperature,
            top_p=src.top_p,
            is_active=True,
            created_by=src.created_by,
        )
        new.save()
        print(f'CREATED id={new.id} {OCR_ROLE} -> {OCR_MODEL} (克隆自 id={src.id} {src.model_name})')

print('\n=== 当前 AIModelConfig（活跃） ===')
for r in AIModelConfig.objects.filter(is_active=True).order_by('id'):
    print(f'  id={r.id} role={r.role!r} model={r.model_name!r}')
