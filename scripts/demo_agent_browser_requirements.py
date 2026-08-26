#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比 Demo（批量 + 融合版，凭证从 AIModelConfig 读取）：
  agent-browser(=Playwright accessibility-tree) 的"DOM 结构理解"
    vs
  TestHub 平台常用的"视觉截图理解"
  在"识别需求"任务上的差异。

新增能力（相对旧版）：
  1. 批量：可一次传多个 URL，逐个跑双路对比。
  2. DOM 重试兜底：墨刀分享页 DOM 文本层为异步/条件渲染，首抓可能为 0 字符；
     首抓 < 阈值时等待重试最多 2 次，降低纯 DOM 方式的"偶发失效"。
  3. 双路 LLM 自动融合：把方式 A(DOM)/方式 B(视觉) 的结果交给 LLM 交叉合并，
     去重并标注每条需求的 sources(dom/vision/both) 与 confidence(high/medium/low)、
     证据等级 evidence(A/B/C/D)，输出融合后的"最佳需求清单"。
  4. 总体方法论结论：汇总所有原型的 DOM 文本量、融合置信分布，给出落地建议。

凭证来源：默认从 DB 表 `ai_model_config`（AIModelConfig）按角色读取已启用配置：
  - 文本路径(方式A/agent-browser式) -> role='browser_use_text'（回退 analyzer/writer）
  - 视觉路径(方式B/平台式)        -> role='writer_vision'（回退 browser_use_vision）
  **不打印 api_key 明文**，只打印配置名/角色/模型名。

运行（在 testhub-backend 容器内）：
  docker cp demo_agent_browser_requirements.py testhub-backend:/tmp/
  docker exec testhub-backend python /tmp/demo_agent_browser_requirements.py <URL1> [URL2 ...] [--same-model]

