"""Validate Alertmanager config without relying on amtool.

alertmanager.yml uses ${VAR:default} and ${VAR} syntax for env var substitution.
amtool check-config does not support --config.expand-env, and mounting /tmp files
on GitHub Actions has path issues. This script performs two-layer validation:

  1. YAML syntax check (structure is valid)
  2. Semantic check (required fields present, receiver names match)

Usage:
    python scripts/validate_alertmanager_config.py [path/to/alertmanager.yml]

Exit code 0 = all checks passed, 1 = validation failed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def expand_env_vars(raw: str) -> str:
    """Expand ${VAR:default} -> default and ${VAR} -> placeholder.

    Alertmanager supports these syntaxes natively, but yaml.safe_load treats
    them as literal strings (which is fine for structure validation). We expand
    them anyway so the semantic check sees real-looking values.
    """
    # ${VAR:default} -> default (capture the default value)
    expanded = re.sub(r"\$\{[A-Z_]+:([^}]+)\}", r"\1", raw)
    # ${VAR} -> placeholder (no default, substitute a stub)
    expanded = re.sub(r"\$\{[A-Z_]+\}", "placeholder", expanded)
    return expanded


def validate_syntax(raw: str) -> dict:
    """Layer 1: YAML syntax check. Returns parsed config or exits with error."""
    expanded = expand_env_vars(raw)
    try:
        config = yaml.safe_load(expanded)
        print("YAML syntax check: PASSED")
        return config
    except yaml.YAMLError as e:
        print(f"YAML syntax error: {e}")
        sys.exit(1)


def validate_semantics(config: dict) -> list[str]:
    """Layer 2: Semantic check. Returns list of error messages (empty = OK)."""
    errors = []

    if not isinstance(config, dict):
        errors.append("Config root must be a mapping/dict")
        return errors

    route = config.get("route", {}) or {}
    default_receiver = route.get("receiver")
    receivers = config.get("receivers", []) or []
    receiver_names = {r.get("name") for r in receivers if isinstance(r, dict)}

    # route.receiver must exist in receivers
    if default_receiver and default_receiver not in receiver_names:
        errors.append(
            f'Default receiver "{default_receiver}" not found in receivers: {receiver_names}'
        )

    # All route.routes[].receiver must exist in receivers
    for i, r in enumerate(route.get("routes", []) or []):
        rname = r.get("receiver")
        if rname and rname not in receiver_names:
            errors.append(
                f'Route {i} receiver "{rname}" not found in receivers: {receiver_names}'
            )

    # inhibit_rules must have source_matchers and target_matchers
    for i, rule in enumerate(config.get("inhibit_rules", []) or []):
        if "source_matchers" not in rule:
            errors.append(f"Inhibit rule {i} missing source_matchers")
        if "target_matchers" not in rule:
            errors.append(f"Inhibit rule {i} missing target_matchers")

    return errors


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("deploy/alertmanager.yml")

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    raw = config_path.read_text(encoding="utf-8")

    config = validate_syntax(raw)

    errors = validate_semantics(config)
    if errors:
        print("Semantic check: FAILED")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("Semantic check: PASSED")
    print("Alertmanager config validation: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
