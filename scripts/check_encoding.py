"""Read-only UTF-8 validation for TestHub source and documentation files."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".bat", ".cmd", ".css", ".env", ".example", ".html", ".ini", ".js",
    ".json", ".md", ".py", ".ps1", ".scss", ".sql", ".toml",
    ".vue", ".yaml", ".yml",
}
EXCLUDED_PARTS = {
    ".git", ".idea", ".pytest_cache", ".venv", "__pycache__", "allure", "dist",
    "knowledge-base", "knowledge-bases", "logs", "media", "node_modules",
}
SPECIAL_NAMES = {
    ".editorconfig", ".env.example", ".gitignore", "Dockerfile",
    "Dockerfile.backend", "Dockerfile.frontend",
}

def is_candidate(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    artifact_prefixes = (
        "_", "be_", "build_", "check_", "l_", "test_", "tmp_",
    )
    if len(relative.parts) == 1 and (relative.name == "$null" or relative.name.startswith(artifact_prefixes)):
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in SPECIAL_NAMES

def validate(root: Path) -> tuple[list[tuple[Path, str]], int]:
    failures: list[tuple[Path, str]] = []
    checked = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_candidate(path, root):
            continue
        checked += 1
        try:
            path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            failures.append((path.relative_to(root), str(exc)))
        except OSError as exc:
            failures.append((path.relative_to(root), f"read error: {exc}"))
    return failures, checked

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TestHub text as UTF-8.")
    parser.add_argument("root", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    if not root.is_dir():
        print(f"ERROR: project root does not exist: {root}", file=sys.stderr)
        return 2
    failures, checked = validate(root)
    print(f"Checked {checked} text files under {root}")
    if failures:
        print(f"Found {len(failures)} file(s) that are not valid UTF-8:")
    for path, reason in failures:
        print(f"  - {path}: {reason}")
    print("No files were modified.")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
