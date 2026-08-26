# -*- coding: utf-8 -*-
"""
墨刀技能 - 5 阶段工作流编排器（后端落地版）

忠实复用现成技能包 modao_skill/ 的 prompts/workflow，映射到 TestHub 后端：
  阶段0 墨刀读取   -> ModaoExtractor（Playwright 逐页 + 注释 + 截图 + 视觉OCR）
  阶段1 需求通读   -> p0_requirement_struct（YAML 结构化摘要）
  阶段2 需求澄清   -> p0 复用（识别模糊/缺失/边界 -> 澄清清单）
  阶段3 用例设计   -> p1拆分 / p2测试点 / p5风险 / p6 PCI / p7三路合并(向量去重) /
                      p3用例 / p4冒烟 / p8质量自检 / Excel导出
  阶段4 冒烟执行   -> 由前端驱动用户决策，后端记录 passed/rejected

向量去重（方案 A）：p7 之前用 Chroma(bge-m3) 对三路测试点做语义近邻去重。
"""
import os
import json
import uuid
import logging
import asyncio
import datetime
import re
import urllib.parse
import time
import functools

import numpy as np

from apps.requirement_analysis.modao_prompts import (
    render_prompt,
    P0_REQUIREMENT_STRUCT, P1_MODULE_SPLIT, P2_TESTPOINT_GEN, P3_CASE_GEN,
    P4_SMOKE_EXTRACT, P5_RISK_IDENTIFY, P6_PCI_IDENTIFY, P7_MERGE_DEDUP, P8_QUALITY_CHECK,
)
from apps.requirement_analysis.vector_store import (
    get_merge_collection, release_merge_collection,
)
from apps.requirement_analysis.models import AIModelService
from apps.requirement_analysis.modao_extractor import ModaoTerminateError
from apps.requirement_analysis.cancel_flags import TERMINATE_REQUESTED

logger = logging.getLogger(__name__)


# ---------- 阶段耗时埋点（写文件，不依赖 Django 日志配置）----------
def _wf_tlog(proto_id, msg, t0=None):
    """把阶段耗时写入 /app/media/modao/proto_<id>_timing.log，供排障分析。"""
    try:
        path = os.path.join('media', 'modao', f'proto_{proto_id}_timing.log')
        if t0 is not None:
            msg = f'{msg} | 耗时 {time.time() - t0:.1f}s'
        line = f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}\n'
        with open(path, 'a') as f:
            f.write(line)
    except Exception:
        pass


def _timed_stage(label):
    """装饰器：记录某个工作流阶段的开始/结束与墙钟耗时。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *a, **k):
            pid = self.prototype.id
            t0 = time.time()
            _wf_tlog(pid, f'▶ STAGE {label} START')
            try:
                return fn(self, *a, **k)
            finally:
                _wf_tlog(pid, f'■ STAGE {label} END', t0)
        return wrapper
    return deco


MEDIA_ROOT = os.environ.get('MEDIA_ROOT', 'media')
DEDUP_THRESHOLD = 0.80  # 余弦相似度阈值（中文需求语义去重，优化后降低避免漏网）


# ---------- 解析工具 ----------
def _extract_block(content: str, lang: str = None) -> str:
    """从 LLM 输出中提取首个 ```lang 代码块。宽松兼容：
    - 标记后不紧跟换行（如 ` ```json{...} `）
    - 缺少结束 ``` 标记（截至文末）
    - 无代码块时返回原文（供 _parse_json/_parse_yaml 直接解析裸 JSON/YAML）
    """
    if not content:
        return ''
    import re
    # 结束定界符：优先 ```，否则匹配到字符串末尾（兼容未闭合代码块）
    end = r'(?:```|$)'
    if lang:
        pat = re.compile(r'```' + lang + r'\s*\n?' + r'(.*?)' + end, re.DOTALL | re.IGNORECASE)
        m = pat.search(content)
        if m:
            return m.group(1).strip()
    # 通用：匹配 ```yaml / ```json / ```yml 或无语言标记的 ``` 代码块
    pat = re.compile(r'```(?:yaml|json|yml)?\s*\n?' + r'(.*?)' + end, re.DOTALL | re.IGNORECASE)
    m = pat.search(content)
    if m:
        return m.group(1).strip()
    return content.strip()


def _parse_yaml(text: str):
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception as e:
        logger.warning(f'YAML 解析失败: {e}')
        return None


def _parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        # 容错：尝试提取首个 { ... } 块
        import re
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

def _normalize_evidence_text(value) -> str:
    """Normalize text for conservative evidence matching."""
    text = str(value or '').lower()
    return re.sub(r'[\s，。；：、,.!?！？:;（）()【】\[\]"""\'''_—-]+', '', text)


def _repair_source_coverage(all_fused_requirements, valid_pages):
    """Stage-0 G6 确定性覆盖补全。

    融合模型常把同一画布内靠 tab 切换显示的子页内容并入父页需求，
    却不把每个子页名写进 ``source_pages``。这些子页内容其实已存在于融合结果中，
    仅归因标签缺失，却会让 G6（未覆盖页占比 >20%）误判阻断。

    本函数在 G6 检查前，把"确有 DOM/视觉内容、但未被任何需求标注"的页面，
    归因到内容最匹配的需求上，确保每一页都在融合结果中有来源证据。
    """
    if not isinstance(all_fused_requirements, list) or not valid_pages:
        return
    covered = set()
    for item in all_fused_requirements:
        if isinstance(item, dict):
            for pn in item.get('source_pages') or []:
                covered.add(_normalize_evidence_text(pn))

    uncovered = [
        p for p in valid_pages
        if isinstance(p, dict)
        and _normalize_evidence_text(p.get('page_name')) not in covered
    ]
    if not uncovered:
        return

    repaired = []
    for page in uncovered:
        pname = page.get('page_name', '')
        norm = _normalize_evidence_text(pname)
        if not norm:
            continue
        target = None
        # 1) 某条需求文本直接包含该页名
        for i, item in enumerate(all_fused_requirements):
            if not isinstance(item, dict):
                continue
            if norm in json.dumps(item, ensure_ascii=False).lower():
                target = i
                break
        # 2) 某条需求已标注的页面与该页存在父子/包含关系（子页名包含父页名或反之）
        if target is None:
            for i, item in enumerate(all_fused_requirements):
                if not isinstance(item, dict):
                    continue
                for sp in (item.get('source_pages') or []):
                    spn = _normalize_evidence_text(sp)
                    if spn and (norm.startswith(spn) or spn.startswith(norm)
                                or norm in spn or spn in norm):
                        target = i
                        break
                if target is not None:
                    break
        # 3) 兜底：归因到文本最长（最可能是被合并的父页）的需求
        if target is None:
            best_len = -1
            for i, item in enumerate(all_fused_requirements):
                if not isinstance(item, dict):
                    continue
                ln = len(json.dumps(item, ensure_ascii=False))
                if ln > best_len:
                    best_len = ln
                    target = i
        if target is not None and isinstance(all_fused_requirements[target], dict):
            sp = all_fused_requirements[target].setdefault('source_pages', [])
            if pname not in sp:
                sp.append(pname)
                repaired.append(pname)
    if repaired:
        logging.getLogger(__name__).info(
            '[STAGE0] 覆盖补全：将 %d 个未被标注的页面归因到融合需求：%s',
            len(repaired), '、'.join(repaired)
        )


def _evidence_quotes(value):
    """Yield quote strings from legacy strings or structured evidence lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        quote = value.get('quote') or value.get('evidence') or value.get('text')
        if quote:
            yield str(quote)
    elif isinstance(value, list):
        for item in value:
            yield from _evidence_quotes(item)

def _evidence_items(value):
    """Keep structured page/quote evidence intact while merging modules."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _validate_evidence(value, source_text: str) -> bool:
    """Evidence is valid only when every meaningful quote occurs in source."""
    source = _normalize_evidence_text(source_text)
    quotes = [
        _normalize_evidence_text(q)
        for q in _evidence_quotes(value)
        if q and '未找到直接原文' not in str(q)
    ]
    # Short fragments are too weak to be trustworthy evidence.
    if not quotes or any(len(q) < 8 for q in quotes):
        return False
    return all(q in source for q in quotes)


def _ordered_union(left, right):
    result = []
    for item in list(left or []) + list(right or []):
        if item not in result:
            result.append(item)
    return result


def _module_signature(module):
    parts = [
        module.get('name', ''),
        module.get('description', ''),
        *[str(x) for x in module.get('key_features', []) if x],
    ]
    text = _normalize_evidence_text(''.join(parts))
    for word in ('模块', '功能', '新增', '修改', '优化', '修订', '补充', '逻辑', '页面'):
        text = text.replace(word, '')
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


def _overlap_coefficient(left, right) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _should_merge_modules(left, right) -> bool:
    left_name = _normalize_evidence_text(left.get('name'))
    right_name = _normalize_evidence_text(right.get('name'))
    generic_words = ('模块', '功能', '新增', '修改', '优化', '修订', '补充', '逻辑', '页面')
    for word in generic_words:
        left_name = left_name.replace(word, '')
        right_name = right_name.replace(word, '')
    if (len(left_name) >= 2 and len(right_name) >= 2
            and (left_name in right_name or right_name in left_name)):
        return True

    left_sources = {str(x) for x in left.get('source_locations', []) if x}
    right_sources = {str(x) for x in right.get('source_locations', []) if x}
    source_overlap = _overlap_coefficient(left_sources, right_sources)
    content_overlap = _overlap_coefficient(
        _module_signature(left), _module_signature(right)
    )
    return source_overlap >= 0.5 and content_overlap >= 0.45


def _merge_module_pair(primary, duplicate):
    merged = dict(primary)
    merged['merged_from'] = _ordered_union(
        primary.get('merged_from') or [primary.get('name')],
        duplicate.get('merged_from') or [duplicate.get('name')],
    )
    merged['source_locations'] = _ordered_union(
        primary.get('source_locations'), duplicate.get('source_locations')
    )
    merged['key_features'] = _ordered_union(
        primary.get('key_features'), duplicate.get('key_features')
    )

    merged['source_evidence'] = _ordered_union(
        _evidence_items(primary.get('source_evidence')),
        _evidence_items(duplicate.get('source_evidence')),
    )

    priority_rank = {'P0': 0, 'P1': 1, 'P2': 2}
    if priority_rank.get(duplicate.get('priority'), 9) < priority_rank.get(
        primary.get('priority'), 9
    ):
        merged['priority'] = duplicate.get('priority')
        merged['priority_source'] = duplicate.get('priority_source')
        merged['priority_reason'] = duplicate.get('priority_reason')

    for key in ('business_flow',):
        left_value = str(primary.get(key) or '').strip()
        right_value = str(duplicate.get(key) or '').strip()
        if right_value and right_value not in left_value:
            merged[key] = '\n'.join(x for x in (left_value, right_value) if x)
    return merged


def _postprocess_requirement_summary(data, source_text: str):
    """Merge probable duplicate modules and annotate evidence validity."""
    if not isinstance(data, dict):
        return data, 0, 0

    merged_modules = []
    merge_count = 0
    for raw_module in data.get('modules') or []:
        if not isinstance(raw_module, dict):
            continue
        module = dict(raw_module)
        for index, existing in enumerate(merged_modules):
            if _should_merge_modules(existing, module):
                merged_modules[index] = _merge_module_pair(existing, module)
                merge_count += 1
                break
        else:
            merged_modules.append(module)

    invalid_count = 0
    checked_count = 0
    converged_conclusions = []

    def _classify(item, module_name):
        """按「先推测后提问」判定歧义点是否可收敛：
        current_guess 唯一且无待确认问题（suggested_question 为空）→ converged，不再追问。"""
        guess = str(item.get('current_guess') or '').strip()
        question = str(item.get('suggested_question') or '').strip()
        status = str(item.get('status') or '').strip()
        converged = status in ('converged', '已确定', '确定') or (guess and not question)
        item['status'] = 'converged' if converged else 'pending'
        if converged:
            converged_conclusions.append({
                'module': module_name,
                'point': item.get('issue') or item.get('scenario') or item.get('description') or '',
                'conclusion': guess or item.get('suggested_answer') or '',
                'evidence': item.get('evidence') or item.get('basis') or '',
            })
        return converged

    priority_is_explicit = bool(re.search(r'(?<![A-Za-z0-9])P[012](?![A-Za-z0-9])', source_text, re.I))
    for module in merged_modules:
        if not priority_is_explicit:
            module['priority_source'] = '模型建议'
        module['business_flow_source'] = (
            '原文明示' if _validate_evidence(module.get('business_flow'), source_text)
            else '模型推演'
        )
        valid = _validate_evidence(module.get('source_evidence'), source_text)
        module['evidence_valid'] = valid
        module['evidence_level'] = 'A' if valid else 'D'
        module['human_confirmation_required'] = not valid
        checked_count += 1
        if not valid:
            invalid_count += 1
        for key in ('ambiguous_points', 'boundary_points'):
            for item in module.get(key) or []:
                if not isinstance(item, dict):
                    continue
                valid = _validate_evidence(item.get('evidence'), source_text)
                item['evidence_valid'] = valid
                item['evidence_level'] = 'A' if valid else 'D'
                converged = _classify(item, module.get('name', ''))
                item['human_confirmation_required'] = (not converged) or (not valid)
                checked_count += 1
                invalid_count += int(not valid)

    for key in ('ambiguous_points', 'boundary_points'):
        for item in data.get(key) or []:
            if isinstance(item, dict):
                valid = _validate_evidence(item.get('evidence'), source_text)
                item['evidence_valid'] = valid
                item['evidence_level'] = 'A' if valid else 'D'
                converged = _classify(item, '全局')
                item['human_confirmation_required'] = (not converged) or (not valid)
                checked_count += 1
                if not valid:
                    invalid_count += 1

    data['modules'] = merged_modules
    data['evidence_validation'] = {
        'checked_count': checked_count,
        'invalid_count': invalid_count,
        'rule': 'normalized_exact_quote_match',
        'levels': {
            'A': '原文或视觉元素精确验证，可进入测试设计',
            'B': '跨页面推导，需保留推导标记',
            'C': '模型建议或需求缺失，仅用于探索性分析',
            'D': '证据验证失败，必须人工确认后才能生成最终用例',
        },
    }
    for item in data.get('missing_points') or []:
        if isinstance(item, dict):
            item['evidence_level'] = 'C'
            converged = _classify(item, '全局')
            item['human_confirmation_required'] = not converged
    for key in ('ambiguous_points', 'missing_points', 'boundary_points'):
        data.setdefault(key, [])
    data['converged_conclusions'] = converged_conclusions
    return data, merge_count, invalid_count


def _normalize_pci_dispositions(all_pci: list) -> dict:
    """机器侧收敛：low/medium 且 suggested_answer 是具体结论的 PCI，
    自动标记 disposition=assumed（按默认假设处理），不计入人工确认负担；
    high/blocker 或建议答案空泛的保持 disposition=confirm；
    含「修改/新增规则、数值阈值、文案」等可能改变产品决策的答案标记 suspicious（需人工确认）；
    assumed 中跨模块重复的问题合并为一条（标记 dedup_assumed）。"""
    import difflib
    import re
    stats = {
        'total': 0, 'assumed': 0, 'confirm': 0, 'suspicious': 0, 'dedup': 0,
        'by_impact': {}, 'by_disposition': {},
    }
    vague_markers = ('待确认', '待定', '需产品', '需要产品', '无法给出', '待进一步', '确认后', '待明确')
    # 答案若涉及修改/新增产品规则、具体数值阈值或文案，属于产品决策，不静默收敛
    change_markers = ('改为', '修改为', '调整为', '新增', '上限', '阈值', '固定为', '统一为', '设为', '文案')

    def _norm(text: str) -> str:
        text = re.sub(r'「[^」]*」', '', text or '')
        text = re.sub(r'\s+', '', text)
        text = re.sub(r'[，。；：、,.!?！？:;（）()【】\[\]"\'\-—_]+', '', text)
        return text

    seen_keys = []
    for mod in all_pci:
        data = mod.get('data') if isinstance(mod, dict) else None
        if not isinstance(data, dict):
            continue
        items = data.get('pci_list')
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            impact = str(it.get('impact') or '').lower()
            stats['total'] += 1
            stats['by_impact'][impact] = stats['by_impact'].get(impact, 0) + 1
            if impact in ('low', 'medium'):
                answer = str(it.get('suggested_answer') or '').strip()
                if not answer or len(answer) < 4 or any(m in answer for m in vague_markers):
                    it['disposition'] = 'confirm'
                    stats['confirm'] += 1
                elif any(m in answer for m in change_markers):
                    it['disposition'] = 'suspicious'
                    stats['suspicious'] += 1
                else:
                    # 跨模块去重：规范化后与已有 assumed 问题高度相似则合并
                    key = _norm(it.get('description') or '')
                    dup = None
                    for k in seen_keys:
                        if difflib.SequenceMatcher(None, k, key).ratio() >= 0.9:
                            dup = k
                            break
                    if dup is not None:
                        it['disposition'] = 'dedup_assumed'
                        it['merged_into'] = '见首个模块的同类假设'
                        stats['dedup'] += 1
                    else:
                        seen_keys.append(key)
                        it['disposition'] = 'assumed'
                        it['assumed_answer'] = answer
                        stats['assumed'] += 1
            else:
                it['disposition'] = 'confirm'
                stats['confirm'] += 1
            disp = it.get('disposition')
            stats['by_disposition'][disp] = stats['by_disposition'].get(disp, 0) + 1
    return stats


