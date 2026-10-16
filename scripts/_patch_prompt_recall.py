"""幂等补丁：给墨刀线 p2/p3 提示词补「禁止删除 + 改写路径 + 覆盖下限」。

## 背景（2026-10-14 生产实测，proto=82 / page=764「P7 入口」）

新版提示词把「不可判伪断言占比」从 65.7% 降到 47.1%（看似达标），但同一轮里：
  - 测试点 34 条 -> 24 条（删掉 10 条）
  - 四个历史缺陷高发维度覆盖全面下降：①10->6 ②15->10 ③9->8 ④8->3
  - 丢失的场景高度集中在「展示型 / 回归型 / 埋点型」—— 即最难写出功能级断言的那一类

## 根因

只加了「兜底句不得单独成条」这条**纯禁止性约束**，没给**改写路径**。
LLM 遇到写不出功能级断言的条目，选择直接丢弃而非改写 ⇒ 分母变小、占比「改善」。
这是**指标 hacking**：指标变好但覆盖变差。

次要根因：两段新指令被追加到硬约束**最末**，长输入下末尾指令衰减。

## 改动

1. p2/p3 的兜底句规则：由「禁止单独成条」改为「**先改写，禁止直接删除**」，
   并给出 ①可观测对象 ②可观测终态 ③对照判据 三步改写路径。
2. p2 新增硬约束 10「覆盖不回退（数量下限）」：条数 >= 模块数 + features 条目数，
   且任一模块 >= 总条数 15%（防注意力偏向新增功能模块）。
3. p2 硬约束 1、p3 硬约束 1 末尾追加提醒，指向位于本节末尾的四个维度自检。

幂等：已含特征串则跳过，可重复执行。
"""
import os

P2 = r'C:\TestHub\apps\requirement_analysis\modao_skill\prompts\p2_testpoint_gen.md'
P3 = r'C:\TestHub\apps\requirement_analysis\modao_skill\prompts\p3_case_gen.md'

MARK = '先改写，禁止直接删除'
MARK_DIM = '逐项自检硬约束'


def load(path):
    with open(path, 'r', encoding='utf-8', newline='') as f:
        c = f.read()
    nl = '\r\n' if '\r\n' in c else '\n'
    return c.split(nl), nl


def save(path, lines, nl):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(nl.join(lines))


def find(lines, prefix):
    for i, l in enumerate(lines):
        if l.startswith(prefix):
            return i
    return -1


def find_contains(lines, needle):
    """按子串定位（避开 emoji 变体选择符导致的精确匹配失败）。"""
    for i, l in enumerate(lines):
        if needle in l:
            return i
    return -1


def insert_after(lines, idx, block):
    lines[idx + 1:idx + 1] = block


def patch_p2():
    lines, nl = load(P2)
    changed = []

    # 1) 硬约束 1 末尾追加四个维度自检提醒
    i = find(lines, '1. **覆盖完整**')
    if i < 0:
        print('FATAL: p2 未找到硬约束 1 锚点')
        return False
    if MARK_DIM not in lines[i]:
        lines[i] = lines[i] + '；并**' + MARK_DIM + ' 9 的四个历史缺陷高发维度**（该条位于本节末尾，切勿遗漏）'
        changed.append('p2-硬约束1-维度提醒')

    # 2) 兜底句规则：禁止 -> 先改写
    j = find_contains(lines, '**兜底句不得单独成条**')
    if j < 0:
        # 已打过补丁时标题被改写，原子串不再存在 —— 用 MARK 判断是否已打过
        if any(MARK in l for l in lines):
            print('p2 兜底句 already patched (skip)')
        else:
            print('FATAL: p2 未找到兜底句规则锚点')
            return False
    elif MARK not in lines[j]:
        lines[j] = lines[j].replace(
            '**兜底句不得单独成条**',
            '**兜底句不得单独成条 —— 先改写，禁止直接删除**',
        ).replace('只能作为附加项', '只能作为**附加项**')
        insert_after(lines, j, [
            '   > **当某条目一时只能写出兜底句时，按序改写，不得直接丢弃该场景**：',
            '   > ① 补**可观测对象** → 落到具体元素 / 文案 / 数值（「昵称区域展示正常」→「昵称区域显示当前账号昵称『张三』」）；',
            '   > ② 补**可观测终态** → 展示之后能做什么（→「点击昵称区域跳转至『编辑资料』页」）；',
            '   > ③ 补**对照判据** → 与什么对比（→「与 H5 端修改后接口返回的 nickname 字段一致」）。',
            '   > 三条都试过仍无功能级判据的，才允许**合并进相邻条目**，并在 `description` 中写明被并入的原场景。',
        ])
        changed.append('p2-兜底句-改写路径')

    # 3) 硬约束 6「严禁泛化」加例外：勿把本模块真实涉及的多账号 / 登录态 / 权益场景当套话删掉
    #    实证：生产 proto=82 丢失了旧版 P0「多账号切换后外卖锁入口缓存数据隔离验证」，
    #    而硬约束 6 的禁止举例里明确写了「多账号隔离」⇒ LLM 一刀切误删。
    m = find_contains(lines, '严禁泛化')
    if m < 0:
        print('FATAL: p2 未找到硬约束 6 锚点')
        return False
    if not any('例外（勿误删）' in l for l in lines[m:m + 5]):
        insert_after(lines, m, [
            '   ⚠️ **例外（勿误删）**：若本模块**确实涉及**账号切换 / 登录态 / 会员权益，',
            '    则「多账号数据隔离」「登录后回跳原页面」「会员过期后权限」属于**本模块的具体场景**，必须保留；',
            '    上文的「多账号隔离」仅指**与本模块无关的通用套话**。',
        ])
        changed.append('p2-硬约束6-例外说明')

    # 4) 新增硬约束 10：覆盖不回退
    if find(lines, '10. **覆盖不回退') < 0:
        k = find_contains(lines, '**中断恢复**')
        if k < 0:
            print('FATAL: p2 未找到 中断恢复 锚点')
            return False
        insert_after(lines, k, [
            '10. **覆盖不回退（数量下限）**：输出测试点条数**不得少于「模块数 + features 条目数」**；',
            '    且**任一模块的测试点条数不得低于总条数的 15%**（防止注意力集中在"新增功能"模块，',
            '    漏掉常规入口的老功能回归、埋点补报、跨端同步等场景）。',
            '    不足 ⇒ 说明有场景被误删，必须补回后再输出。',
        ])
        changed.append('p2-新增硬约束10-覆盖下限')

    if changed:
        save(P2, lines, nl)
    print('p2 changed: %s' % (', '.join(changed) if changed else 'none (already patched)'))
    return True


