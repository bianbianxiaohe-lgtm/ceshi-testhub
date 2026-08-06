# -*- coding: utf-8 -*-
"""纯 Airtest 录制模式真机端到端验证：走真实 HTTP 端点。"""
import requests, sys, json

BASE = "http://127.0.0.1:8000/api"
USER, PASS = "admin", "Admin@123456"

def log(*a):
    print("[E2E]", *a, flush=True)

def wait_server():
    import socket
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", 8000), 2)
            return True
        except Exception:
            time.sleep(2)
    return False

def main():
    s = requests.Session()

    if not wait_server():
        log("SERVER_NOT_UP"); sys.exit(1)
    log("SERVER_UP")

    # 1) 登录拿 JWT
    r = s.post(f"{BASE}/auth/login/", json={"username": USER, "password": PASS}, timeout=30)
    if r.status_code != 200:
        log("LOGIN_FAIL", r.status_code, r.text[:300]); sys.exit(1)
    tok = r.json().get("access")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    log("LOGIN_OK")

    # 2) 取一个 UiProject
    r = s.get(f"{BASE}/ui-automation/projects/", timeout=30)
    if r.status_code != 200:
        log("PROJ_FAIL", r.status_code, r.text[:200]); sys.exit(1)
    projs = r.json().get("results") or r.json().get("data") or []
    if not projs:
        log("NO_PROJECT"); sys.exit(1)
    pid = projs[0]["id"]
    log("PROJECT_ID", pid)

    # 3) 开始录制（纯 Airtest）
    r = s.post(f"{BASE}/ui-automation/recording/start/", json={
        "device_id": 1, "app_config_id": 2, "project_id": pid, "engine": "airtest"
    }, timeout=180)
    if r.status_code != 200 or not r.json().get("success"):
        log("START_FAIL", r.status_code, r.text[:400]); sys.exit(1)
    js = r.json()
    log("START_OK elements=%d screenshot_len=%d" % (js.get("count"), len(js.get("screenshot") or "")))
    elems = js.get("elements") or []
    if not elems:
        log("WARN no elements dumped (poco may be empty)"); 

    # 选一个优先 id 策略的元素做 click
    target = next((e for e in elems if e.get("strategy") == "id"), None) or \
             next((e for e in elems if e.get("center_x") is not None), None)
    click_ok = False
    if target:
        r = s.post(f"{BASE}/ui-automation/recording/action/", json={
            "action_type": "click",
            "element": {
                "strategy": target.get("strategy"),
                "value": target.get("value"),
                "name": target.get("chinese_name") or target.get("text") or "el",
                "center_x": target.get("center_x"),
                "center_y": target.get("center_y"),
            }
        }, timeout=120)
        if r.status_code == 200 and r.json().get("success"):
            click_ok = True
            log("CLICK_OK step=%s" % r.json().get("recorded", {}).get("step_number"))
        else:
            log("CLICK_FAIL", r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text)[:300])
    else:
        log("SKIP click (no element)")

    # swipe（方向 up）
    r = s.post(f"{BASE}/ui-automation/recording/action/", json={
        "action_type": "swipe", "input_value": "up"
    }, timeout=120)
    swipe_ok = False
    if r.status_code == 200 and r.json().get("success"):
        swipe_ok = True
        log("SWIPE_OK")
    else:
        log("SWIPE_FAIL", r.status_code, r.text[:300])

    # 4) 生成用例
    r = s.post(f"{BASE}/ui-automation/recording/generate/", json={}, timeout=120)
    if r.status_code != 200 or not r.json().get("success"):
        log("GEN_FAIL", r.status_code, r.text[:400]); sys.exit(1)
    g = r.json()
    log("GEN_OK case_id=%s step_count=%s engine=%s" % (g.get("case_id"), g.get("step_count"), g.get("engine_type")))
    script = g.get("airtest_script") or ""
    log("SCRIPT_LEN", len(script))

    checks = []
    checks.append(("start", True))
    checks.append(("click", click_ok))
    checks.append(("swipe", swipe_ok))
    checks.append(("generate", True))
    checks.append(("case_id", bool(g.get("case_id"))))
    checks.append(("script_nonempty", len(script) > 0))
    checks.append(("script_has_connect_device", "connect_device" in script))
    checks.append(("script_has_poco", "AndroidUiautomationPoco" in script))
    checks.append(("script_has_start_app", 'start_app("com.android.settings")' in script))

    all_ok = all(v for _, v in checks)
    log("=== CHECKS ===")
    for name, ok in checks:
        log(("PASS" if ok else "FAIL"), name)
    log("=== E2E %s ===" % ("DONE_OK" if all_ok else "DONE_WITH_FAILURES"))

    # 输出脚本前 30 行便于肉眼确认
    if script:
        log("--- airtest script head ---")
        for line in script.splitlines()[:30]:
            log("   ", line)
    sys.exit(0 if all_ok else 2)

if __name__ == "__main__":
    main()