说明：agent-browser 本质是一个 Rust CLI，其核心 snapshot = Playwright accessibility tree。
本 demo 用 Playwright 直接复现该工作流；方式A 把 DOM 可见文本喂 LLM，方式B 把截图喂多模态 LLM。
"""
import os
import sys
import json
import re
import base64

# ---- Django 初始化（容器 /app 为项目根）----
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
try:
    import django
    django.setup()
except Exception as e:
    print(f"[!] Django 初始化失败: {e}")
    sys.exit(1)

from playwright.sync_api import sync_playwright
from openai import OpenAI
from apps.requirement_analysis.models import AIModelConfig


# ---------- 配置读取 ----------
def load_configs():
    """从 AIModelConfig 读取已启用配置；返回 (text_cfg, vis_cfg, all_active)。"""
    active = list(AIModelConfig.objects.filter(is_active=True))

    def pick(roles):
        for r in roles:
            for c in active:
                if c.role == r:
                    return c
        return None

    text_cfg = pick(["browser_use_text", "analyzer", "writer", "reviewer"])
    vis_cfg = pick(["writer_vision", "browser_use_vision"]) or text_cfg
    if vis_cfg is None and active:
        vis_cfg = active[0]
    if text_cfg is None and active:
        text_cfg = active[0]
    return text_cfg, vis_cfg, active


def cfg_brief(cfg):
    if not cfg:
        return None
    return {
        "name": cfg.name,
        "role": cfg.role,
        "model_type": cfg.model_type,
        "model_name": cfg.model_name,
        "base_url": cfg.base_url,
        "api_key_len": len(cfg.api_key or ""),
        "is_active": cfg.is_active,
    }


def make_client(cfg):
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


# ---------- DOM 文本（含重试兜底） ----------
DOM_MIN_CHARS = 60  # 低于此值视为 DOM 层未就绪，重试


def get_dom_text(page):
    """等价 agent-browser snapshot 的底层：页面可见文本(DOM 文本)。"""
    try:
        text = page.inner_text("body")
    except Exception:
        text = page.content()
    return (text or "").strip()


def get_dom_text_with_retry(page):
    """墨刀分享页 DOM 文本层异步渲染，首抓可能为 0；重试至多 2 次。"""
    text = get_dom_text(page)
    tries = 1
    while len(text) < DOM_MIN_CHARS and tries < 3:
        page.wait_for_timeout(1500)
        text = get_dom_text(page)
        tries += 1
    return text, len(text), tries


# ---------- LLM 调用 ----------
EXTRACT_PROMPT = (
    "你是资深需求分析师。请根据提供的页面内容，提取其中的功能需求点。"
    "输出 JSON 数组，每条包含：module(所属模块)、feature(功能点)、"
    "interaction(关键交互/边界)、evidence(证据等级 A/B/C/D)。"
    "只输出 JSON 数组，不要解释。"
)

FUSE_PROMPT = (
    "你是资深需求分析架构师。下面是对同一个产品原型页面，分别用两种方式提取的需求：\n"
    "- 方式A（DOM 文本 / agent-browser 式）：基于页面 DOM 可见文本\n"
    "- 方式B（视觉截图 / 平台式）：基于页面截图\n"
    "请融合两份结果，输出去重后的功能需求数组。每条包含：\n"
    "  module(所属模块), feature(功能点), interaction(关键交互/边界),\n"
    "  evidence(取两种方式中最严格的证据等级 A/B/C/D),\n"
    "  sources(数组，元素取自 'dom' 或 'vision'，表示该需求被哪种方式支持),\n"
    "  confidence('high' 若 dom 与 vision 都支持 / 'medium' 若仅一种且 evidence>=B / 'low' 若仅一种且 evidence 为 C 或 D)\n"
    "只输出 JSON 数组，不要解释。"
)


def parse_llm_json(raw):
    """鲁棒解析 LLM 返回的 JSON 数组；失败返回 None。"""
    if raw is None:
        return None
    s = raw.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 去掉可能包裹的 ```json ... ```
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # 截取首个 [ 到末个 ]
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            pass
    return None


def call_text(client, model, dom_text):
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": "页面可访问性树(DOM 文本):\n" + dom_text[:12000]},
        ],
        temperature=0.2,
    )
    return r.choices[0].message.content


def call_vision(client, model, shot_path):
    with open(shot_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "这是该页面的截图："},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]},
        ],
        temperature=0.2,
    )
    return r.choices[0].message.content


def call_fuse(client, model, a_text, b_text, dom_len):
    user = (
        f"DOM 可见文本长度 = {dom_len} 字符。\n\n"
        f"===== 方式A（DOM 文本）原始结果 =====\n{a_text}\n\n"
        f"===== 方式B（视觉截图）原始结果 =====\n{b_text}\n"
    )
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": FUSE_PROMPT},
            {"role": "user", "content": user[:16000]},
        ],
        temperature=0.1,
    )
    return r.choices[0].message.content


# ---------- 单原型双路 + 融合 ----------
def run_one(url, text_cfg, vis_cfg, merge_cfg, same_model):
    shot_path = "/tmp/demo_shot.png"
    print(f"\n[*] 打开页面: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"[!] 页面加载警告: {e}")
        page.wait_for_timeout(1800)
        dom_text, dom_len, dom_tries = get_dom_text_with_retry(page)
        print(f"[*] DOM 可见文本长度: {dom_len} 字符（重试 {dom_tries} 次；agent-browser 式输入量）")
        try:
            page.screenshot(path=shot_path)
        except Exception as e:
            print(f"[!] 截图失败: {e}")
            shot_path = None
        # 视觉模型偶尔需要 canvas 多渲染一会；再次等待确保截图完整
        browser.close()

    result = {
        "url": url,
        "dom_visible_text_len": dom_len,
        "dom_retry_tries": dom_tries,
        "method_a_dom_raw": None,
        "method_a_dom_list": None,
        "method_b_vision_raw": None,
        "method_b_vision_list": None,
        "fused": None,
        "errors": [],
    }

    use_env = bool(os.environ.get("OPENAI_API_KEY"))

    def client_and_model(cfg):
        if use_env:
            return OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                          base_url=os.environ.get("OPENAI_BASE_URL")), \
                   os.environ.get("OPENAI_MODEL", "gpt-4o")
        return make_client(cfg), cfg.model_name

    # 方式 A：DOM 文本
    print("[方式 A] 用 DOM 文本(agent-browser 式)提取需求 ...")
    try:
        client, model = client_and_model(text_cfg)
        raw = call_text(client, model, dom_text)
        result["method_a_dom_raw"] = raw
        result["method_a_dom_list"] = parse_llm_json(raw)
    except Exception as e:
        msg = f"[方式A调用失败] {e}"
        print(msg)
        result["errors"].append(msg)
        result["method_a_dom_raw"] = msg

    # 方式 B：视觉截图
    print("[方式 B] 用页面截图(平台式视觉)提取需求 ...")
    try:
        if shot_path:
            client, model = client_and_model(vis_cfg)
            raw = call_vision(client, model, shot_path)
            result["method_b_vision_raw"] = raw
            result["method_b_vision_list"] = parse_llm_json(raw)
        else:
            result["method_b_vision_raw"] = "[!] 无截图，跳过视觉路径"
    except Exception as e:
        msg = f"[方式B调用失败] {e}"
        print(msg)
        result["errors"].append(msg)
        result["method_b_vision_raw"] = msg

    # 融合
    print("[融合] 交叉合并双路结果 ...")
    try:
        client, model = client_and_model(merge_cfg)
        raw = call_fuse(client, model,
                        result["method_a_dom_raw"] or "",
                        result["method_b_vision_raw"] or "",
                        dom_len)
        result["fused"] = parse_llm_json(raw)
        result["fused_raw"] = raw
    except Exception as e:
        msg = f"[融合调用失败] {e}"
        print(msg)
        result["errors"].append(msg)
        result["fused"] = None

    return result


# ---------- 报告 ----------
def summarize(result):
    r = result
    print(f"\n{'='*70}")
    print(f"原型: {r['url']}")
    print(f"  DOM 可见文本: {r['dom_visible_text_len']} 字符 (重试 {r['dom_retry_tries']} 次)")
    a = r["method_a_dom_list"] or []
    b = r["method_b_vision_list"] or []
    print(f"  方式A(DOM) 提取 {len(a)} 条 | 方式B(视觉) 提取 {len(b)} 条")
    fused = r["fused"] or []
    print(f"  >>> 融合后 {len(fused)} 条需求")
    high = sum(1 for x in fused if x.get("confidence") == "high")
    med = sum(1 for x in fused if x.get("confidence") == "medium")
    low = sum(1 for x in fused if x.get("confidence") == "low")
    print(f"      置信分布: high={high} medium={med} low={low}")
    for i, x in enumerate(fused, 1):
        src = "/".join(x.get("sources", []) or [])
        print(f"    {i:2d}. [{x.get('confidence','?')}/{x.get('evidence','?')}/{src}] "
              f"{x.get('module','')} / {x.get('feature','')}")
        print(f"        交互: {x.get('interaction','')}")


def print_overall_methodology(results):
    print(f"\n\n{'#'*70}")
    print("# 总体方法论结论（多原型批量对比）")
    print(f"{'#'*70}")
    print("\n各原型画像：")
    for r in results:
        fused = r["fused"] or []
        both = sum(1 for x in fused if "dom" in (x.get("sources") or []) and "vision" in (x.get("sources") or []))
        dom_only = sum(1 for x in fused if x.get("sources") == ["dom"])
        vis_only = sum(1 for x in fused if x.get("sources") == ["vision"])
        print(f"  - {r['url'][:60]}")
        print(f"      DOM={r['dom_visible_text_len']}字符 | 融合{len(fused)}条 "
              f"(双路共识{both} / 仅DOM{dom_only} / 仅视觉{vis_only})")
    print("\n最佳方案（融合策略）：")
    print("  1) 双路必须同时跑：DOM 文本(agent-browser 式) + 视觉截图(平台式)。")
    print("  2) DOM 文本层需加载重试兜底：首抓 < 60 字符时等待重试，对抗墨刀异步渲染偶发 0 字符。")
    print("  3) 交叉融合：两边共识(high)= 高置信直接采用；")
    print("     仅 DOM(含精确数值/次数/规则) 补充为 high/medium；仅视觉(布局/纯图) 补充为 medium。")
    print("  4) 证据等级保留最严格一档 A/B/C/D；C/D 标 low 交人工确认。")
    print("  平台 modao_extractor.py 现有『可见文本+截图+视觉OCR』方向正确，建议补：DOM 重试 + 双路融合合并。")


# ---------- 入口 ----------
def main():
    args = sys.argv[1:]
    same_model = "--same-model" in args
    urls = [a for a in args if not a.startswith("--")] or [
        "https://modao.cc/proto/0t26l0ti9fhhRTsdayyD/sharing?view_mode=read_only"]

    text_cfg, vis_cfg, active = load_configs()
    if same_model and vis_cfg:
        text_cfg = vis_cfg
        print("[*] --same-model: 两条路径均使用视觉模型做 A/B（隔离模型差异）")

    print("========== 模型配置（已启用，按角色）==========")
    for c in active:
        b = cfg_brief(c)
        print(f"  - {b['name']} | role={b['role']} | type={b['model_type']} | model={b['model_name']} | key_len={b['api_key_len']}")
    print(f"[*] 文本路径(方式A) 选用: {cfg_brief(text_cfg)}")
    print(f"[*] 视觉路径(方式B) 选用: {cfg_brief(vis_cfg)}")
    print(f"[*] 融合路径 选用: {cfg_brief(vis_cfg if same_model else (text_cfg or vis_cfg))}")

    if not text_cfg and not vis_cfg:
        print("[!] 库中没有可用的 AIModelConfig，无法调用 LLM。请先在平台配置模型。")
        return

    merge_cfg = vis_cfg if same_model else (text_cfg or vis_cfg)

    results = [run_one(u, text_cfg, vis_cfg, merge_cfg, same_model) for u in urls]

    print("\n\n========== 各原型融合需求清单 ==========")
    for r in results:
        summarize(r)

    print_overall_methodology(results)

    with open("/tmp/demo_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n[✓] 结果已写入 /tmp/demo_result.json")


if __name__ == "__main__":
    main()
