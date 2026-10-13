"""Diff the /app code of two backend images (old vs new) at file level.

Usage (host):
    python scripts/_diff_imgs.py _old_app.tar _new_app.tar

Prints: added / removed / modified files (md5), plus a summary.
Only code files are compared (the tar contains apps/ backend/ *.py *.md).
"""
import hashlib
import io
import os
import sys
import tarfile


def index(tar_path):
    out = {}
    with tarfile.open(tar_path) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            data = fh.read()
            name = member.name
            if name.startswith('./'):
                name = name[2:]
            out[name] = (hashlib.md5(data).hexdigest(), len(data))
    return out


def main():
    if len(sys.argv) < 3:
        print('usage: python _diff_imgs.py <old.tar> <new.tar>')
        return 2
    old = index(sys.argv[1])
    new = index(sys.argv[2])

    lines = []
    w = lines.append

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    common = set(old) & set(new)
    modified = sorted(p for p in common if old[p][0] != new[p][0])

    w('=== SUMMARY ===')
    w('old files=%d  new files=%d' % (len(old), len(new)))
    w('ADDED   =%d' % len(added))
    w('REMOVED =%d' % len(removed))
    w('MODIFIED=%d' % len(modified))
    w('')
    w('=== MODIFIED (%d) ===' % len(modified))
    for p in modified:
        w('  M %s   (%d B -> %d B)' % (p, old[p][1], new[p][1]))
    w('')
    w('=== ADDED (%d) ===' % len(added))
    for p in added:
        w('  A %s   (%d B)' % (p, new[p][1]))
    w('')
    w('=== REMOVED (%d) ===' % len(removed))
    for p in removed:
        w('  D %s   (%d B)' % (p, old[p][1]))

    text = '\n'.join(lines)
    with io.open('_img_diff.txt', 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
