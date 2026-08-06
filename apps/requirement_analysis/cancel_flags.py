# -*- coding: utf-8 -*-
"""进程内「手动终止」标记。

key = ModaoPrototype.id，value = True 表示用户已请求终止该任务。
后台阶段任务（读取/结构化/澄清/用例设计）在检查点轮询此标记，命中即中断。

适用前提：单进程部署（Django runserver / 单 worker）。本项目 dev 与 prod 后端均为
单进程 runserver，因此进程内字典可见性成立。若日后改为多 worker（gunicorn -w N），
需将此处换成 Redis / 数据库标记。
"""
TERMINATE_REQUESTED = {}
