#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state_manager.py
轻量级工作流状态管理

使用：
  python state_manager.py init --state-dir state
  python state_manager.py save --stage 0 --output output/requirement_from_modao.md
  python state_manager.py save --stage 1 --output output/requirement_summary.md
  python state_manager.py confirm --stage 1
  python state_manager.py status --state-dir state
  python state_manager.py reject --email output/reject_email_xxx.md
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any


STATE_FILE = "workflow_state.json"

DEFAULT_STATE = {
    "skill_name": "modao-testcase-workflow",
    "skill_version": "1.0.0",
    "current_stage": 0,
    "stages_completed": [],
    "stage_outputs": {},
    "user_confirmations": {},
    "stage4_decision": None,  # passed / rejected / None
    "stage4_execution_record": None,
    "stage4_reject_email": None,
    "created_at": None,
    "updated_at": None,
}


def get_state_path(state_dir: str) -> Path:
    return Path(state_dir) / STATE_FILE


def load_state(state_dir: str) -> Dict[str, Any]:
    """加载状态文件，不存在则返回默认状态"""
    state_path = get_state_path(state_dir)
    if not state_path.exists():
        return DEFAULT_STATE.copy()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ 状态文件读取失败: {e}，使用默认状态")
        return DEFAULT_STATE.copy()


def save_state(state_dir: str, state: Dict[str, Any]) -> None:
    """保存状态到文件"""
    state_path = get_state_path(state_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def update_timestamp(state: Dict[str, Any]) -> None:
    """更新 updated_at 时间戳"""
    from datetime import datetime
    state["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def cmd_init(args):
    """初始化状态文件"""
    state = DEFAULT_STATE.copy()
    from datetime import datetime
    state["created_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    state["updated_at"] = state["created_at"]
    save_state(args.state_dir, state)
    print(f"✅ 状态文件已初始化: {get_state_path(args.state_dir)}")


def cmd_save(args):
    """保存阶段产物"""
    state = load_state(args.state_dir)
    stage = args.stage

    if not (0 <= stage <= 4):
        print(f"❌ 阶段号必须为 0-4，收到: {stage}")
        return 1

    state["current_stage"] = stage
    if stage not in state["stages_completed"]:
        state["stages_completed"].append(stage)
    state["stage_outputs"][f"stage{stage}"] = args.output
    update_timestamp(state)
    save_state(args.state_dir, state)

    print(f"✅ 阶段{stage} 产物已保存: {args.output}")
    return 0


def cmd_confirm(args):
    """用户确认某阶段"""
    state = load_state(args.state_dir)
    stage = args.stage

    if not (0 <= stage <= 4):
        print(f"❌ 阶段号必须为 0-4，收到: {stage}")
        return 1

    state["user_confirmations"][f"stage{stage}_confirmed"] = True
    if stage < 4:
        state["current_stage"] = stage + 1
    update_timestamp(state)
    save_state(args.state_dir, state)

    print(f"✅ 阶段{stage} 用户确认完成")
    print(f"📌 当前阶段: {state['current_stage']}")
    return 0


def cmd_reject(args):
    """记录冒烟失败，生成驳回邮件"""
    state = load_state(args.state_dir)
    state["stage4_decision"] = "rejected"
    state["stage4_reject_email"] = args.email
    state["stages_completed"] = [1, 2, 3, 4]
    update_timestamp(state)
    save_state(args.state_dir, state)

    print(f"❌ 阶段4 决策: 驳回")
    print(f"📧 驳回邮件: {args.email}")
    return 0


def cmd_pass(args):
    """记录冒烟通过"""
    state = load_state(args.state_dir)
    state["stage4_decision"] = "passed"
    state["stages_completed"] = [1, 2, 3, 4]
    if args.execution:
        state["stage4_execution_record"] = args.execution
    update_timestamp(state)
    save_state(args.state_dir, state)

    print(f"✅ 阶段4 决策: 冒烟通过")
    return 0


def cmd_status(args):
    """查看当前状态"""
    state = load_state(args.state_dir)
    print("=" * 50)
    print("📋 工作流状态")
    print("=" * 50)
    print(f"技能: {state.get('skill_name')} v{state.get('skill_version')}")
    print(f"当前阶段: {state.get('current_stage', 0)}")
    print(f"已完成阶段: {state.get('stages_completed', [])}")
    print(f"用户确认: {state.get('user_confirmations', {})}")
    print(f"产物列表:")
    for k, v in state.get("stage_outputs", {}).items():
        print(f"  - {k}: {v}")
    if state.get("stage4_decision"):
        print(f"阶段4 决策: {state['stage4_decision']}")
    if state.get("stage4_reject_email"):
        print(f"驳回邮件: {state['stage4_reject_email']}")
    if state.get("created_at"):
        print(f"创建时间: {state['created_at']}")
    if state.get("updated_at"):
        print(f"更新时间: {state['updated_at']}")
    print("=" * 50)
    return 0


def cmd_reset(args):
    """重置状态"""
    state = DEFAULT_STATE.copy()
    from datetime import datetime
    state["created_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    state["updated_at"] = state["created_at"]
    save_state(args.state_dir, state)
    print(f"✅ 状态已重置: {get_state_path(args.state_dir)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="req-testcase-workflow 状态管理")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init
    sub_init = subparsers.add_parser("init", help="初始化状态")
    sub_init.add_argument("--state-dir", default="state", help="状态目录（默认: state）")

    # save
    sub_save = subparsers.add_parser("save", help="保存阶段产物")
    sub_save.add_argument("--state-dir", default="state", help="状态目录（默认: state）")
    sub_save.add_argument("--stage", type=int, required=True, help="阶段号 1-4")
    sub_save.add_argument("--output", required=True, help="产物文件路径")

    # confirm
    sub_confirm = subparsers.add_parser("confirm", help="用户确认某阶段")
    sub_confirm.add_argument("--state-dir", default="state", help="状态目录（默认: state）")
    sub_confirm.add_argument("--stage", type=int, required=True, help="阶段号 1-4")

    # reject
    sub_reject = subparsers.add_parser("reject", help="记录冒烟驳回")
    sub_reject.add_argument("--state-dir", default="state", help="状态目录（默认: state）")
    sub_reject.add_argument("--email", required=True, help="驳回邮件路径")

    # pass
    sub_pass = subparsers.add_parser("pass", help="记录冒烟通过")
    sub_pass.add_argument("--state-dir", default="state", help="状态目录（默认: state）")
    sub_pass.add_argument("--execution", default=None, help="执行记录 JSON 字符串")

    # status
    sub_status = subparsers.add_parser("status", help="查看状态")
    sub_status.add_argument("--state-dir", default="state", help="状态目录（默认: state）")

    # reset
    sub_reset = subparsers.add_parser("reset", help="重置状态")
    sub_reset.add_argument("--state-dir", default="state", help="状态目录（默认: state）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "init": cmd_init,
        "save": cmd_save,
        "confirm": cmd_confirm,
        "reject": cmd_reject,
        "pass": cmd_pass,
        "status": cmd_status,
        "reset": cmd_reset,
    }

    handler = commands.get(args.command)
    if not handler:
        print(f"❌ 未知命令: {args.command}")
        return 1

    return handler(args) or 0


if __name__ == "__main__":
    sys.exit(main() or 0)