def patch_p3():
    lines, nl = load(P3)
    changed = []

    # 1) 硬约束 1 末尾追加四个维度自检提醒
    i = find(lines, '1. **步骤可执行**')
    if i < 0:
        print('FATAL: p3 未找到硬约束 1 锚点')
        return False
    if MARK_DIM not in lines[i]:
        lines[i] = lines[i] + '；并**' + MARK_DIM + ' 8 的四个历史缺陷高发维度**（该条位于本节末尾，切勿遗漏）'
        changed.append('p3-硬约束1-维度提醒')

    # 2) 兜底句规则：禁止 -> 先改写
    j = find_contains(lines, '**兜底句不得单独成条**')
    if j < 0:
        if any(MARK in l for l in lines):
            print('p3 兜底句 already patched (skip)')
        else:
            print('FATAL: p3 未找到兜底句规则锚点')
            return False
    elif MARK not in lines[j]:
        lines[j] = lines[j].replace(
            '**兜底句不得单独成条**',
            '**兜底句不得单独成条 —— 先改写，禁止直接删除**',
        )
        # 改写路径插到「> 依据：」那一行之后
        k = j
        while k + 1 < len(lines) and lines[k + 1].startswith('   >'):
            k += 1
        insert_after(lines, k, [
            '   > **当某条断言一时只能写成兜底句时，按序改写，不得直接丢弃该验证点**：',
            '   > ① 补**可观测对象** → 落到具体元素 / 文案 / 数值；',
            '   > ② 补**可观测终态** → 断言之后能做什么（如「点击后跳转至『编辑资料』页」）；',
            '   > ③ 补**对照判据** → 与什么对比（如「与接口返回的 nickname 字段一致」）。',
            '   > 仍写不出的，才允许并入同用例的其他断言，并在 `notes` 中写明原验证点。',
        ])
        changed.append('p3-兜底句-改写路径')

    # 3) 新增硬约束 9：覆盖不回退
    if find(lines, '9. **覆盖不回退') < 0:
        k = find_contains(lines, '不限于交易')
        if k < 0:
            print('FATAL: p3 未找到第 8 条注 锚点')
            return False
        insert_after(lines, k, [
            '9. **覆盖不回退**：每条输入测试点都必须至少生成 1 条用例，且其验证点必须体现在',
            '    `expected` 中；**不得因写不出功能级断言而省略该验证点**（改用上述改写路径，',
            '    或并入相邻断言并在 `notes` 说明）。',
        ])
        changed.append('p3-新增硬约束9-覆盖下限')

    if changed:
        save(P3, lines, nl)
    print('p3 changed: %s' % (', '.join(changed) if changed else 'none (already patched)'))
    return True


if __name__ == '__main__':
    ok = patch_p2() and patch_p3()
    sys_rc = 0 if ok else 1
    os._exit(sys_rc)
