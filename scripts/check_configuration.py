"""Read-only configuration preflight that never prints secret values."""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}
REQUIRED_KEYS = {"SECRET_KEY", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"}
PLACEHOLDERS = {"", "change-me-to-strong-password", "generate-a-new-secret-key-here"}

def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {number} does not contain '='")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def check(values: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    missing = sorted(key for key in REQUIRED_KEYS if not values.get(key))
    if missing:
        errors.append("missing required keys: " + ", ".join(missing))
    debug = values.get("DEBUG", "").lower()
    if debug not in TRUE_VALUES | FALSE_VALUES:
        errors.append("DEBUG must be True/False, yes/no, or 1/0")
        debug_enabled = None
    else:
        debug_enabled = debug in TRUE_VALUES
    production = values.get("APP_ENV", "").lower() in {"prod", "production"} or debug_enabled is False
    if production:
        if debug_enabled:
            errors.append("DEBUG must be False in production")
        if values.get("SECRET_KEY", "") in PLACEHOLDERS:
            errors.append("SECRET_KEY is empty or still uses a placeholder")
        if values.get("DB_PASSWORD", "") in PLACEHOLDERS:
            errors.append("DB_PASSWORD is empty or still uses a placeholder")
        hosts = {item.strip() for item in values.get("ALLOWED_HOSTS", "").split(",") if item.strip()}
        if not hosts:
            errors.append("ALLOWED_HOSTS must be configured in production")
        elif "*" in hosts:
            errors.append("ALLOWED_HOSTS must not contain '*' in production")
    if "APP_ENV" not in values:
        warnings.append("APP_ENV is not set; add it when practical")
    if not values.get("CORS_ALLOWED_ORIGINS"):
        warnings.append("CORS_ALLOWED_ORIGINS is not explicitly configured")
    return errors, warnings

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TestHub environment config.")
    parser.add_argument("env_file", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--ignore-process-env", action="store_true",
                        help="validate only the file, without process overrides")
    args = parser.parse_args()
    path = args.env_file.resolve()
    if not path.is_file():
        print(f"ERROR: configuration file does not exist: {path}", file=sys.stderr)
        return 2
    try:
        values = parse_env(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: could not parse configuration: {exc}", file=sys.stderr)
        return 2
    override_keys = {
        "DEBUG", "APP_ENV", "SECRET_KEY", "DB_NAME", "DB_USER", "DB_PASSWORD",
        "DB_HOST", "ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS",
    }
    overridden = sorted(key for key in override_keys if key in os.environ)
    if not args.ignore_process_env:
        values.update({key: os.environ[key] for key in overridden})
    errors, warnings = check(values)
    print(f"Checked {len(values)} configuration keys in {path.name}.")
    if overridden and not args.ignore_process_env:
        print("Process environment overrides: " + ", ".join(overridden))
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}")
    print("Secret values were not printed and the configuration was not modified.")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