class ModaoWorkflow:
    """墨刀技能工作流编排。"""

    def __init__(self, prototype, analyzer_config, writer_config, embedder_config,
                 vision_config=None, ocr_vision_config=None, dedup_threshold=DEDUP_THRESHOLD):
        self.prototype = prototype
        self.analyzer_config = analyzer_config
        self.writer_config = writer_config
        self.embedder_config = embedder_config
        self.vision_config = vision_config
        self.ocr_vision_config = ocr_vision_config or vision_config
        self.dedup_threshold = dedup_threshold
        self.session_id = prototype.uuid

    # ---------- 配置解析 ----------
    @staticmethod
    def resolve_configs(analyzer_id=None, writer_id=None, embedder_id=None):
        from apps.requirement_analysis.models import AIModelConfig
        analyzer = (AIModelConfig.objects.filter(id=analyzer_id).first()
                    if analyzer_id else AIModelConfig.get_active_config('siliconflow', 'analyzer')
                    or AIModelConfig.objects.filter(role='analyzer', is_active=True).first())
        writer = (AIModelConfig.objects.filter(id=writer_id).first()
                  if writer_id else AIModelConfig.objects.filter(role='writer', is_active=True).first())
        embedder = (AIModelConfig.objects.filter(id=embedder_id).first()
                    if embedder_id else AIModelConfig.get_active_embedder())
        # fallback: analyzer 缺失时复用 writer（两者都是 LLM 文本生成，可共用模型）
        if not analyzer and writer:
            analyzer = writer
        return analyzer, writer, embedder

    # ---------- LLM / 向量 基础 ----------
    def _llm(self, config, prompt: str, max_tokens: int = 8000, timeout: int = 300, temperature: float = None, return_meta: bool = False):
        """调用 LLM。带超时保护：单条调用超过 timeout 秒即抛 asyncio.TimeoutError，
        由上层（run_design_phase1 模块级 try/except）捕获并降级，避免窗口永久卡死。

        temperature: None=沿用config.temperature, 0=确定性输出(推荐用于结构化生成)。
        return_meta: True 时返回 dict(content, finish_reason)，便于上层检测 max_tokens 截断；
                     默认 False 维持仅返回 content 字符串，不影响其他调用方。"""
        import time as _time
        if not config:
            raise Exception('缺少可用的 AI 模型配置（analyzer/writer）')
        t0 = _time.time()
        model_label = f'{config.model_type}/{config.model_name}'
        role_label = getattr(config, 'role', '?')
        temp_label = f't={temperature}' if temperature is not None else f't={config.temperature}'
        prompt_line1 = (prompt.strip() or '').split('\n')[0][:60]
        print(f'[LLM] ▶ 调用 {model_label} (role={role_label}) | {temp_label} | max_tokens={max_tokens} | 提示: {prompt_line1}...', flush=True)
        messages = [{'role': 'user', 'content': prompt}]
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    AIModelService.call_openai_compatible_api(config, messages, max_tokens=max_tokens, temperature=temperature),
                    timeout=timeout,
                )
            )
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f'LLM 调用超时（>{timeout}s），请检查模型服务是否可用或网络是否通畅'
            )
        content = result['choices'][0]['message']['content']
        finish_reason = None
        try:
            finish_reason = result['choices'][0].get('finish_reason')
        except Exception:
            pass
        elapsed = _time.time() - t0
        print(f'[LLM] ✓ {model_label} 返回 {len(content)}字符 耗时 {elapsed:.1f}s finish_reason={finish_reason}', flush=True)
        if return_meta:
            return {'content': content, 'finish_reason': finish_reason}
        return content

    def _embed(self, texts):
        if not self.embedder_config:
            return None
        try:
            return asyncio.run(
                asyncio.wait_for(
                    AIModelService.embed_texts(self.embedder_config, texts),
                    timeout=300,
                )
            )
        except asyncio.TimeoutError:
            logger.warning(f'向量化超时（降级为无去重，>300s）')
            return None
        except Exception as e:
            logger.warning(f'向量化失败（降级为无去重）: {e}')
            return None

    def _cosine_sim(self, texts_a, texts_b):
        """两组文本的余弦相似度矩阵（len(a) x len(b)）；embedder 不可用或失败返回 None，调用方自行降级。"""
        if not self.embedder_config or not texts_a or not texts_b:
            return None
        vecs = self._embed(list(texts_a) + list(texts_b))
        if not vecs:
            return None
        try:
            arr = np.array(vecs, dtype=float)
            arr = arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9, None)
            na = len(texts_a)
            return arr[:na] @ arr[na:].T
        except Exception as e:
            logger.warning(f'PCI 语义相似度计算失败: {e}')
            return None

    # ---------- 向量语义去重（方案 A）----------
    def _vector_dedup(self, items):
        """
        items: [{'id','title','description','source'(list),'priority'}]
        返回 (deduped_items, dedup_count, audit_records)

        预排序：按 priority (P0>P1>P2) → id/title 字母序，确保同输入下结果稳定。
        """
        if not items:
            return items, 0, []
        # 稳定排序：高优先级在前 → 同优先级按 id/title 字典序
        prio_w = {'P0': 0, 'P1': 1, 'P2': 2}
        items = sorted(items, key=lambda it: (
            prio_w.get(it.get('priority', '').upper() if isinstance(it.get('priority'), str) else 'P9', 9),
            it.get('id', '') or it.get('title', '') or '',
        ))
        texts = [it.get('description') or it.get('title') or '' for it in items]
        vecs = self._embed(texts)
        if vecs is None:
            logger.info('无 embedder，跳过向量去重')
            return items, 0, []
        try:
            arr = np.array(vecs, dtype=float)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / np.clip(norms, 1e-9, None)
            sim = arr @ arr.T
        except Exception as e:
            logger.warning(f'向量去重计算失败: {e}')
            return items, 0, []

        n = len(items)
        keep = [True] * n
        dedup = 0
        audit_records = []

        def better(a, b):
            return prio_w.get(a.get('priority'), 9) <= prio_w.get(b.get('priority'), 9)

        for i in range(n):
            if not keep[i]:
                continue
            for j in range(i + 1, n):
                if keep[j] and sim[i][j] >= self.dedup_threshold:
                    audit_records.append({
                        'kept_id': items[i].get('id'),
                        'kept_title': items[i].get('title', ''),
                        'removed_id': items[j].get('id'),
                        'removed_title': items[j].get('title', ''),
                        'similarity': round(float(sim[i][j]), 6),
                        'threshold': self.dedup_threshold,
                        'reason': '同模块测试点描述的向量相似度达到阈值',
                    })
                    # 合并来源标记，保留高优先级代表
                    src = list(set((items[i].get('source') or []) + (items[j].get('source') or [])))
                    if better(items[j], items[i]):
                        items[i]['priority'] = items[j]['priority']
                    items[i]['source'] = src
                    items[i]['description'] = items[i].get('description') or items[j].get('description')
                    keep[j] = False
                    dedup += 1
        result = [items[i] for i in range(n) if keep[i]]
        return result, dedup, audit_records

    def _pci_dedup_against_clarifications(self, pci_list, clarification_log):
        """
        后处理去重：把 PCI 列表中与已澄清问题（resolution 非空）高度相似的条目剔除。

        pci_list: [{'title','description','priority',...}, ...]
        clarification_log: 字符串（JSON 数组）或已解析列表
        返回 (filtered_pci_list, removed_count, removed_items)
        """
        if not pci_list:
            return pci_list, 0, []
        # 解析澄清清单，只取 resolution 非空的条目
        try:
            clarify_items = json.loads(clarification_log) if isinstance(clarification_log, str) else (clarification_log or [])
        except Exception:
            clarify_items = []
        if not isinstance(clarify_items, list):
            clarify_items = []
        resolved = []
        for item in clarify_items:
            if not isinstance(item, dict):
                continue
            resolution = str(item.get('resolution') or item.get('answer') or '').strip()
            if resolution:
                resolved.append(item)
        if not resolved:
            return pci_list, 0, []

        # 构建已澄清问题的文本集合（issue + suggested_question + resolution 摘要）
        def _clean(s):
            return re.sub(r'\s+', '', str(s or ''))
        resolved_texts = []
        for r in resolved:
            parts = [r.get('issue', ''), r.get('suggested_question', ''), r.get('resolution', '')]
            resolved_texts.append(_clean(' '.join(parts)))

        # 对每条 PCI，计算其与已澄清问题的最优相似度（向量余弦主判抓改写重复，字面 difflib 兜底）
        import difflib
        pci_raw_texts = [(pci.get('description') or '') + ' ' + (pci.get('title') or '')
                         for pci in pci_list if isinstance(pci, dict)]
        ref_question_texts = [((r.get('issue') or '') + ' ' + (r.get('suggested_question') or '')).strip()
                              for r in resolved]
        cos_sim = self._cosine_sim(pci_raw_texts, ref_question_texts)
        keep = []
        removed = []
        raw_idx = -1
        for pci in pci_list:
            if not isinstance(pci, dict):
                keep.append(pci)
                continue
            raw_idx += 1
            pci_text = _clean((pci.get('description') or '') + ' ' + (pci.get('title') or ''))
            if not pci_text:
                keep.append(pci)
                continue
            max_ratio = 0.0
            for rt in resolved_texts:
                if not rt:
                    continue
                ratio = difflib.SequenceMatcher(None, pci_text, rt).ratio()
                if ratio > max_ratio:
                    max_ratio = ratio
            max_cos = 0.0
            if cos_sim is not None:
                try:
                    max_cos = float(max(cos_sim[raw_idx]))
                except Exception:
                    max_cos = 0.0
            # 判重：向量余弦 >= dedup_threshold（改写重复）或字面 >= 0.55
            if max_cos >= self.dedup_threshold or max_ratio >= 0.55:
                removed.append({'title': pci.get('title', ''), 'description': pci.get('description', ''),
                                'max_similarity': round(max_ratio, 3), 'max_cosine': round(max_cos, 3)})
            else:
                keep.append(pci)
        return keep, len(removed), removed

    def _log(self, msg: str):
        """追加工作日志到 prototype.work_log（带时间戳）。"""
        from datetime import datetime as dt
        ts = dt.now().strftime('%H:%M:%S')
        entry = f"[{ts}] {msg}\n"
        self.prototype.work_log = (self.prototype.work_log or '') + entry
        # 同时更新 updated_at，保证超时看门狗能感知任务仍在推进，避免误判为卡死
        self.prototype.save(update_fields=['work_log', 'updated_at'])

    def ask_question(self, stage: int, question: str, max_tokens: int = 4000) -> str:
        """针对某阶段产物进行答疑（人工疑点解答），返回 AI 回答文本。"""
        ctx_map = {
            0: (self.prototype.extracted_json or '') + '\n' + (self.prototype.requirement_summary or ''),
            1: self.prototype.requirement_summary or '',
            2: self.prototype.clarification_log or '',
            3: '\n'.join([
                self.prototype.testcases_json or '',
                self.prototype.final_testpoints_json or '',
                self.prototype.risks_json or '',
                self.prototype.pci_json or '',
            ]),
        }
        context = (ctx_map.get(stage, self.prototype.requirement_summary) or '').strip()
        if not context:
            return '该阶段暂无内容可答疑，请先运行对应阶段生成产物。'
        prompt = (
            '你是一名资深测试分析师。用户对工作流产物有疑问，请用 **2-4 句话** 简洁应答。\n\n'
            f'===== 产物内容 =====\n{context}\n===== 结束 =====\n\n'
            f'用户疑问：{question}\n\n'
            '要求：直接给结论（不说「需确认」、不用反问）。简述依据。'
            '末尾用 [推断] 标记不确定的结论。禁止 4 段式结构、禁止大段论述、禁止行业科普。'
        )
        return self._llm(self.analyzer_config or self.writer_config, prompt, max_tokens=max_tokens)

    # ---------- 阶段0：原型读取（支持多地址批量 + 单地址自动发现页面树）----------
    @staticmethod
    def _page_label_from_url(u: str) -> str:
        """从 URL 推断页面名：优先取 hash 中的 p= 参数（已 URL 解码），否则取路径末段。"""
        try:
            frag = u.split('#', 1)[1] if '#' in u else ''
            m = re.search(r'[?&]p=([^&]+)', frag)
            if not m:
                m = re.search(r'[?&]p=([^&]+)', u)
            if m:
                return urllib.parse.unquote(m.group(1))
        except Exception:
            pass
        path = u.split('#')[0].rstrip('/')
        return path.split('/')[-1] or u

    @_timed_stage('阶段0 读取')
    def run_extract(self, urls=None, url=None, cookies=None, headless=True, source_type=None,
                    dual_fusion=False, fusion_config=None):
        from apps.requirement_analysis.modao_extractor import ModaoExtractor
        source_type = source_type or self.prototype.source_type or 'modao'
        # 双路融合：未显式指定 fusion_config 时，复用分析用的 analyzer 配置做交叉融合
        if dual_fusion and fusion_config is None:
            fusion_config = self.analyzer_config
        if dual_fusion and not self.vision_config:
            self.prototype.status = 'failed'
            self.prototype.error_message = '双路融合需要启用 writer_vision 视觉模型配置，读取已中止。'
            self.prototype.save(update_fields=['status', 'error_message'])
            return {'pages': [], 'blocked': True, 'error': 'missing_vision_config'}
        if dual_fusion and not fusion_config:
            self.prototype.status = 'failed'
            self.prototype.error_message = '双路融合需要可用的 analyzer/writer 文本模型配置，读取已中止。'
            self.prototype.save(update_fields=['status', 'error_message'])
            return {'pages': [], 'blocked': True, 'error': 'missing_fusion_config'}
        # 规范化 URL 列表（兼容单字符串 / 列表 / 换行或逗号分隔）
        if urls is None:
            urls = [url] if url else []
        elif isinstance(urls, str):
            urls = [x for x in urls.replace(',', '\n').split('\n') if x.strip()]
        urls = [x.strip() for x in urls if isinstance(x, str) and x.strip()]
        urls = list(dict.fromkeys(urls))  # 去重保序
        if not urls:
            self.prototype.status = 'failed'
            self.prototype.error_message = '未提供有效的需求地址'
            self.prototype.save(update_fields=['status', 'error_message'])
            self._log('未提供有效的需求地址，读取中止')
            return {'pages': []}

        self.prototype.status = 'extracting'
        self.prototype.save(update_fields=['status'])
        self._log(f'开始需求读取，共 {len(urls)} 个地址...')
        extractor = ModaoExtractor(run_id=self.session_id)
        all_pages = []
        all_warnings = []
        all_fused_requirements = []
        for ui, u in enumerate(urls, 1):
            try:
                # webshare：始终枚举页面树（目录地址自动发现所有子页面）。
                # 墨刀多地址：每个当单页抓（避免页面树枚举导致跨地址重复）；
                # 墨刀单地址：尝试枚举页面树自动发现目录内多页。
                if source_type == 'webshare':
                    enumerate_pages = True
                    single = False
                else:
                    single = len(urls) > 1
                    enumerate_pages = not single
                data = extractor.extract_sync(url=u, cookies=cookies, headless=headless,
                                              enumerate_pages=enumerate_pages,
                                              source_type=source_type,
                                              vision_config=self.vision_config,
                                              ocr_vision_config=self.ocr_vision_config,
                                              dual_fusion=dual_fusion,
                                              fusion_config=fusion_config,
                                              prototype_id=self.prototype.id)
                for p in data['pages']:
                    if single:
                        # 单页模式 extractor 给的是默认"第N页"，用 URL 推断更可读的页面名
                        p['page_name'] = self._page_label_from_url(u) or p.get('page_name') or f'地址{ui}'
                    all_pages.append(p)
                all_warnings.extend(data.get('warnings') or [])
                all_fused_requirements.extend(data.get('fused_requirements') or [])
                self._log(f'地址{ui}读取完成：{len(data["pages"])} 页')
            except ModaoTerminateError as te:
                # 用户在前端点「终止」：立即收尾为 failed，避免被外层 except 吞掉后当正常跑完
                self._log(f'任务已被用户手动终止：{te}')
                TERMINATE_REQUESTED.pop(self.prototype.id, None)
                self.prototype.refresh_from_db()
                self.prototype.status = 'failed'
                self.prototype.error_message = '任务已被用户手动终止'
                self.prototype.save(update_fields=['status', 'error_message'])
                return {'pages': all_pages, 'terminated': True}
            except Exception as e:
                logger.error(f'地址[{u}]读取失败: {e}')
                self._log(f'地址{ui}读取失败: {e}')
                continue

        # 重新编号并落库（先清空旧 pages，避免重跑累积）
        for idx, p in enumerate(all_pages, 1):
            p['page_no'] = idx
        self.prototype.pages.all().delete()
        auto_filtered_names = []
        for p in all_pages:
            should_filter, reason = self._auto_filter_page(p)
            note = f'自动过滤：{reason}' if should_filter else ''
            if should_filter:
                auto_filtered_names.append(p.get('page_name', ''))
            self.prototype.pages.create(
                page_no=p['page_no'],
                page_name=p['page_name'],
                text=p.get('text', ''),
                annotations=json.dumps(p.get('annotations', []), ensure_ascii=False),
                screenshot=p.get('screenshot', ''),
                selected=(not should_filter),
                recognition_note=note,
                # A2-b：提取完成即标记画布「已读取」
                current_stage=0,
                stage_status='done',
            )
        if auto_filtered_names:
            self._log(
                f'已自动过滤 {len(auto_filtered_names)} 个无效画布（默认不纳入结构化）：'
                + '、'.join(auto_filtered_names)
                + '；如需保留可在「校验画布模块」中手动勾选恢复'
            )
        valid_pages = [p for p in all_pages if not p.get('duplicate_of_page')]
        duplicate_count = len(all_pages) - len(valid_pages)
        self._log(f'全部读取完成，共 {len(all_pages)} 页 / {len(valid_pages)} 个独立画布')
        # 阶段0来源覆盖补全：在落库前执行，使修复后的 source_pages 持久化；
        # 避免动态子页内容被并入父页需求时误触发 G6（>20% 未覆盖）阻断。融合内容本身完整。
        _repair_source_coverage(all_fused_requirements, valid_pages)
        self.prototype.extracted_json = json.dumps({
            'urls': urls,
            'pages': [{
                'page_no': p['page_no'],
                'page_name': p['page_name'],
                'text': p.get('text', ''),
                'dom_text': p.get('dom_text', ''),
                'vision_text': p.get('vision_text', ''),
                'dom_text_len': p.get('dom_text_len', 0),
                'vision_attempted': bool(p.get('vision_attempted')),
                'vision_success': bool(p.get('vision_success')),
                'annotations': p.get('annotations', []),
                'screenshot': p.get('screenshot', ''),
                'visual_summary': p.get('visual_summary', ''),
                'visual_artifacts': p.get('visual_artifacts', []),
                'screenshot_sha256': p.get('screenshot_sha256', ''),
                'duplicate_of_page': p.get('duplicate_of_page'),
                'extraction_warnings': p.get('extraction_warnings', []),
            } for p in all_pages],
            'dual_fusion': bool(dual_fusion),
            'fused_requirements': all_fused_requirements,
            'warnings': all_warnings,
        }, ensure_ascii=False)
        self.prototype.source_type = source_type
        # 多页原型如果超过 20% 的页面是完全相同截图，说明画布切换不可信；
        # 保留所有读取产物供排查，但阻断结构化和后续用例生成。
        duplicate_ratio = duplicate_count / len(all_pages) if all_pages else 0
        block_reasons = []

        # ── 阻断 1: 空页 ──
        if not all_pages:
            block_reasons.append('未能从链接中读取到任何页面内容，请检查链接是否有效、是否需要登录')

        # ── 阻断 2: 截图重复 ──
        if len(all_pages) > 1 and duplicate_ratio > 0.2:
            block_reasons.append(
                f'有 {duplicate_count} 页截图重复（共 {len(all_pages)} 页），可能是墨刀画布切换失败，'
                f'建议关闭双路融合后重试，或手动逐页截图上传'
            )

        # ── 视觉识别校验 ──
        attempted_pages = [p for p in valid_pages if p.get('vision_attempted')]
        vision_failed = [p for p in attempted_pages if not p.get('vision_success')]
        vision_failure_ratio = len(vision_failed) / len(attempted_pages) if attempted_pages else 0
        is_small_prototype = len(all_pages) <= 2  # 1~2 页的小原型不因单页视觉失败而阻断

        if dual_fusion and vision_failure_ratio > 0.2 and not is_small_prototype:
            failed_names = '、'.join(p.get('page_name', '') for p in vision_failed[:8])
            block_reasons.append(
                f'有 {len(vision_failed)} 个页面的视觉识别未返回有效结果（{failed_names}），'
                f'请检查视觉模型配置是否正常、API 额度是否充足'
            )

        # ── 小原型视觉失败 → 降级为告警，不阻断 ──
        if is_small_prototype and vision_failed:
            self._log(
                f'小原型（{len(all_pages)} 页）中有 {len(vision_failed)} 页视觉识别未返回内容，'
                f'已自动降级为纯 DOM 文本模式继续处理，不影响后续流程'
            )

        if dual_fusion and len(attempted_pages) != len(valid_pages):
            block_reasons.append(
                f'视觉识别覆盖率不足：{len(valid_pages)} 个页面中仅 {len(attempted_pages)} 个完成了识别，'
                f'请检查视觉模型是否可用'
            )

        # ── 阻断 5: 融合需求为空 ──
        if dual_fusion and not all_fused_requirements:
            block_reasons.append(
                '双路融合（DOM + 视觉）未能生成有效的结构化需求，'
                '可能是原型内容过少或格式不支持，建议改用纯文本模式上传需求'
            )

        # ── 阻断 6: 页面覆盖不足 ──
        fused_source_pages = set()
        for item in all_fused_requirements:
            if not isinstance(item, dict):
                continue
            for page_name in item.get('source_pages') or []:
                fused_source_pages.add(_normalize_evidence_text(page_name))
        uncovered_pages = [
            p for p in valid_pages
            if _normalize_evidence_text(p.get('page_name')) not in fused_source_pages
        ]
        uncovered_ratio = len(uncovered_pages) / len(valid_pages) if valid_pages else 0
        if dual_fusion and all_fused_requirements and uncovered_ratio > 0.2:
            uncovered_names = '、'.join(p.get('page_name', '') for p in uncovered_pages[:8])
            block_reasons.append(
                f'有 {len(uncovered_pages)} 个页面的内容未被融合需求覆盖：{uncovered_names}，'
                f'建议检查这些页面是否有效、是否需要重新读取'
            )
        extraction_blocked = bool(block_reasons)
        self.prototype.status = 'failed' if extraction_blocked else 'extracted'
        if extraction_blocked:
            self.prototype.error_message = '原型读取失败：\n' + '\n'.join(f'  · {r}' for r in block_reasons)
        else:
            self.prototype.error_message = ''
        self.prototype.current_stage = 0
        # A2-b：同步画布级状态（提取成功=已读取 done；失败=failed）
        page_status = 'failed' if extraction_blocked else 'done'
        self.prototype.pages.all().update(
            stage_status=page_status,
            error_message=(self.prototype.error_message if extraction_blocked else ''),
        )
        self.prototype.save()
        if extraction_blocked:
            self._log(self.prototype.error_message)
        return {
            'pages': all_pages,
            'valid_pages': len(valid_pages),
            'vision_attempted': len(attempted_pages),
            'vision_failed': len(vision_failed),
            'fused_requirements': len(all_fused_requirements),
            'uncovered_pages': len(uncovered_pages),
            'blocked': extraction_blocked,
        }

    # ---------- 阶段0 画布自动过滤 ----------
    # 墨刀原型常自带模板/引导/封面/副本页（如「总览/演示/标注/登录/免费使用」等），
    # 这些页对需求结构化无意义，读取后自动取消勾选，避免污染后续流程；
    # 用户仍可在画布校验卡片上手改回勾选。
    _USELESS_PAGE_HINTS = (
        '总览', '演示', '标注', '登录', '免费使用', '引导', '封面', '示例', '帮助',
        'about', 'intro', 'start', 'cover', 'template', 'demo', 'guide', 'tour',
        '欢迎', '首页引导', '使用说明', '新手', '教程', '预览',
    )

    @classmethod
    def _auto_filter_page(cls, p: dict):
        """判断某画布是否应自动过滤（不纳入后续流程）。

        返回 (should_filter: bool, reason: str)。保守策略，仅命中明确无效特征才过滤，
        避免误杀真实业务页面。
        """
        # 1) 副本页（与某页重复）
        dup = p.get('duplicate_of_page')
        if dup:
            return True, f'画布副本(与「{dup}」重复)'

        name = (p.get('page_name') or '').strip().lower()
        # 2) 页面名命中无用模板关键词（整名或包含关键词）
        for hint in cls._USELESS_PAGE_HINTS:
            hl = hint.lower()
            if name == hl or hl in name:
                return True, f'模板/引导页(命中「{hint}」)'

        # 3) 内容过少：DOM 文本极短且视觉也未提供有效内容，疑似空页/封面
        dom_len = int(p.get('dom_text_len') or 0)
        vision_ok = bool(p.get('vision_success'))
        vision_text = (p.get('vision_text') or '').strip()
        if dom_len < 15 and (not vision_ok or len(vision_text) < 15):
            return True, '内容过少(疑似空页/封面)'

        return False, ''

    # ---------- 阶段1：需求结构化 ----------
    def _selected_page_names(self) -> set:
        """已勾选（纳入后续流程）的画布名集合；未做勾选操作时默认全部纳入。"""
        try:
            pages = self.prototype.pages.all()
            if not pages:
                return set()
            selected = {p.page_name for p in pages if getattr(p, 'selected', True)}
            # 若没有任何一条 selected 记录（历史数据），视为全选
            if not selected:
                return {p.page_name for p in pages}
            return selected
        except Exception:
            return set()

    def _advance_selected_pages(self, stage, status='done', error=None):
        """A2-b：把任务下所有「已勾选」画布的画布级进度推进到指定阶段。

        结构化/澄清/测试点合并是任务级全局聚合操作，完成后所有参与画布统一推进；
        回退时由回退接口单独调用本方法降级。
        """
        try:
            selected_names = self._selected_page_names()
            pages = self.prototype.pages.all()
            if selected_names:
                pages = pages.filter(page_name__in=selected_names)
            for p in pages:
                # 只在前进时取 max；回退（stage 更小）时由调用方直接赋值
                if stage >= p.current_stage:
                    p.current_stage = stage
                if status:
                    p.stage_status = status
                if error is not None:
                    p.error_message = error
                p.save(update_fields=['current_stage', 'stage_status', 'error_message'])
        except Exception as e:
            logger.warning('[_advance_selected_pages] 同步画布进度失败: %s', e)

    def _source_text(self) -> str:
        if self.prototype.extracted_json:
            selected_names = self._selected_page_names()
            data = json.loads(self.prototype.extracted_json)
            parts = []
            fused = data.get('fused_requirements') or []
            if fused:
                if selected_names:
                    fused = [
                        x for x in fused
                        if isinstance(x, dict)
                        and (selected_names & set(str(s) for s in (x.get('source_pages') or [])))
                    ]
                parts.append(
                    '## DOM + 视觉双路交叉融合需求（结构化主输入）\n'
                    + json.dumps(fused, ensure_ascii=False)
                )
            for p in data.get('pages', []):
                if p.get('duplicate_of_page'):
                    continue
                if selected_names and p.get('page_name') not in selected_names:
                    continue
                parts.append(
                    f"### {p['page_name']}\n{p.get('text','')}\n"
                    f"[注释/标注] {json.dumps(p.get('annotations', []), ensure_ascii=False)}\n"
                    f"[结构化视觉内容 visual_artifacts] "
                    f"{json.dumps(p.get('visual_artifacts', []), ensure_ascii=False)}")
            return '\n\n'.join(parts)
        return self.prototype.requirement_summary or ''

    def _match_page_text_for_module(self, mod_name: str, mod: dict = None) -> str:
        """注入该模块的结构化需求到 P2 prompt。

        优先使用 fused_requirements（阶段0 已由 LLM+OCR 逐页提取、按 module 归类的结构化需求），
        它们含 feature + interaction + evidence，是测试点生成的最高质量输入。
        fused 无匹配时才回退到页面 text 匹配。
        """
        if not self.prototype.extracted_json or not mod_name:
            return ''
        try:
            data = json.loads(self.prototype.extracted_json)
        except Exception:
            return ''
        # ① 优先：fused_requirements 按 module 匹配（兼容细分后的「父模块-来源页」子模块名）
        rel = self._fused_entries_for_module(mod_name)
        if rel:
            parts = [f'\n\n【该模块已提取的结构化需求（LLM+OCR 逐条）】以下为模块「{mod_name}」的 {len(rel)} 条需求，'
                     f'请严格基于这些具体需求生成测试点，不要泛化或臆造：']
            used_len = 0
            max_total = 5000
            for i, r in enumerate(rel, 1):
                if used_len >= max_total:
                    break
                feature = r.get('feature', '') or ''
                interaction = r.get('interaction', '') or ''
                ev = r.get('evidence', '') or ''
                block = f'{i}. 【{feature}】{interaction}'
                if ev:
                    block += f'（证据等级：{ev}）'
                if len(block) > 600:
                    block = block[:600]
                if used_len + len(block) > max_total:
                    block = block[:max_total - used_len]
                used_len += len(block)
                parts.append(block)
            return '\n'.join(parts)
        # ② 回退：页面 text 匹配（fused 无该模块时用）
        pages = [p for p in data.get('pages', []) if not p.get('duplicate_of_page')]
        if not pages:
            return ''
        import re
        mod_words = set(re.findall(r'[\u4e00-\u9fa5]{2,4}', mod_name))
        if not mod_words:
            mod_words = {mod_name}
        matched = []
        for p in pages:
            page_name = p.get('page_name', '') or ''
            text_head = (p.get('text', '') or '')[:500]
            if any(w in page_name for w in mod_words) or any(w in text_head for w in mod_words):
                matched.append(p)
        if not matched:
            for p in pages:
                if any(w in p.get('page_name', '') for w in mod_words):
                    matched.append(p)
        if not matched:
            return ''
        import re as _re
        _noise = {'总览', '演示', '标注', '登录', '免费使用', '画布', '页面', '图层', '批注', '评论',
                  '展开全部', '展开', '登录后导出', '欢迎来到墨刀', '立即登录', '预览', '分享', '收起'}
        mod_keywords = set()
        for f in (mod.get('features', []) if isinstance(mod, dict) else []):
            mod_keywords.update(_re.findall(r'[\u4e00-\u9fa5]{2,6}', str(f)))
        if not mod_keywords:
            mod_keywords = mod_words
        parts = [f'\n\n【对应原型的页面关键需求（便签/批注，已按模块相关性抽取）】以下内容属于模块「{mod_name}」，请基于这些具体需求生成测试点：']
        used_len = 0
        max_total = 4000
        for p in matched[:3]:
            if used_len >= max_total:
                break
            txt = (p.get('text', '') or '').strip()
            if not txt:
                continue
            lines = []
            for ln in txt.split('\n'):
                ln_s = ln.strip()
                if not ln_s:
                    continue
                if ln_s in _noise or ln_s.startswith('墨刀用户'):
                    continue
                lines.append(ln_s)
            relevant = [ln for ln in lines if any(k in ln for k in mod_keywords)]
            pick = relevant if len(relevant) >= 3 else lines
            block = '\n'.join(pick)
            if len(block) > 1800:
                block = block[:1800]
            if used_len + len(block) > max_total:
                block = block[:max_total - used_len]
            used_len += len(block)
            parts.append(f"\n### 页面「{p.get('page_name','未命名')}」（第{p.get('page_no')}页）\n{block}")
        return '\n'.join(parts) if len(parts) > 1 else ''

    def _extract_module_context(self, mod_name: str) -> str:
        """从阶段1 requirement_summary 提取当前模块的跨模块关联影响与特有风险，
        注入 PCI 生成 prompt，让 PCI 具备全局关联视角（类似 PDF 的『待确认风险列+跨模块影响』）。
        """
        summary = (self.prototype.requirement_summary or '').strip()
        if not summary:
            return ''
        try:
            data = _parse_yaml(summary)
        except Exception:
            return ''
        if not isinstance(data, dict):
            return ''
        modules = data.get('modules') or []
        if not isinstance(modules, list):
            return ''
        target = None
        for m in modules:
            if not isinstance(m, dict):
                continue
            name = str(m.get('name', '') or '').strip()
            if name == mod_name or mod_name in name or name in mod_name:
                target = m
                break
        if not target:
            return ''
        impact = target.get('cross_module_impact') or []
        risks = target.get('module_risks') or []
        parts = []
        if isinstance(impact, list) and impact:
            parts.append('跨模块关联影响：\n' + '\n'.join(f'- {i}' for i in impact))
        if isinstance(risks, list) and risks:
            parts.append('本模块特有风险：\n' + '\n'.join(f'- {r}' for r in risks))
        if not parts:
            return ''
        return '\n'.join(parts)

    def _fused_entries_for_module(self, mod_name: str) -> list:
        """按模块名匹配返回 fused_requirements 条目列表。

        兼容两种形式：
        1) 阶段1 原生模块名（如「日记贴纸模板」）→ 精确匹配 module 字段
        2) 细分后的子模块名（如「日记贴纸模板-删除」）→ 剥离「-来源页」后缀匹配父模块，
           并按来源页过滤出该子模块对应的 fused 条目
        """
        if not self.prototype.extracted_json:
            return []
        try:
            data = json.loads(self.prototype.extracted_json)
        except Exception:
            return []
        fused = data.get('fused_requirements') or []
        if not isinstance(fused, list):
            return []
        base = mod_name
        sub_page = None
        if '-' in mod_name:
            base, _, sub_page = mod_name.rpartition('-')
        rel = [x for x in fused if isinstance(x, dict) and (x.get('module') or '').strip() == base]
        if sub_page and rel:
            rel = [x for x in rel if x.get('source_pages') and str(x.get('source_pages')[0]) == sub_page]
        return rel


    def _split_heavy_module_by_fused(self, modules: list) -> list:
        """对「细节特别多」的模块做再细分，缓解 P2 单次生成超容导致的漏子功能。

        背景：阶段1 会把多个页面（如贴纸的 切换模板/删除/添加/编辑/分享）锁成 1 个业务模块，
        P1「阶段1对齐铁律」强制保留该粗粒度模块名，导致 P2 一次要吞几十条 fused 需求，
        max_tokens 装不下 → LLM 聚焦主流程、静默丢弃删除/添加等子功能。

        本方法：对 fused 条目数超过阈值的模块，按其 fused 条目的 feature/source 聚类拆成子模块，
        （类似部署前的细粒度拆分），P2 将逐个细模块生成，避免超容漏项。
        父模块名保留（作为统一前缀），不破坏阶段1 业务语义。
        """
        threshold = 12  # 单模块 fused 条目超过该值则细分
        if not modules:
            return modules

        out = []
        for mod in modules:
            if not isinstance(mod, dict):
                out.append(mod)
                continue
            name = str(mod.get('name', '') or '').strip()
            rel = self._fused_entries_for_module(name)
            if len(rel) < threshold:
                out.append(mod)
                continue

            # 按 source_pages 首个来源页聚类（删除/添加/编辑/分享/切换模板...）
            groups = {}
            for r in rel:
                pages = r.get('source_pages') or []
                key = str(pages[0]) if isinstance(pages, list) and pages else '其他'
                groups.setdefault(key, []).append(r)

            # 生成子模块：父模块名 + 来源页作为子模块标识
            sub_modules = []
            for i, (page_key, entries) in enumerate(groups.items(), 1):
                sub_name = f"{name}-{page_key}" if page_key != '其他' else f"{name}-其他{i}"
                sub_features = [e.get('feature', '') for e in entries if isinstance(e, dict) and e.get('feature')]
                sub = {
                    'name': sub_name,
                    'priority': mod.get('priority', 'P0'),
                    'sub_pages': [page_key] if page_key != '其他' else [],
                    'features': sub_features or [],
                    'risks': mod.get('risks', []),
                    'estimated_testcases': max(len(entries) * 2, 5),
                    'estimated_smoke': 1,
                    '_parent_module': name,
                    '_fused_source': page_key,
                    '_fused_count': len(entries),
                }
                sub_modules.append(sub)

            if len(sub_modules) <= 1:
                # 聚类没有区分度（几乎全挤在一个来源页），退回原模块，交由 P2 分批处理
                out.append(mod)
                continue

            self._log(f'  ⚙️ 模块[{name}] 细节过多（{len(rel)} 条 fused），细分为 {len(sub_modules)} 个子模块：'
                      + ', '.join(s['name'] for s in sub_modules))
            out.extend(sub_modules)

        return out

    def _source_decision_tables(self):
        """Return decision tables from vision extraction as authoritative source data."""
        if not self.prototype.extracted_json:
            return []
        try:
            data = json.loads(self.prototype.extracted_json)
        except (TypeError, ValueError):
            return []
        tables = []
        for page in data.get('pages') or []:
            for artifact in page.get('visual_artifacts') or []:
                if not isinstance(artifact, dict) or artifact.get('artifact_type') != 'decision_table':
                    continue
                table = json.loads(json.dumps(artifact, ensure_ascii=False))
                table.setdefault('source_page', f"第{page.get('page_no')}页")
                table.setdefault('name', table.get('title') or table.get('artifact_id') or '决策表')
                tables.append(table)
        return tables

    def _source_visual_structures(self):
        """Return all non-trivial visual structures with page traceability."""
        if not self.prototype.extracted_json:
            return []
        try:
            data = json.loads(self.prototype.extracted_json)
        except (TypeError, ValueError):
            return []
        trivial = {'ui', 'annotation'}
        structures = []
        for page in data.get('pages') or []:
            for artifact in page.get('visual_artifacts') or []:
                if not isinstance(artifact, dict) or artifact.get('artifact_type') in trivial:
                    continue
                item = json.loads(json.dumps(artifact, ensure_ascii=False))
                item.setdefault('source_page', f"第{page.get('page_no')}页")
                item.setdefault('source_artifact_id', item.get('artifact_id'))
                structures.append(item)
        return structures

    def _restore_authoritative_decision_tables(self, parsed):
        """Keep LLM module association, but never trust it to rewrite visual matrix cells."""
        source_tables = self._source_decision_tables()
        if not isinstance(parsed, dict) or not source_tables:
            return parsed
        generated = {
            item.get('source_artifact_id') or item.get('artifact_id'): item
            for item in (parsed.get('decision_tables') or []) if isinstance(item, dict)
        }
        restored = []
        for source in source_tables:
            artifact_id = source.get('artifact_id')
            enriched = generated.get(artifact_id) or {}
            table = dict(source)
            table['source_artifact_id'] = artifact_id
            if enriched.get('related_module'):
                table['related_module'] = enriched['related_module']
            restored.append(table)
        parsed['decision_tables'] = restored
        return parsed

    def _restore_authoritative_visual_structures(self, parsed):
        """Preserve source structures; LLM may only enrich their module association/name."""
        if not isinstance(parsed, dict):
            return parsed
        source_items = self._source_visual_structures()
        generated_items = []
        for key in ('visual_structure_links', 'visual_structures', 'state_matrices', 'decision_tables'):
            generated_items.extend(parsed.get(key) or [])
        generated = {
            item.get('source_artifact_id') or item.get('artifact_id'): item
            for item in generated_items if isinstance(item, dict)
        }
        modules = [item for item in (parsed.get('modules') or []) if isinstance(item, dict)]
        restored = []
        for source in source_items:
            artifact_id = source.get('artifact_id')
            enrichment = generated.get(artifact_id) or {}
            item = dict(source)
            item['source_artifact_id'] = artifact_id
            if enrichment.get('name'):
                item['name'] = enrichment['name']
            source_page = str(item.get('source_page') or '')
            page_candidates = [
                module.get('name') for module in modules
                if source_page and source_page in [str(x) for x in (module.get('source_locations') or [])]
            ]
            proposed = enrichment.get('related_module')
            if proposed in page_candidates:
                item['related_module'] = proposed
            elif len(page_candidates) == 1:
                item['related_module'] = page_candidates[0]
            elif proposed:
                item['related_module'] = proposed
                item['module_association_warning'] = '所属模块未通过来源页交叉校验'
            restored.append(item)
        parsed['visual_structures'] = restored
        parsed['state_matrices'] = [
            item for item in restored if item.get('artifact_type') == 'state_matrix'
        ]
        return parsed

    # ---------- 项目知识库（辅助生成 + 自适应闭环）----------
    def _kb_context(self, query_hint: str = '') -> str:
        """读取本项目知识库上下文，按 query_hint 做语义检索 top-3 最相关片段。
        query_hint 为空时退化为全量读取（兼容旧调用）；非空时走 RAG 精准检索。"""
        cache_key = f'_kb_cache_{hash(query_hint)}'
        if getattr(self, cache_key, None) is not None:
            return getattr(self, cache_key)

        ctx = ''
        try:
            if not self.prototype.project_id:
                return ''
            from apps.projects.models import Project
            from apps.requirement_analysis.models import AIModelService
            project = Project.objects.filter(id=self.prototype.project_id).first()
            if not project:
                return ''

            if query_hint:
                # RAG 精准检索：按当前模块/测试点语义检索 top-3
                ctx = AIModelService.build_knowledge_context_from_project(
                    project, query_text=query_hint, max_chunks=3) or ''
            else:
                # 全量读取（兼容旧调用）
                ctx = AIModelService.build_knowledge_context_from_project(
                    project, query_text=self._source_text()) or ''
        except Exception as e:
            logger.warning(f'读取项目知识库失败（降级为无知识库）: {e}')
            ctx = ''
        setattr(self, cache_key, ctx)
        return ctx

    def _kb_suffix(self, query_hint: str = '') -> str:
        """拼接到各阶段 prompt 末尾的知识库参考段（无知识库时返回空串）。
        query_hint: 可选，用于按需精准检索相关片段。"""
        ctx = self._kb_context(query_hint=query_hint)
        if not ctx:
            return ''
        return (
            "\n\n### 项目知识库参考\n"
            + ctx
            + "\n（请结合上述项目业务背景与既有测试约束来辅助本次分析与生成；"
              "不要重复知识库中已明确的内容，聚焦于本次需求新增/变化的部分）"
        )

    def _build_focused_split_prompt(self, name: str, expected_names, expected_module_list: str) -> str:
        """为【单个】遗漏模块构造聚焦补全 prompt。

        关键治本思路：整列拆分时，LLM 常在长文本中被主要模块淹没而主动删除次要模块
        （即便已把 name 预填进骨架也会整项删掉）。改为对每个遗漏模块单独发一次
        「只生成这一个」的聚焦调用——单任务场景下 LLM 不会被其他模块挤掉注意力，
        漏拆率从约 50% 降到接近 0。
        """
        single_skeleton = '\n'.join([
            'modules:',
            f'  - name: {name}',
            '    sub_pages:',
            '      - <根据需求摘要填入该模块的页面/子流程>',
            '    priority: <P0/P1/P2>',
            '    features:',
            '      - <该模块核心功能1>',
            '      - <该模块核心功能2>',
            '    entry_path: |',
            '      <APP内入口路径>',
            '    core_data: |',
            '      <核心数据>',
            '    risks:',
            '      - <风险点，可为空>',
            '    estimated_testcases: <5-50>',
            '    estimated_smoke: <1-5>',
        ])
        focus_instruction = (
            f'【单次聚焦模式·最高优先级】本次你只需输出模块「{name}」这【一个】拆分项，'
            f'禁止输出其他模块。其余阶段1业务模块（{"、".join(expected_names)}）已由其他步骤处理，'
            f'你只需专注、基于上方需求摘要把「{name}」这一个模块补全。'
        )
        return render_prompt(
            P1_MODULE_SPLIT,
            requirement_yaml=self.prototype.requirement_summary,
            expected_module_list=expected_module_list,
            module_skeleton=single_skeleton,
            focus_instruction=focus_instruction,
        ) + self._kb_suffix()


    @_timed_stage('阶段1 结构化')
    def run_struct(self):
        self.prototype.status = 'structuring'
        self.prototype.save(update_fields=['status'])
        self._log('开始需求结构化分析...')
        text = self._source_text()
        prompt = render_prompt(P0_REQUIREMENT_STRUCT, requirement_text=text) + self._kb_suffix()
        out = self._llm(self.analyzer_config, prompt, max_tokens=8000, temperature=0)
        parsed = _parse_yaml(_extract_block(out, 'yaml'))
        if isinstance(parsed, dict):
            missing_sections = [
                k for k in ('ambiguous_points', 'missing_points', 'boundary_points') if k not in parsed
            ]
            if missing_sections:
                self._log(f'结构化输出缺少 {"、".join(missing_sections)} 字段，自动重试一次...')
                retry_prompt = (
                    prompt
                    + '\n\n【格式校验反馈】你上一次输出缺少以下字段：'
                    + '、'.join(missing_sections)
                    + '。请重新输出完整 YAML，这三个字段必须出现（确实没有时写空列表 []），并严格按模板结构输出。'
                )
                out = self._llm(self.analyzer_config, retry_prompt, max_tokens=8000, temperature=0)
                parsed = _parse_yaml(_extract_block(out, 'yaml'))
        if isinstance(parsed, dict):
            parsed = self._restore_authoritative_decision_tables(parsed)
            parsed = self._restore_authoritative_visual_structures(parsed)
            parsed, merge_count, invalid_count = _postprocess_requirement_summary(
                parsed, text
            )
            import yaml
            out = yaml.safe_dump(
                parsed, allow_unicode=True, sort_keys=False, width=120
            )
            if merge_count:
                self._log(f'结构化后处理：合并 {merge_count} 个重复模块')
            if invalid_count:
                self._log(f'证据校验：{invalid_count} 项未匹配原始页面，已标记 evidence_valid=false')
        self.prototype.requirement_summary = out
        self.prototype.status = 'extracted'
        self.prototype.current_stage = 1
        self.prototype.save()
        self._advance_selected_pages(1)
        self._log('需求结构化完成，已生成摘要')
        return out

    def _converged_conclusions(self) -> list:
        """读取阶段1已收敛为确定结论的歧义点清单（供阶段2/阶段3避免重复追问）。"""
        try:
            import yaml as _yaml
            data = _yaml.safe_load(self.prototype.requirement_summary or '{}') or {}
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        return data.get('converged_conclusions') or []

    # ---------- 阶段2：需求澄清 ----------
    @_timed_stage('阶段2 澄清')
    def run_clarify(self):
        self.prototype.status = 'clarifying'
        self.prototype.save(update_fields=['status'])
        self._log('开始需求澄清（识别模糊/缺失/边界）...')
        # 阶段1摘要决定已确认范围；原始内容只用于证据核对和查漏，
        # 避免摘要遗漏被继续放大，也避免把用户已排除的需求重新带回流程。
        structured = (self.prototype.requirement_summary or '').strip()
        source_text = self._source_text().strip()
        confirmed_scope = structured or source_text
        scope_note = (
            '结构化摘要是本阶段的需求范围边界。原始内容仅用于验证摘要是否有遗漏或无依据表述；'
            '不要针对摘要中已经排除、标记不做或超出范围的功能提问。'
            if structured and source_text else
            '当前没有独立的结构化摘要，请直接基于原始内容审查。'
        )
        converged = self._converged_conclusions()
        converged_note = ''
        if converged:
            converged_note = (
                '\n### 已收敛结论（阶段1已按默认假设确定，直接采纳、不得重复追问）\n'
                + json.dumps(converged, ensure_ascii=False)
                + '\n\n'
            )
        prompt = (
            '你是一名严格、保守的需求审查员。你的任务不是补写需求，而是对照原始内容审查'
            '已确认范围中的模糊点、完成当前流程所必需但缺失的信息，以及功能边界。\n\n'
            f'===== 已确认的结构化范围 =====\n{confirmed_scope}\n===== 范围结束 =====\n\n'
            f'===== 原始原型/需求内容（仅用于证据核对与查漏） =====\n'
            f'{source_text}\n===== 原始内容结束 =====\n\n'
            f'### 范围规则\n{scope_note}\n\n'
            f'{converged_note}'
            '### 审查规则\n'
            '1. 每个问题必须能指向具体页面、标注、字段或结构化条目。\n'
            '2. 原文明确写出的内容不是缺失点；不得重复追问。\n'
            '3. 只有完成当前已确认流程确实必需的信息，才能判为缺失点。\n'
            '4. 如果结构化摘要遗漏了范围内的原文，audit_kind 写 "结构化遗漏"。\n'
            '5. 如果结构化摘要中的表述在原文找不到依据，audit_kind 写 "结构化无依据"。\n'
            '6. **明确边界值/默认值/排序规则/异常分支/跨页面一致性**等若有歧义或隐含，必须提出。\n'
            '7. 严格避免凭空编造，但允许在已确认范围内指出"待确认的合理假设"。\n'
            '8. 至少输出 2 条问题；只有明确找不到任何问题时才能输出空数组（极少）。\n\n'
            '### 输出要求\n'
            '**必须且仅**输出一个 JSON 数组，不要使用 markdown 代码块或附加说明。'
            '数组每项字段如下：\n'
            '- type: 仅限 "模糊点" / "缺失点" / "边界点"\n'
            '- audit_kind: 仅限 "原文歧义" / "结构化遗漏" / "结构化无依据" / "信息缺失" / "边界不清"\n'
            '- location: 具体页面、标注、字段或结构化条目\n'
            '- evidence: 支持判断的简短原文；找不到直接依据时写 "未找到直接原文"\n'
            '- issue: 客观描述问题，不得把推断写成事实\n'
            '- suggested_question: 可由产品明确回答的单一问题\n'
            '- priority: "高" / "中" / "低"\n'
            '- impact: 受影响的测试场景或模块\n\n'
            '示例（仅表示格式，不得复制内容）：\n'
            '[{"type":"缺失点","audit_kind":"信息缺失","location":"登录页/密码字段",'
            '"evidence":"原文仅写登录密码","issue":"密码规则未说明",'
            '"suggested_question":"密码允许的长度和字符范围是什么？","priority":"中","impact":"登录校验"}]'
        )
        out = self._llm(self.analyzer_config, prompt, max_tokens=6000, temperature=0)
        # 先剥除 markdown code block 包裹（temperature=0 下模型更倾向用 ```json 包裹）
        stripped = _extract_block(out, 'json')
        if not stripped:
            stripped = _extract_block(out, None)
        try:
            clarify_items = json.loads(stripped or out)
        except Exception:
            clarify_items = None
        if isinstance(clarify_items, list):
            invalid_count = 0
            for item in clarify_items:
                if not isinstance(item, dict):
                    continue
                valid = _validate_evidence(item.get('evidence'), source_text)
                item['evidence_valid'] = valid
                invalid_count += int(not valid)
            out = json.dumps(clarify_items, ensure_ascii=False, indent=2)
            if invalid_count:
                self._log(f'澄清证据校验：{invalid_count} 项未匹配原始页面')
        self.prototype.clarification_log = out
        self.prototype.status = 'extracted'
        self.prototype.current_stage = 2
        self.prototype.save()
        self._advance_selected_pages(2)
        self._log('需求澄清完成')
        return out

    # ---------- 阶段3：用例设计（核心）----------
    def run_design(self):
        """完整跑阶段3（兼容旧入口）：第一段测试点合并 + 第二段用例生成，一口气到底。"""
        self.run_design_phase1()
        return self.run_design_phase2()

    # ---------- 阶段3 第一段：模块拆分→测试点→风险→PCI→三路合并 ----------
    @_timed_stage('阶段3-1 测试点合并')
    def run_design_phase1(self):
        """产出 module_split / risks_json / pci_json / final_testpoints_json，
        完成后 status='testpoints_ready'，等待人工确认/编辑测试点后再调 phase2 生成用例。"""
        self.prototype.status = 'designing'
        self.prototype.save(update_fields=['status'])
        self._log('开始用例设计（阶段3 · 第一段：测试点合并）...')

        # 3.1 模块拆分
        self._log('3.1 正在拆分模块...')
        # 治本修复：提前提取阶段1已锁定的业务模块清单，作为硬约束注入拆分 prompt，
        # 防止 LLM 在长文本中被细节淹没而漏拆相对次要的业务模块。
        summary_yaml = _parse_yaml(_extract_block(self.prototype.requirement_summary or '', 'yaml')) or {}
        summary_modules = summary_yaml.get('modules', []) if isinstance(summary_yaml, dict) else []
        expected_names = [m.get('name', '').strip() for m in summary_modules if isinstance(m, dict) and m.get('name')]
        if expected_names:
            expected_module_list = '\n'.join(f'- {name}' for name in expected_names)
            # 治本修复（预填骨架）：把阶段1锁定的模块名直接写进输出 YAML 的 modules: 列表，
            # 逼 LLM 做「补全」而非「自由决定列哪些模块」。completion 偏置远强于指令，
            # 可彻底规避 LLM 在长输入前忽略铁律而漏拆次要模块的问题。
            skeleton_lines = ['modules:']
            for name in expected_names:
                skeleton_lines.append(f'  - name: {name}')
                skeleton_lines.append('    sub_pages:')
                skeleton_lines.append('      - <待补充：根据需求摘要填入该模块的页面/子流程>')
                skeleton_lines.append('    priority: <P0/P1/P2>')
                skeleton_lines.append('    features:')
                skeleton_lines.append('      - <待补充：该模块核心功能1>')
                skeleton_lines.append('      - <待补充：该模块核心功能2>')
                skeleton_lines.append('    entry_path: |')
                skeleton_lines.append('      <待补充：APP内入口路径>')
                skeleton_lines.append('    core_data: |')
                skeleton_lines.append('      <待补充：核心数据>')
                skeleton_lines.append('    risks:')
                skeleton_lines.append('      - <待补充，可为空>')
                skeleton_lines.append('    decision_tables:')
                skeleton_lines.append('      - <若该模块有decision_table则原样复制，否则删除此字段>')
                skeleton_lines.append('    visual_structures:')
                skeleton_lines.append('      - <若该模块有visual_structure则原样复制，否则删除此字段>')
                skeleton_lines.append('    estimated_testcases: <待补充 5-50>')
                skeleton_lines.append('    estimated_smoke: <待补充 1-5>')
            module_skeleton = '\n'.join(skeleton_lines)
        else:
            expected_module_list = '（阶段1未提取到明确模块清单，请基于需求摘要自行识别全部业务模块）'
            module_skeleton = 'modules:\n  - name: <待补充：基于需求摘要自行识别全部业务模块，逐个列出>'
        split_prompt = render_prompt(
            P1_MODULE_SPLIT,
            requirement_yaml=self.prototype.requirement_summary,
            expected_module_list=expected_module_list,
            module_skeleton=module_skeleton,
        ) + self._kb_suffix(query_hint=self.prototype.requirement_summary[:500] if self.prototype.requirement_summary else '')
        split_out, split_yaml, modules, missing_modules = '', {}, [], []
        if expected_names:
            # 整列 LLM 拆分（单次）。覆盖交由下方「单模块聚焦」安全网保证——
            # 实测整列重试仍会在长文本中被主要模块淹没而漏拆次要模块，不可依赖。
            split_out = self._llm(self.analyzer_config, split_prompt, max_tokens=6000, temperature=0, timeout=600)
            split_yaml = _parse_yaml(_extract_block(split_out, 'yaml')) or {}
            modules = split_yaml.get('modules', []) if isinstance(split_yaml, dict) else []
            actual_names = [m.get('name', '').strip() for m in modules if isinstance(m, dict) and m.get('name')]
            missing_modules = [
                name for name in expected_names
                if not any(name in actual or actual in name for actual in actual_names)
            ]
            # 治本安全网：对仍遗漏的模块逐个做「单模块聚焦」补全（每次只问一个模块，
            # LLM 不会被其他模块挤掉注意力）；聚焦仍失败的则合成占位模块，保证覆盖不阻断下游。
            for name in list(missing_modules):
                focused_prompt = self._build_focused_split_prompt(name, expected_names, expected_module_list)
                fout = self._llm(self.analyzer_config, focused_prompt, max_tokens=3000, temperature=0)
                fy = _parse_yaml(_extract_block(fout, 'yaml')) or {}
                fm = [m for m in (fy.get('modules', []) if isinstance(fy, dict) else [])
                      if isinstance(m, dict) and m.get('name')]
                if fm:
                    fm[0]['name'] = name  # 强制 name 与阶段1一致
                    modules.append(fm[0])
                    self._log(f'聚焦补全模块：{name}')
                else:
                    modules.append({
                        'name': name, 'priority': 'P1', 'sub_pages': [], 'features': [],
                        'risks': [], 'estimated_testcases': 5, 'estimated_smoke': 1,
                        '_synthesized': True,
                    })
                    self._log(f'警告：模块「{name}」LLM 无法生成，已合成占位模块（覆盖已保证，内容需人工确认）')
                missing_modules = [n for n in missing_modules if n != name]
        else:
            # 无阶段1清单：维持原整列逻辑（无强制覆盖目标）
            for attempt in range(2):  # 首次拆分 + 遗漏时自动重试一次
                prompt = split_prompt
                if attempt and missing_modules:
                    prompt += (
                        '\n\n【重要·覆盖校验反馈】你上一次拆分遗漏了以下模块，'
                        '本次输出的 modules 列表必须包含它们（模块名称保持与下列名称一致，不得改名或合并省略）：'
                        + '、'.join(missing_modules)
                    )
                split_out = self._llm(self.analyzer_config, prompt, max_tokens=6000, temperature=0)
                split_yaml = _parse_yaml(_extract_block(split_out, 'yaml')) or {}
                modules = split_yaml.get('modules', []) if isinstance(split_yaml, dict) else []
                actual_names = [m.get('name', '').strip() for m in modules if isinstance(m, dict) and m.get('name')]
                missing_modules = [
                    name for name in expected_names
                    if not any(name in actual or actual in name for actual in actual_names)
                ]
                if not missing_modules:
                    break
                if attempt == 0:
                    self._log('模块覆盖校验：拆分遗漏 ' + '、'.join(missing_modules) + '，自动补全重试一次...')
        decision_tables = (
            summary_yaml.get('decision_tables', [])
            if isinstance(summary_yaml, dict) else []
        ) or self._source_decision_tables()
        visual_structures = (
            summary_yaml.get('visual_structures', [])
            if isinstance(summary_yaml, dict) else []
        ) or self._source_visual_structures()
        for table in decision_tables:
            related = _normalize_evidence_text(table.get('related_module'))
            candidates = [
                module for module in modules
                if related and (
                    related in _normalize_evidence_text(module.get('name'))
                    or _normalize_evidence_text(module.get('name')) in related
                )
            ]
            if not candidates and len(modules) == 1:
                candidates = modules
            for module in candidates:
                module.setdefault('decision_tables', []).append(table)
        for structure in visual_structures:
            if structure.get('artifact_type') == 'decision_table':
                continue
            related = _normalize_evidence_text(structure.get('related_module'))
            candidates = [
                module for module in modules
                if related and (
                    related in _normalize_evidence_text(module.get('name'))
                    or _normalize_evidence_text(module.get('name')) in related
                )
            ]
            if not candidates and len(modules) == 1:
                candidates = modules
            for module in candidates:
                module.setdefault('visual_structures', []).append(structure)
        # 模块再细分：对细节特别多的阶段1模块（如贴纸的 切换/删除/添加/编辑 被锁成 1 个粗模块）
        # 按 fused 来源聚类拆成细模块，避免 P2 单次生成超容漏子功能（方案2）
        if not missing_modules:
            sub_modules = self._split_heavy_module_by_fused(modules)
            if len(sub_modules) != len(modules):
                modules = sub_modules
                # 重新序列化回 module_split
                if isinstance(split_yaml, dict):
                    split_yaml['modules'] = modules
                import yaml
                split_out = yaml.safe_dump(split_yaml, allow_unicode=True, sort_keys=False, width=120)
        self.prototype.module_split = split_out

        if missing_modules:
            self.prototype.status = 'failed'
            self.prototype.error_message = (
                '模块覆盖校验失败，模块拆分遗漏：' + '、'.join(missing_modules)
                + '。请修正模块拆分后再生成测试点。'
            )
            self.prototype.save(update_fields=['module_split', 'status', 'error_message'])
            self._log(self.prototype.error_message)
            return {'modules': len(modules), 'final_testpoints': 0, 'error': 'module_coverage_failed',
                    'missing_modules': missing_modules, 'phase': 1}
        self._log(f'3.1 模块拆分完成，共 {len(modules)} 个模块')


        all_final_tps = []      # 全部模块的最终测试点
        all_risks = []
        all_pci = []
        dedup_audit = []

        for idx, mod in enumerate(modules, 1):
            mod_name = mod.get('name', '未命名模块')
            self._log(f'3.2 开始处理模块[{idx}/{len(modules)}] {mod_name} ...')
            mod_ctx = json.dumps(mod, ensure_ascii=False)
            try:
                # 3.3 基础测试点 (draft)
                mod_features = mod.get('features', [])
                feature_count_hint = ''
                if isinstance(mod_features, list) and mod_features:
                    feature_count_hint = (
                        f'\n\n【覆盖要求】本模块有 {len(mod_features)} 个新增/变更功能点（features），你必须覆盖这些功能点。'
                        f'此外还需覆盖：① 该模块修改后可能影响的老功能回归验证；② 跨模块联动影响。'
                        f'模块 features 列表：\n{chr(10).join("- " + str(f) for f in mod_features)}'
                        f'\n请确保生成的 test_points 涵盖功能测试 + 回归验证 + 联动场景，不要生成脱离本模块具体场景的通用模板。'
                    )
                # 注入对应原型的页面 text（按模块名模糊匹配），让 LLM 看到便签/批注等具体需求
                page_text_hint = self._match_page_text_for_module(mod_name, mod)
                # 方案3：P2 自动分批。若本模块 fused 条目过多，拆成多批分别生成测试点再合并，
                # 避免单次 max_tokens=6000 装不下导致 LLM 聚焦主流程、静默丢弃删除/添加等子功能。
                fused_rel = self._fused_entries_for_module(mod_name)
                batch_size = 15  # 每批最多注入的 fused 条目数
                if len(fused_rel) > batch_size:
                    # 分批：每批取一个连续切片，单独生成该子集的测试点
                    batches = [fused_rel[i:i + batch_size] for i in range(0, len(fused_rel), batch_size)]
                    draft_tps = []
                    for bi, batch in enumerate(batches, 1):
                        batch_hint = (
                            f'\n\n【该模块已提取的结构化需求（第 {bi}/{len(batches)} 批，共 {len(batch)} 条）】'
                            f'请严格基于以下具体需求生成该批测试点，不要泛化或臆造，也不要把本批内容漏掉：\n'
                            + '\n'.join(
                                f'{j}. 【{r.get("feature", "")}】{r.get("interaction", "")}'
                                f'（证据等级：{r.get("evidence", "")}）'
                                for j, r in enumerate(batch, 1)
                            )
                        )
                        batch_prompt = render_prompt(P2_TESTPOINT_GEN, module_info_yaml=mod_ctx) + feature_count_hint + batch_hint + self._kb_suffix(query_hint=mod_name)
                        tp_out = self._llm(self.analyzer_config, batch_prompt, max_tokens=6000, temperature=0)
                        tp_yaml = _parse_yaml(_extract_block(tp_out, 'yaml')) or {}
                        batch_tps = tp_yaml.get('test_points', []) if isinstance(tp_yaml, dict) else []
                        batch_tps = [t for t in batch_tps if isinstance(t, dict)]
                        draft_tps.extend(batch_tps)
                        self._log(f'  模块[{mod_name}] 第{bi}批（{len(batch)}条fused）生成 {len(batch_tps)} 条测试点')
                    self._log(f'  模块[{mod_name}] 分批生成汇总：{len(draft_tps)} 条测试点（{len(fused_rel)}条fused / 每批{batch_size}条）')
                else:
                    tp_prompt = render_prompt(P2_TESTPOINT_GEN, module_info_yaml=mod_ctx) + feature_count_hint + page_text_hint + self._kb_suffix(query_hint=mod_name)
                    tp_out = self._llm(self.analyzer_config, tp_prompt, max_tokens=6000, temperature=0)
                    tp_yaml = _parse_yaml(_extract_block(tp_out, 'yaml')) or {}
                    draft_tps = tp_yaml.get('test_points', []) if isinstance(tp_yaml, dict) else []
                    self._log(f'  模块[{mod_name}] 基础测试点生成：{len(draft_tps)} 条')
                if isinstance(mod_features, list) and len(mod_features) > 0 and len(draft_tps) < max(len(mod_features) * 2, 5):
                    self._log(f'  ⚠️ 模块[{mod_name}] 测试点({len(draft_tps)})偏少（功能点{len(mod_features)}个），可能覆盖不足或产生泛化输出')
                # 过滤非 dict 的测试点（LLM 偶发返回字符串元素）
                draft_tps = [t for t in draft_tps if isinstance(t, dict)]
                # 空结果重试：LLM 偶发返回空/无效格式导致该模块无基础测试点，重试一次（精简 prompt，强调必须输出具体 YAML）
                if not draft_tps:
                    self._log(f'  ⚠️ 模块[{mod_name}] 基础测试点为空，重试一次...')
                    retry_prompt = (
                        f'为模块「{mod_name}」生成测试点（test_points），必须输出有效的 YAML 列表，禁止返回空。\n'
                        f'模块信息：\n{mod_ctx}\n'
                        f'要求：每个测试点必须是 dict（含 title/type/priority/description/category），数量 5-20 条，'
                        f'基于模块的具体功能，不要泛化。\n'
                        f'输出格式（直接输出 YAML）：\nmodule: {mod_name}\ntest_points:\n  - id: TP_{mod_name}_001\n    title: ...\n    type: 功能\n    category: main_flow\n    priority: P0\n    description: ...'
                    ) + page_text_hint
                    try:
                        tp_out2 = self._llm(self.analyzer_config, retry_prompt, max_tokens=6000, temperature=0)
                        tp_yaml2 = _parse_yaml(_extract_block(tp_out2, 'yaml')) or {}
                        draft_tps = tp_yaml2.get('test_points', []) if isinstance(tp_yaml2, dict) else []
                        draft_tps = [t for t in draft_tps if isinstance(t, dict)]
                        self._log(f'  模块[{mod_name}] 重试后基础测试点生成：{len(draft_tps)} 条')
                    except Exception as _re:
                        self._log(f'  模块[{mod_name}] 重试失败: {_re}')
                for t in draft_tps:
                    t['source'] = ['draft']
                    # 后处理：LLM 经常漏 category 字段，按 type/priority 推断补全
                    cat = (t.get('category') or '').strip()
                    if not cat:
                        tp_type = t.get('type', '')
                        cat_map = {'功能': 'main_flow', '边界': 'boundary',
                                   '异常': 'exception', 'UI': 'UI', '权限': 'permission',
                                   '性能': 'performance', '兼容': 'compatibility'}
                        default = 'main_flow' if str(t.get('priority', '')).upper() == 'P0' else 'branch_flow'
                        t['category'] = cat_map.get(tp_type, default)

                # 3.3.5 风险识别 (risk)
                risk_prompt = render_prompt(P5_RISK_IDENTIFY,
                                            test_points_json=json.dumps(draft_tps, ensure_ascii=False))
                risk_out = self._llm(self.analyzer_config, risk_prompt, max_tokens=6000, temperature=0)
                risk_json = _parse_json(_extract_block(risk_out, 'json')) or {}
                all_risks.append({'module': mod_name, 'data': risk_json})
                risk_ext = []
                for rp in risk_json.get('risk_points', []):
                    if not isinstance(rp, dict):
                        continue
                    for etp in rp.get('extended_test_points', []):
                        if not isinstance(etp, dict):
                            continue
                        ecat = (etp.get('category') or '').strip() or 'exception'
                        risk_ext.append({
                            'id': etp.get('id', f"{mod_name}-EXT"),
                            'title': etp.get('title', ''),
                            'description': etp.get('description', ''),
                            'priority': etp.get('priority_hint', 'P1'),
                            'category': ecat,
                            'source': ['risk'],
                        })

                # 3.3.6 PCI 识别 (pci)
                cross_module_impact = self._extract_module_context(mod_name)
                converged = self._converged_conclusions()
                clarified_qa = []
                for _ci in self.prototype.clarification_items():
                    _cq = (_ci.get('issue') or _ci.get('suggested_question') or '').strip()
                    _ca = str(_ci.get('resolution') or _ci.get('answer') or '').strip()
                    if _cq and _ca:
                        clarified_qa.append(f'Q: {_cq}\nA: {_ca}')
                stage2_text = self.prototype.clarification_log or ''
                if clarified_qa:
                    stage2_text += (
                        '\n\n### 产品已回答的确认结论（以下答案视为已确认需求，'
                        '禁止就同一问题再生成 PCI，不得出现在 pci_list 中）：\n'
                        + '\n'.join(clarified_qa)
                    )
                pci_prompt = render_prompt(P6_PCI_IDENTIFY,
                                           test_points_json=json.dumps(draft_tps, ensure_ascii=False),
                                           requirement_text=self._source_text(),
                                           stage2_issues=stage2_text,
                                           cross_module_impact=cross_module_impact or '无（该模块未分析出跨模块影响）',
                                           converged_conclusions=(
                                               json.dumps(converged, ensure_ascii=False) if converged else '无'
                                           ))
                pci_out = self._llm(self.analyzer_config, pci_prompt, max_tokens=6000, temperature=0)
                pci_json = _parse_json(_extract_block(pci_out, 'json')) or {}
                if not pci_json:
                    pci_json = _parse_yaml(_extract_block(pci_out, 'yaml')) or {}
                if not pci_json:
                    logger.warning(f'模块[{mod_name}] P6 JSON 解析失败，自动重试一次...')
                    self._log(f'  模块[{mod_name}] P6 输出解析失败，自动重试...')
                    repair_prompt = (
                        pci_prompt
                        + '\n\n【格式校验反馈】你上一次输出的 JSON 无法解析（可能混入解释文字、被截断或缺少 pci_list）。'
                        '请重新输出完整 JSON，严格按模板结构，只输出 JSON 本身，不要任何前言或结尾说明。'
                    )
                    pci_out = self._llm(self.analyzer_config, repair_prompt, max_tokens=6000, temperature=0)
                    pci_json = _parse_json(_extract_block(pci_out, 'json')) or {}
                    if not pci_json:
                        pci_json = _parse_yaml(_extract_block(pci_out, 'yaml')) or {}
                # 后处理去重：剔除与已澄清问题（resolution 非空）重复的 PCI 条目
                pci_raw_list = pci_json.get('pci_list') or pci_json.get('data', {}).get('pci_list') or []
                if pci_raw_list:
                    filtered_list, removed_count, removed_items = self._pci_dedup_against_clarifications(
                        pci_raw_list, self.prototype.clarification_log)
                    if removed_count > 0:
                        # 写回 PCI JSON（兼容两种包裹结构）
                        if 'pci_list' in pci_json:
                            pci_json['pci_list'] = filtered_list
                        elif 'data' in pci_json and isinstance(pci_json['data'], dict):
                            pci_json['data']['pci_list'] = filtered_list
                        pci_json['_dedup_removed'] = removed_count
                        pci_json['_dedup_removed_items'] = removed_items
                        self._log(f'PCI 去重：从已澄清问题中剔除了 {removed_count} 条重复 PCI（{mod_name}）')
                all_pci.append({'module': mod_name, 'data': pci_json})

                # 3.3.7 三路合并去重（向量去重 + p7 最终化）
                combined = []
                for t in (draft_tps + risk_ext):
                    combined.append({
                        'id': t.get('id', f"{mod_name}-{len(combined)}"),
                        'title': t.get('title', ''),
                        'description': t.get('description', ''),
                        'priority': t.get('priority', 'P1'),
                        'source': t.get('source', ['draft']),
                    })
                self._log(f'  模块[{mod_name}] 合并前：{len(draft_tps)} draft + {len(risk_ext)} risk = {len(combined)}')
                deduped, dedup_count, audit = self._vector_dedup(combined)
                for record in audit:
                    record.update({'stage': 'pre_merge', 'module': mod_name})
                dedup_audit.extend(audit)
                merge_prompt = render_prompt(
                    P7_MERGE_DEDUP,
                    draft_testpoints=json.dumps(deduped, ensure_ascii=False),
                    risk_extended_testpoints='[]',
                    pci_blocked_scenarios=json.dumps(
                        [p for p in pci_json.get('pci_list', [])], ensure_ascii=False),
                )
                merge_out = self._llm(self.analyzer_config, merge_prompt, max_tokens=8000, temperature=0)
                merge_json = _parse_json(_extract_block(merge_out, 'json')) or {}
                # 兼容部分模型返回 YAML 而非 JSON 的情况
                if not merge_json:
                    merge_json = _parse_yaml(_extract_block(merge_out, 'yaml')) or {}
                final_tps = merge_json.get('test_points', []) if isinstance(merge_json, dict) else []
                # 安全网：若 P7 未按约定返回测试点，但去重后输入非空，则降级使用输入
                if not final_tps and deduped:
                    logger.warning(f'模块[{mod_name}] P7 返回空测试点，降级使用去重后输入({len(deduped)}条)')
                    self._log(f'  模块[{mod_name}] P7 返回空，降级使用去重后输入 {len(deduped)} 条')
                    final_tps = deduped
                for t in final_tps:
                    t['module'] = mod_name
                    # P7 合并后也补全 category（PCI 扩展点经常漏填）
                    cat = (t.get('category') or '').strip()
                    if not cat:
                        tp_type = t.get('type', '')
                        cat_map = {'功能': 'main_flow', '边界': 'boundary',
                                   '异常': 'exception', 'UI': 'UI', '权限': 'permission',
                                   '性能': 'performance', '兼容': 'compatibility'}
                        default = 'main_flow' if str(t.get('priority', '')).upper() == 'P0' else 'branch_flow'
                        t['category'] = cat_map.get(tp_type, default)
                all_final_tps.extend(final_tps)
                logger.info(f'模块[{mod_name}] 三路合并：输入{len(combined)} 去重{dedup_count} 最终{len(final_tps)}')
                self._log(f'  模块[{mod_name}] 合并完成：{len(final_tps)} 测试点')
            except Exception as e:
                logger.error(f'模块[{mod_name}] 测试点合并失败: {e}')
                self._log(f'  模块[{mod_name}] 失败: {e}')
                continue

        # P7 合并后全局二次去重：消除各模块合并可能 reintroduce 的近重复
        # 按 module 分组去重，仅消同模块内的近重复，避免跨模块同功能被误删
        global_dedup = 0
        if self.embedder_config and all_final_tps:
            grouped = {}
            for t in all_final_tps:
                grouped.setdefault(t.get('module', '') or '', []).append(t)
            merged = []
            for mod_name, mod_items in grouped.items():
                deduped, cnt, audit = self._vector_dedup(mod_items)
                for record in audit:
                    record.update({'stage': 'post_merge', 'module': mod_name})
                dedup_audit.extend(audit)
                global_dedup += cnt
                merged.extend(deduped)
            all_final_tps = merged
            if global_dedup:
                self._log(f'  全局二次去重：消除 {global_dedup} 条合并重新引入的近重复')

        # 跨模块 PCI 聚类去重：同一问题在不同模块重复出现（含语义相同但措辞不同）时，标记为重复
        import difflib
        import re as _re

        def _pci_keywords(text):
            """提取 PCI 描述中的核心业务词（去停用词、去常见动词/连接词），用于语义聚类。"""
            if not text:
                return set()
            stops = {'是否', '什么', '如何', '怎么', '需要', '是否需', '确认', '该', '问', '配置',
                     '定义', '明确', '规则', '要求', '存在', '以及', '还是', '及', '与', '并', '或', '问题',
                     '场景', '情况', '展示', '界面', '页面', '中', '的', '和', '个'}
            # 提取 2-6 字中文词（名词/业务概念）
            words = set(_re.findall(r'[\u4e00-\u9fa5]{2,6}', text))
            # 过滤掉停用词，保留有业务含义的词
            return {w for w in words if w not in stops and len(w) >= 2}

        def _pci_similar(a, b, ta, tb, cos=None):
            """判定两条 PCI 的相似等级：
            - 'merge': 高置信重复（字面 >=0.7，或字面 0.55~0.7 且关键词高度重叠，或向量余弦 >=0.85）→ 自动合并
            - 'mark': 中等相似（字面 0.45~0.55，或关键词中等重叠，或向量余弦 >=0.75）→ 标记供人工核对
            - 'none': 不相似
            """
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            ka, kb = _pci_keywords(ta), _pci_keywords(tb)
            shared = ka & kb
            shared_ratio = len(shared) / max(len(ka), 1) if ka else 0
            kw_overlap = len(shared) >= 2 and shared_ratio >= 0.4
            # 高置信重复 → 自动合并
            if ratio >= 0.7 or (ratio >= 0.55 and kw_overlap) or (cos is not None and cos >= 0.85):
                return 'merge', ratio, shared_ratio
            # 中等相似 → 标记保留供人工核对
            if ratio >= 0.45 or (kw_overlap and ratio >= 0.35) or (cos is not None and cos >= 0.75):
                return 'mark', ratio, shared_ratio
            return 'none', ratio, shared_ratio

        # 预计算全部 PCI 描述的向量（余弦相似度捕捉跨模块改写重复）
        _pci_vec_list = []
        _pci_vec_index = {}
        for _mp in all_pci:
            for _pc in (_mp.get('data', {}).get('pci_list') or _mp.get('data', {}).get('data', {}).get('pci_list') or []):
                if isinstance(_pc, dict) and ((_pc.get('description') or '').strip() or (_pc.get('title') or '').strip()):
                    _pci_vec_index[id(_pc)] = len(_pci_vec_list)
                    _pci_vec_list.append((_pc.get('description') or '').strip() or (_pc.get('title') or '').strip())
        _pci_vecs = self._embed(_pci_vec_list) if _pci_vec_list else None
        if _pci_vecs is not None:
            try:
                _varr = np.array(_pci_vecs, dtype=float)
                _varr = _varr / np.clip(np.linalg.norm(_varr, axis=1, keepdims=True), 1e-9, None)
                _pci_vecs = _varr
            except Exception:
                _pci_vecs = None
        _seen_vecs = []  # 代表向量，与 seen_pci_texts 对齐
        seen_pci_texts = []   # 保留组的代表文本
        seen_pci_keywords = []  # 保留组的关键词集合
        merged_count = 0
        marked_count = 0
        merged_items = []
        marked_items = []
        for mod_pci in all_pci:
            pci_list = (mod_pci.get('data', {}).get('pci_list') or mod_pci.get('data', {}).get('data', {}).get('pci_list') or [])
            keep = []
            for pci in pci_list:
                if not isinstance(pci, dict):
                    keep.append(pci)
                    continue
                desc = (pci.get('description') or '').strip()
                text = desc or (pci.get('title') or '')
                if not text:
                    keep.append(pci)
                    continue
                # 判断与之前 PCI（代表）的相似等级
                level = 'none'
                dup_ref = None
                dup_sim = 0
                dup_kw = 0
                for i, prev_text in enumerate(seen_pci_texts):
                    cos = None
                    if _pci_vecs is not None and id(pci) in _pci_vec_index and i < len(_seen_vecs) and _seen_vecs[i] is not None:
                        cos = float(np.dot(_pci_vecs[_pci_vec_index[id(pci)]], _seen_vecs[i]))
                    lv, ratio, kratio = _pci_similar(desc, prev_text, text, prev_text, cos)
                    if lv != 'none':
                        level = lv
                        dup_ref = i
                        dup_sim = round(ratio, 3)
                        dup_kw = round(kratio, 3)
                        break
                if level == 'merge':
                    # 高置信重复 → 真正合并，只保留代表条（当前条剔除）
                    merged_count += 1
                    merged_items.append({'module': mod_pci.get('module'), 'sim': dup_sim, 'kw': dup_kw, 'desc': desc[:100]})
                    # 被合并条不加入 keep，也不作为新代表
                    continue
                elif level == 'mark':
                    # 中等相似 → 标记保留供人工核对
                    pci['_pci_dup'] = True
                    pci['_pci_dup_ref'] = dup_ref
                    pci['_pci_dup_similarity'] = dup_sim
                    marked_count += 1
                    marked_items.append({'module': mod_pci.get('module'), 'sim': dup_sim, 'desc': desc[:100]})
                else:
                    # 不相似 → 作为新代表
                    seen_pci_texts.append(desc)
                    seen_pci_keywords.append(_pci_keywords(text))
                    _seen_vecs.append(_pci_vecs[_pci_vec_index[id(pci)]] if (_pci_vecs is not None and id(pci) in _pci_vec_index) else None)
                keep.append(pci)  # 保留非重复 + 标记条（供人工核对）
            # 写回
            if 'pci_list' in (mod_pci.get('data') or {}):
                mod_pci['data']['pci_list'] = keep
            elif 'data' in mod_pci and isinstance(mod_pci['data'], dict) and 'pci_list' in mod_pci['data'].get('data', {}):
                mod_pci['data']['data']['pci_list'] = keep
        if merged_count:
            self._log(f'  跨模块 PCI 智能合并：合并 {merged_count} 条高置信重复 PCI（仅保留代表，字段已剔除）')
            if merged_items:
                import json as _json
                self._log('  已合并 PCI：' + _json.dumps(merged_items[:10], ensure_ascii=False))
        if marked_count:
            self._log(f'  跨模块 PCI 待核对：标记 {marked_count} 条中等相似 PCI（保留供人工核对，字段 _pci_dup）')
            if marked_items:
                import json as _json
                self._log('  待核对 PCI：' + _json.dumps(marked_items[:10], ensure_ascii=False))

        # 第一段产物落库（测试点合并完成，等待人工确认）
        pci_stats = _normalize_pci_dispositions(all_pci)
        self._log(
            f'PCI 机器收敛：共 {pci_stats["total"]} 条，'
            f'按默认假设收敛 {pci_stats["assumed"]} 条，'
            f'疑似改动产品规则 {pci_stats["suspicious"]} 条，'
            f'跨模块重复合并 {pci_stats["dedup"]} 条，'
            f'需人工确认 {pci_stats["confirm"]} 条'
        )
        self.prototype.risks_json = json.dumps(all_risks, ensure_ascii=False)
        self.prototype.pci_json = json.dumps(all_pci, ensure_ascii=False)
        self.prototype.final_testpoints_json = json.dumps(all_final_tps, ensure_ascii=False)
        self.prototype.dedup_audit_json = json.dumps(dedup_audit, ensure_ascii=False)
        self.prototype.status = 'testpoints_ready'
        self.prototype.current_stage = 3
        self.prototype.save()
        self._advance_selected_pages(3)
        self._log(f'第一段完成！共 {len(modules)} 模块 / {len(all_final_tps)} 测试点。请确认/编辑测试点后再生成测试用例。')
        release_merge_collection(self.session_id)
        return {
            'modules': len(modules),
            'final_testpoints': len(all_final_tps),
            'phase': 1,
        }

    # ---------- 阶段3 第二段：基于（已确认的）测试点生成用例→冒烟→质量→Excel ----------
    @_timed_stage('阶段3-2 用例生成')
    def _code_quality_check(self, all_cases, smoke_json, all_final_tps):
        #type: (...) -> dict   
        import re as _re
        # C1 兼容性归一化：把「{module:X, testcase:{...}}」嵌套结构中外层 module 同步到内层 testcase，
        # 避免 LLM 把 module 放外层而 C1 只查内层导致误判"缺 module"。
        for tc in all_cases:
            if not isinstance(tc, dict):
                continue
            inner = tc.get('testcase', tc) if isinstance(tc, dict) else tc
            if isinstance(inner, dict) and not inner.get('module') and tc.get('module'):
                inner['module'] = tc.get('module')
        total_cases = len(all_cases)
        smoke_cases = smoke_json.get('smoke_testcases',[]) if isinstance(smoke_json,dict) else (smoke_json if isinstance(smoke_json,list) else [])
        total_smoke = len(smoke_cases)
        # C1 (兼容 {module, testcase:{id,title,...}} 嵌套结构)
        REQ_F = ('id','module','title','precondition','steps','expected','priority','type')
        c1_failed = []
        for tc in all_cases:
            if not isinstance(tc,dict): continue
            inner = tc.get('testcase', tc) if isinstance(tc, dict) else tc
            if not isinstance(inner, dict): continue
            missing = [k for k in REQ_F if not inner.get(k)]
            if missing: c1_failed.append({'case_id': inner.get('id','?'), 'missing_fields': missing})
        c1_r = 'FAIL' if c1_failed else 'PASS'
        # C2
        c2_ratio = total_smoke / total_cases if total_cases > 0 else 0
        if total_smoke==0 or c2_ratio<0.05: c2_r,c2_n = 'WARNING',f'{c2_ratio:.1%}'
        elif c2_ratio>0.25: c2_r,c2_n = 'WARNING',f'{c2_ratio:.1%}'
        else: c2_r,c2_n = 'PASS',f'{c2_ratio:.1%}'
        # C3
        c3_mods = {}
        for tp in all_final_tps:
            if not isinstance(tp,dict): continue
            if str(tp.get('priority','')).upper()!='P0': continue
            m = tp.get('module') or tp.get('feature_module') or '?'
            c = tp.get('category') or ''
            c3_mods.setdefault(m,{'t':0,'m':0})
            c3_mods[m]['t']+=1
            if c=='main_flow': c3_mods[m]['m']+=1
        c3_ok = all(v['m']>=1 for v in c3_mods.values()) if c3_mods else True
        c3_r = 'PASS' if c3_ok else 'FAIL'
        c3_miss = [m for m,v in c3_mods.items() if v['m']==0]
        # C4
        VAGUE = ('测试一下','检查功能','验证功能','随便','正常','一般')
        c4_t,c4_b = 0,0
        for tc in all_cases:
            if not isinstance(tc,dict): continue
            steps = tc.get('steps',[])
            if isinstance(steps,str): steps = [s.strip() for s in _re.split(r'[\n\r]+',steps) if s.strip()]
            if not isinstance(steps,list) or len(steps)<3: c4_b+=1
            elif any(w in '|'.join(str(s) for s in steps) for w in VAGUE): c4_b+=1
            c4_t+=1
        c4_r = 'WARNING' if c4_t>0 and c4_b/c4_t>0.3 else 'PASS'
        # C5
        p0c = sum(1 for t in all_final_tps if isinstance(t,dict) and str(t.get('priority','')).upper()=='P0')
        p2c = sum(1 for t in all_final_tps if isinstance(t,dict) and str(t.get('priority','')).upper()=='P2')
        ttp = len(all_final_tps) or 1
        c5_p0,c5_p2 = p0c/ttp, p2c/ttp
        c5_i = []
        if c5_p0>0.15: c5_i.append(f'P0%={c5_p0:.1%}>15%')
        if c5_p2<0.20: c5_i.append(f'P2%={c5_p2:.1%}<20%')
        c5_r = 'WARNING' if c5_i else 'PASS'
        # C6
        c6_b = sum(1 for t in all_final_tps if isinstance(t,dict) and len(t.get('description','') or '')<80)
        c6_r = 'WARNING' if c6_b/ttp>0.3 else 'PASS'
        # blocking
        bi = []
        if c1_r=='FAIL': bi.append({'check':'C1','message':f'{len(c1_failed)}用例缺必填字段'})
        if c3_r=='FAIL': bi.append({'check':'C3','message':f'缺main_flow: {",".join(c3_miss[:5])}'})
        wn = []
        if c2_r=='WARNING': wn.append(f'C2: {c2_n}')
        if c4_r=='WARNING': wn.append(f'C4: {c4_b}/{c4_t}')
        if c5_r=='WARNING': wn.append(f'C5: {";".join(c5_i)}')
        if c6_r=='WARNING': wn.append(f'C6: {c6_b}/{ttp}')
        qr = {
            'quality_report': {
                'overall_result': 'PASS' if not bi else 'FAIL',
                'checks': {
                    'C1': {'result': c1_r, 'issues': c1_failed},
                    'C2': {'result': c2_r, 'smoke_count': total_smoke, 'total_count': total_cases, 'ratio': round(c2_ratio,4)},
                    'C3': {'result': c3_r, 'p0_modules': list(c3_mods.keys()), 'missing_main_flow': c3_miss},
                    'C4': {'result': c4_r, 'sampled': c4_t, 'bad': c4_b},
                    'C5': {'result': c5_r, 'p0_ratio': round(c5_p0,4), 'p2_ratio': round(c5_p2,4)},
                    'C6': {'result': c6_r, 'sampled': ttp, 'bad': c6_b},
                },
                'blocking_issues': bi,
                'warnings': wn,
            }
        }
        return {
            'quality_json': qr,
            'blocking': bi,
            'warnings': wn,
            'smoke_count': total_smoke,
            'c1_failed': len(c1_failed),
        }
    def _repair_missing_steps(self, case: dict, mod_name: str) -> dict:
        """缺步骤用例自愈：把该条用例回喂 LLM 重生成一次操作步骤；仍失败则标记缺失。"""
        title = case.get('title') or case.get('scenario') or case.get('name') or '该用例'
        repair_prompt = (
            '以下是生成的一条测试用例，但缺少「操作步骤」。'
            '请根据用例标题、前置条件和预期结果，补充 2~5 条具体的、可执行的测试操作步骤。\n\n'
            f'模块：{mod_name}\n'
            f'标题：{title}\n'
            f'前置条件：{case.get("precondition") or ""}\n'
            f'预期结果：{case.get("expected") or ""}\n\n'
            '只输出 JSON，格式：{"steps": ["步骤1", "步骤2", ...]}\n'
            '不要输出任何解释文字。'
        )
        try:
            out = self._llm(self.writer_config or self.analyzer_config, repair_prompt,
                            max_tokens=1500, temperature=0, timeout=120)
            data = _parse_json(_extract_block(out, 'json')) or {}
            steps_new = data.get('steps') or []
            if isinstance(steps_new, list) and any(str(s).strip() for s in steps_new):
                case['steps'] = [str(s).strip() for s in steps_new if str(s).strip()]
                case['steps_repaired'] = True
                self._log(f'  用例「{title}」步骤缺失，已自动补全 {len(case["steps"])} 条')
                return case
        except Exception as e:
            logger.warning(f'用例步骤自愈失败（{title}）: {e}')
        case['steps'] = '【步骤缺失，请补充操作步骤】'
        case['steps_missing'] = True
        case['notes'] = (
            ((case.get('notes') or '') + '；' if case.get('notes') else '')
            + '步骤缺失，需人工补充'
        )
        self._log(f'  ⚠️ 用例「{title}」步骤自愈失败，标记待人工补充')
        return case

    def run_design_phase2(self):
        """读取（可能被人工编辑过的）final_testpoints_json，生成测试用例、冒烟、质量报告、Excel。"""
        self.prototype.status = 'designing'
        self.prototype.save(update_fields=['status'])
        self._log('开始生成测试用例（阶段3 · 第二段）...')

        # 读取已确认的最终测试点
        try:
            all_final_tps = json.loads(self.prototype.final_testpoints_json or '[]')
            if not isinstance(all_final_tps, list):
                all_final_tps = []
        except Exception:
            all_final_tps = []
        if not all_final_tps:
            self.prototype.status = 'failed'
            self.prototype.error_message = '没有可用的测试点，请先运行第一段生成测试点'
            self.prototype.save(update_fields=['status', 'error_message'])
            self._log('第二段中止：final_testpoints_json 为空')
            return {'testcases': 0, 'error': 'no_testpoints'}

        # 重新解析模块拆分，供用例生成提供 module_context
        split_yaml = _parse_yaml(_extract_block(self.prototype.module_split, 'yaml')) or {}
        modules = split_yaml.get('modules', []) if isinstance(split_yaml, dict) else []
        mod_map = {m.get('name', ''): m for m in modules if isinstance(m, dict)}

        # 按模块分组测试点（保持原始顺序）
        tps_by_mod = {}
        for tp in all_final_tps:
            mod_name = (tp.get('module') if isinstance(tp, dict) else None) or '未分组'
            tps_by_mod.setdefault(mod_name, []).append(tp)

        # 3.4 用例生成（按模块批量，模块内再按 CASE_BATCH_SIZE 拆批，避免 max_tokens 截断残缺）
        CASE_BATCH_SIZE = 12  # 单批测试点上限（线上实测单模块 p95=30，12 为安全余量与调用次数的甜点）
        module_testcases = []
        for mod_name, final_tps in tps_by_mod.items():
            if not final_tps:
                continue
            mod = mod_map.get(mod_name, {'name': mod_name})
            mod_ctx = json.dumps(mod, ensure_ascii=False)
            # 注入人工已确认的 PCI 答案 + 风险处置结论，让 AI 基于确认结论精准出例
            confirmed_ctx = self._build_confirmed_context()
            # 模块内拆批
            batches = [final_tps[i:i + CASE_BATCH_SIZE] for i in range(0, len(final_tps), CASE_BATCH_SIZE)]
            mod_cases = []
            try:
                for bi, batch_tps in enumerate(batches):
                    self._log(f'  模块[{mod_name}] 正在生成测试用例（第 {bi + 1}/{len(batches)} 批，本批 {len(batch_tps)} 测试点，共 {len(final_tps)}）...')
                    case_prompt = (render_prompt(P3_CASE_GEN,
                                                 test_point_yaml=json.dumps(batch_tps, ensure_ascii=False),
                                                 module_context=mod_ctx)
                                   + "\n\n### 附加指令\n请为上面列出的【每一条】最终测试点生成一条结构化测试用例，"
                                     "以 YAML 列表返回，列表项为 `testcase:` 字典（字段同 p3 输出规范）。"
                                   + self._kb_suffix(query_hint=mod_name))
                    if confirmed_ctx:
                        case_prompt += (
                            "\n\n### 已确认的待确认问题答案与风险处置结论（人工已确认，请务必作为用例设计依据）\n"
                            + confirmed_ctx)
                    meta = self._llm(self.writer_config, case_prompt, max_tokens=16000, temperature=0, return_meta=True)
                    case_out = meta.get('content', '') if isinstance(meta, dict) else meta
                    finish_reason = meta.get('finish_reason') if isinstance(meta, dict) else None
                    if finish_reason == 'length':
                        # max_tokens 用满被截断：本批用例可能残缺，记录告警但不静默丢弃已生成部分
                        logger.warning(f'模块[{mod_name}] 第{bi + 1}批用例生成被 max_tokens 截断(finish_reason=length)，本批可能残缺')
                        self._log(f'  ⚠ 模块[{mod_name}] 第{bi + 1}批输出被 max_tokens 截断，本批用例可能不完整（请检查该模块用例覆盖）')
                    case_yaml = _parse_yaml(_extract_block(case_out, 'yaml')) or {}
                    # 兼容三种 LLM 输出形态：
                    #   1) {testcases: [...]}  推荐，列表
                    #   2) {testcase: {...}}   旧 prompt，单条
                    #   3) [...]               裸数组
                    cases = []
                    if isinstance(case_yaml, dict):
                        cases = case_yaml.get('testcases') or []
                        if not cases and 'testcase' in case_yaml:
                            cases = [case_yaml['testcase']]
                    elif isinstance(case_yaml, list):
                        cases = case_yaml
                    # 过滤掉空字典（LLM 偶发返回的空占位）
                    cases = [c for c in cases if isinstance(c, dict) and c]
                    for c in cases:
                        if not c.get('module'):
                            c['module'] = mod_name
                    mod_cases.extend(cases)
                module_testcases.append((mod_name, mod_cases))
            except Exception as e:
                logger.error(f'模块[{mod_name}] 用例生成失败: {e}')
                self._log(f'  模块[{mod_name}] 用例生成失败: {e}')
                continue

        # 汇总全部用例
        all_cases = []
        for _, cases in module_testcases:
            all_cases.extend(cases)
        # 用例归一化：统一为扁平结构（解包 {module, testcase:{...}}），
        # 并给缺失操作步骤的用例补兜底步骤，避免入库后出现「无步骤用例」。
        flat_cases = []
        for tc in all_cases:
            if not isinstance(tc, dict):
                continue
            inner = tc.get('testcase', tc) if isinstance(tc.get('testcase'), dict) else tc
            if isinstance(inner, dict):
                if not inner.get('module') and tc.get('module'):
                    inner['module'] = tc.get('module')
                steps = inner.get('steps')
                steps_txt = ''
                if isinstance(steps, list):
                    steps_txt = ';'.join(
                        str(x.get('content') or x.get('action') or x) if isinstance(x, dict) else str(x)
                        for x in steps
                    )
                elif isinstance(steps, str):
                    steps_txt = steps
                if not steps_txt.strip():
                    # 先自愈：回喂 LLM 重生成一次操作步骤；仍失败才显式标记缺失
                    inner = self._repair_missing_steps(inner, inner.get('module') or '?')
                flat_cases.append(inner)
        all_cases = flat_cases
        self.prototype.testcases_json = json.dumps(all_cases, ensure_ascii=False)
        self._log(f'3.4 用例生成完成，共 {len(all_cases)} 条用例')

        # 3.5 冒烟提取（p4 技能输出 YAML，必须用 _parse_yaml 解析）
        # 关键：输入必须是「已生成的全部测试用例」，从中筛选 P0 用例作为冒烟，
        # 直接复用其 steps/expected，避免从测试点现编步骤导致与正式用例脱节、id 对不上。
        self._log('3.5 正在从已生成用例中筛选 P0 冒烟用例...')
        smoke_prompt = render_prompt(P4_SMOKE_EXTRACT,
                                     generated_testcases_json=json.dumps(all_cases, ensure_ascii=False))
        smoke_out = self._llm(self.analyzer_config, smoke_prompt, max_tokens=6000, temperature=0)
        smoke_json = _parse_yaml(_extract_block(smoke_out, 'yaml')) or {}
        # 兼容模型直接返回数组的情况，统一包装为 {smoke_overview, smoke_testcases, execution_suggestion}
        if isinstance(smoke_json, list):
            smoke_json = {'smoke_testcases': smoke_json}
        self.prototype.smoke_json = json.dumps(smoke_json, ensure_ascii=False)

        # 3.6 质量自检（代码级 C1-C6，省掉 P8 LLM 调用）
        self._log('3.6 正在执行质量自检（代码级 C1-C6）...')
        q = self._code_quality_check(all_cases, smoke_json, all_final_tps)
        self.prototype.quality_report_json = json.dumps(q['quality_json'], ensure_ascii=False)
        self._log('3.6 质量自检完成（代码级，0 次 LLM 调用）')
        if q['blocking']:
            self.prototype.status = 'failed'
            reasons = '；'.join(b.get('message',str(b)) for b in q['blocking'])
            self.prototype.error_message = f'质量门禁未通过（阻断项）：{reasons}。已保留测试用例和质量报告，但未导出正式 Excel。'
            self.prototype.excel_path = ''
            self.prototype.save()
            self._advance_selected_pages(self.prototype.current_stage, status='failed', error=self.prototype.error_message)
            self._log(self.prototype.error_message)
            return {'final_testpoints': len(all_final_tps), 'testcases': len(all_cases),
                    'smoke': q['smoke_count'], 'excel': '', 'quality': 'failed', 'blocking_issues': q['blocking'], 'phase': 2}
        if q['warnings']:
            self.prototype.error_message = '质量门禁告警（已放行导出）：' + '；'.join(q['warnings'])
            self._log('质量门禁软告警（已放行导出）：' + '；'.join(q['warnings']))
        else:
            self.prototype.error_message = ''
            self._log('质量门禁全部通过')

        # 3.7 Excel 导出
        self._log('3.7 正在导出 Excel...')
        excel_path = self._export_excel(all_cases, smoke_json)

        self.prototype.excel_path = excel_path or ''
        self.prototype.status = 'done'
        self.prototype.current_stage = 3
        self.prototype.save()
        self._advance_selected_pages(4)
        self._log(f'用例生成全部完成！共 {len(all_final_tps)} 测试点 / {len(all_cases)} 用例 / Excel: {excel_path or "无"}')

        # 自适应沉淀（方案C闭环）：本次流程发现的风险处置/PCI处置/质量缺口/澄清结论，
        # 自动回填项目知识库（带 proto 的版本/功能前缀），供后续同类需求 RAG 召回。
        # 仅质量门禁通过（status='done'）时沉淀，避免把失败产物写入知识库。
        try:
            from apps.requirement_analysis.models import AIModelService
            kb_result = AIModelService.auto_fill_knowledge_from_modao_products(
                self.prototype,
                model_config=self.analyzer_config,
                user_id=self.prototype.created_by_id,
            )
            self._log(
                f'[知识沉淀] 自动回填 {kb_result.get("created_count", 0)} 条新知识'
                f'（跳过已存在 {kb_result.get("skipped_count", 0)} 条）'
            )
        except Exception as e:
            self._log(f'[知识沉淀] 自动回填失败（可忽略，不影响用例产出）: {e}')

        # 确认问答沉淀（方案C闭环补充）：把澄清阶段用户确认过的问答对精确沉淀为知识，
        # 与上面 AI 从全文提炼的约束知识互补（前者是「用户怎么确认的」，后者是「AI 总结的约束」）。
        try:
            from apps.requirement_analysis.models import AIModelService
            confirmed_answers = []
            for _item in self.prototype.clarification_items():
                if not isinstance(_item, dict):
                    continue
                _resolution = (str(_item.get('resolution') or _item.get('answer') or '')).strip()
                _q = (str(_item.get('suggested_question') or _item.get('issue') or _item.get('question') or '')).strip()
                if _q and _resolution:
                    confirmed_answers.append({'question': _q, 'answer': _resolution})
            if confirmed_answers:
                _ver = getattr(self.prototype, 'version', None)
                _mod = getattr(self.prototype, 'feature_module', None)
                conf_result = AIModelService.auto_fill_knowledge_from_confirmations(
                    confirmed_answers=confirmed_answers,
                    project_id=self.prototype.project_id,
                    user_id=self.prototype.created_by_id,
                    model_config=self.analyzer_config,
                    version_tag=getattr(_ver, 'name', '') or '',
                    module_tag=getattr(_mod, 'name', '') or '',
                )
                self._log(
                    f'[知识沉淀·确认问答] 自动回填 {conf_result.get("created_count", 0)} 条'
                    f'（跳过已存在 {conf_result.get("skipped_count", 0)} 条）'
                )
        except Exception as e:
            self._log(f'[知识沉淀·确认问答] 自动回填失败（可忽略，不影响用例产出）: {e}')

        return {
            'final_testpoints': len(all_final_tps),
            'testcases': len(all_cases),
            'smoke': len(smoke_json.get('smoke_testcases', []) if isinstance(smoke_json, dict) else []),
            'excel': excel_path,
            'phase': 2,
        }

    # ---------- 收集人工已确认的 PCI 答案 + 风险处置结论，供用例生成参考 ----------
    def _build_confirmed_context(self):
        """从 pci_json / risks_json 提取人工已确认的答案，拼接为上下文文本。
        用例生成(p3)注入后 AI 可基于确认结论精准出例。兼容多种结构：
        顶层数组 [{module, data:{pci_list/risk_points}}] / 单层 {data:{...}} / 裸数组。
        """
        parts = []
        # 1) PCI 确认答案
        try:
            pci_raw = json.loads(self.prototype.pci_json or '[]')
            pci_list = []
            if isinstance(pci_raw, list):
                for m in pci_raw:
                    lst = None
                    if isinstance(m, dict):
                        lst = (m.get('data', {}) or {}).get('pci_list') or m.get('pci_list')
                    if isinstance(lst, list):
                        pci_list.extend(lst)
            elif isinstance(pci_raw, dict):
                pci_list = (pci_raw.get('data', {}) or {}).get('pci_list') or pci_raw.get('pci_list') or []
            for pci in pci_list:
                if not isinstance(pci, dict):
                    continue
                desc = (pci.get('description') or '').strip()
                if not desc:
                    continue
                lines = []
                subs = pci.get('sub_questions') or []
                if isinstance(subs, list) and subs:
                    for s in subs:
                        q = (s.get('question') or '').strip()
                        a = (s.get('answer') or '').strip()
                        if q and a:
                            lines.append(f'  - Q: {q}\n    A: {a}')
                else:
                    a = (pci.get('answer') or pci.get('resolution_condition') or '').strip()
                    if a:
                        lines.append(f'  - A: {a}')
                if lines:
                    parts.append(f'【待确认问题 {pci.get("id", "")}】{desc}\n' + '\n'.join(lines))
        except Exception:
            pass
        # 2) 风险处置结论
        try:
            risk_raw = json.loads(self.prototype.risks_json or '[]')
            risk_list = []
            if isinstance(risk_raw, list):
                for m in risk_raw:
                    lst = None
                    if isinstance(m, dict):
                        lst = (m.get('data', {}) or {}).get('risk_points') or m.get('risk_points')
                    if isinstance(lst, list):
                        risk_list.extend(lst)
            elif isinstance(risk_raw, dict):
                risk_list = (risk_raw.get('data', {}) or {}).get('risk_points') or risk_raw.get('risk_points') or []
            for r in risk_list:
                if not isinstance(r, dict):
                    continue
                desc = (r.get('description') or r.get('risk_point') or '').strip()
                mit = (r.get('mitigation') or '').strip()
                if desc and mit:
                    parts.append(f'【风险 {r.get("id", "")}】{desc}\n  - 处置: {mit}')
        except Exception:
            pass
        if not parts:
            return ''
        return '\n\n'.join(parts)

    # ---------- Excel 导出（复用技能 module_exporter 样式）----------
    def _export_excel(self, testcases, smoke_json):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
        except Exception as e:
            logger.warning(f'openpyxl 不可用，跳过 Excel: {e}')
            return ''

        out_dir = os.path.join(MEDIA_ROOT, 'modao', self.session_id)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, 'testcases_all.xlsx')

        wb = Workbook()
        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']

        HEADER_FILL = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        HEADER_FONT = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')
        SMOKE_FILL = PatternFill(start_color='FFE699', end_color='FFE699', fill_type='solid')
        P0_FILL = PatternFill(start_color='F8CBAD', end_color='F8CBAD', fill_type='solid')
        P1_FILL = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
        CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
        LEFT = Alignment(horizontal='left', vertical='center', wrap_text=True)
        THIN = Border(*[Side(style='thin', color='BFBFBF')] * 4)

        # 总览
        ws = wb.create_sheet('总览', 0)
        ws.append(['需求梳理与用例生成 - 总览'])
        ws['A1'].font = Font(name='微软雅黑', size=14, bold=True)
        p0 = sum(1 for c in testcases if c.get('priority') == 'P0')
        p1 = sum(1 for c in testcases if c.get('priority') == 'P1')
        p2 = sum(1 for c in testcases if c.get('priority') == 'P2')
        smoke_cases = smoke_json.get('smoke_testcases', []) if isinstance(smoke_json, dict) else []
        smoke_cnt = len(smoke_cases)
        stats = [
            ('模块数', len({c.get('module') for c in testcases})),
            ('用例总数', len(testcases)),
            ('P0', p0), ('P1', p1), ('P2', p2),
            ('冒烟用例数', smoke_cnt),
            ('生成时间', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ]
        ws.append([])
        ws.append(['统计项', '数值'])
        for c in (1, 2):
            ws.cell(row=3, column=c).font = HEADER_FONT
            ws.cell(row=3, column=c).fill = HEADER_FILL
        for label, val in stats:
            ws.append([label, val])
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['B'].width = 15

        # 用例 sheet（按模块）
        modules = {}
        for c in testcases:
            modules.setdefault(c.get('module', '未命名'), []).append(c)
        cols = [('ID', 14), ('模块', 15), ('标题', 35), ('前置条件', 25), ('测试步骤', 50),
                ('预期结果', 30), ('优先级', 8), ('类型', 10), ('关联需求', 15), ('是否冒烟', 10), ('备注', 20)]
        for mod_name, cases in modules.items():
            ws2 = wb.create_sheet(mod_name[:31])
            ws2.append([c[0] for c in cols])
            for ci, _ in enumerate(cols, 1):
                cell = ws2.cell(row=1, column=ci)
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = CENTER
                cell.border = THIN
            for c in cases:
                steps = c.get('steps', [])
                steps_txt = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(steps)) if isinstance(steps, list) else str(steps)
                ws2.append([
                    c.get('id', ''), c.get('module', ''), c.get('title', ''),
                    c.get('precondition', ''), steps_txt, c.get('expected', ''),
                    c.get('priority', ''), c.get('type', ''), c.get('requirement_ref', ''),
                    '是' if c.get('is_smoke') else '否', c.get('notes', ''),
                ])
                r = ws2.max_row
                for ci in range(1, len(cols) + 1):
                    cell = ws2.cell(row=r, column=ci)
                    cell.alignment = LEFT
                    cell.border = THIN
                    cell.font = Font(name='微软雅黑', size=10)
                    if ci == 7 and c.get('priority') in ('P0', 'P1'):
                        cell.fill = P0_FILL if c.get('priority') == 'P0' else P1_FILL
                        cell.alignment = CENTER
                    if ci == 10 and c.get('is_smoke'):
                        cell.fill = SMOKE_FILL
                        cell.alignment = CENTER
                ws2.row_dimensions[r].height = 60
            for ci, (_, w) in enumerate(cols, 1):
                ws2.column_dimensions[get_column_letter(ci)].width = w
            ws2.freeze_panes = 'A2'

        # 冒烟 sheet
        if smoke_cases:
            ws3 = wb.create_sheet('冒烟用例')
            shead = ['序号', '用例ID', '所属模块', '冒烟标题', '前置条件', '测试步骤', '通过标准', '执行结果', '执行人', '备注']
            ws3.append(shead)
            for ci, h in enumerate(shead, 1):
                cell = ws3.cell(row=1, column=ci)
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = CENTER
                cell.border = THIN
            for i, sc in enumerate(smoke_cases, 1):
                steps = sc.get('test_steps') or sc.get('steps') or []
                steps_txt = '\n'.join(f'{j+1}. {s}' for j, s in enumerate(steps)) if isinstance(steps, list) else str(steps)
                expected_val = sc.get('pass_criteria') or sc.get('expected') or ''
                if isinstance(expected_val, list):
                    expected_val = '\n'.join(str(x) for x in expected_val)
                ws3.append([i, sc.get('id', ''), sc.get('module', ''), sc.get('title', ''),
                            sc.get('precondition', ''), steps_txt,
                            expected_val, '', '', sc.get('notes', '')])
                for ci in range(1, len(shead) + 1):
                    cell = ws3.cell(row=ws3.max_row, column=ci)
                    cell.alignment = LEFT
                    cell.border = THIN
                    cell.font = Font(name='微软雅黑', size=10)
            ws3.freeze_panes = 'A2'

        wb.save(out_path)
        logger.info(f'Excel 导出成功: {out_path}')
        return out_path

    # ---------- 阶段4：冒烟执行决策（前端驱动）----------
    def record_smoke_decision(self, decision: str, reject_email: str = ''):
        self.prototype.stage4_decision = decision  # passed / rejected
        if reject_email:
            self.prototype.clarification_log = (self.prototype.clarification_log or '') + '\n\n' + reject_email
        self.prototype.current_stage = 4
        self.prototype.save()
