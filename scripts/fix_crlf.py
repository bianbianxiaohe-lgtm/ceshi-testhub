"""把指定的脚本文件统一成 CRLF，且不改动编码。

为什么需要它：write_to_file（以及某些编辑器）会写出裸 LF。cmd 解析这样的
.bat 会出现「此时不应有 ...」这类完全误导的语法错误，PowerShell 也可能
在续行/字符串处出错。历史已经踩过多次。

用法（在工作区根目录）：
    python scripts/fix_crlf.py ios_wda_host.bat ios_resolve_server.ps1

不带参数时，自动处理 scripts/ 下所有需要修复的 ios_* 脚本
（排除已废弃的 ios_device_start.bat）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = {'ios_device_start.bat'}  # 已废弃，不再维护


def to_crlf(path):
    with open(path, 'rb') as f:
        data = f.read()
    before_crlf = data.count(b'\r\n')
    before_lf = data.count(b'\n') - before_crlf
    if before_lf == 0:
        return False, 0
    # 先把已有的 CRLF 折叠成 LF，再统一展开，避免出现 \r\r\n
    data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    with open(path, 'wb') as f:
        f.write(data)
    return True, before_lf


def main():
    names = sys.argv[1:]
    if not names:
        names = [n for n in sorted(os.listdir(HERE))
                 if n.startswith('ios_') and n.endswith(('.bat', '.ps1'))
                 and n not in SKIP]

    changed = 0
    for name in names:
        path = name if os.path.isabs(name) else os.path.join(HERE, name)
        if not os.path.exists(path):
            print('MISSING  %s' % name)
            continue
        fixed, count = to_crlf(path)
        if fixed:
            print('FIXED    %-30s %d bare LF -> CRLF' % (os.path.basename(path), count))
            changed += 1
        else:
            print('OK       %-30s already CRLF' % os.path.basename(path))
    print()
    print('%d file(s) converted.' % changed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
