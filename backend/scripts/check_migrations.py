#!/usr/bin/env python3
"""Alembic 迁移文件命名一致性 linter。

检查规则（spec 阶段 1.2）：
1. 文件名前缀数字与 revision id 顺序一致
2. revision 链可追溯（每个 down_revision 指向已存在的 revision）
3. 无编号跳跃（缺失编号有占位说明文件，如 `016_placeholder.py`）

退出码：
- 0: 全部通过
- 1: 发现违规

用法：
    poetry run python scripts/check_migrations.py
    # 或在 CI 中：
    # python backend/scripts/check_migrations.py

注意：005_add_summary_snapshot.py 的 revision='004_summary' 是历史遗留，
文件内已有详细注释说明，本脚本通过 allowlist 跳过该已知例外。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 已知例外：文件名前缀与 revision id 不对齐，但有历史原因注释
# key=文件名, value=允许的 revision id（不与文件名前缀对齐）
KNOWN_EXCEPTIONS: dict[str, str] = {
    "005_add_summary_snapshot.py": "004_summary",
}

# 已知缺失编号占位说明（无占位文件时，必须在此声明原因）
# 缺失编号 016/017/018：早期开发中废弃的设计，无占位文件
KNOWN_MISSING_NUMBERS: dict[int, str] = {
    16: "早期开发中废弃的 RAG 重排设计，迁移已合并到 019_prompt_templates",
    17: "早期开发中废弃的对话上下文设计，迁移已合并到 019_prompt_templates",
    18: "早期开发中废弃的审计日志索引设计，迁移已合并到 010_performance_indexes",
}


def parse_migration_header(path: Path) -> tuple[str, str | None]:
    """从迁移文件顶部解析 revision 和 down_revision。

    返回 (revision, down_revision)。down_revision 为 None 表示首迁移。
    """
    text = path.read_text(encoding="utf-8")
    rev_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    down_match = re.search(r"^down_revision\s*=\s*(['\"]([^'\"]+)['\"]|None)", text, re.MULTILINE)

    if not rev_match:
        raise ValueError(f"{path.name}: missing 'revision' declaration")

    revision = rev_match.group(1)
    down_revision: str | None = None
    if down_match and down_match.group(2):
        down_revision = down_match.group(2)
    return revision, down_revision


def extract_prefix(filename: str) -> int | None:
    """从文件名提取数字前缀，如 '001_init_tables.py' → 1, '019a_chat_messages.py' → 19。

    返回 None 表示文件名无数字前缀（不符合命名规范）。
    字母后缀（如 019a）归并到主编号 19。
    """
    match = re.match(r"^(\d{3})[a-z]?_", filename)
    if not match:
        return None
    return int(match.group(1))


def main() -> int:
    migrations_dir = Path(__file__).parent.parent / "alembic" / "versions"
    if not migrations_dir.exists():
        print(f"ERROR: migrations directory not found: {migrations_dir}", file=sys.stderr)
        return 1

    py_files = sorted(migrations_dir.glob("*.py"))
    # 排除 __init__.py 和 script.py.mako
    py_files = [f for f in py_files if not f.name.startswith("__") and not f.name.endswith(".mako")]

    errors: list[str] = []
    warnings: list[str] = []

    # 收集所有迁移的元数据
    migrations: list[dict] = []
    all_revisions: set[str] = set()
    file_prefixes: dict[int, list[str]] = {}  # prefix -> [filename, ...]

    for path in py_files:
        try:
            revision, down_revision = parse_migration_header(path)
        except ValueError as e:
            errors.append(str(e))
            continue

        prefix = extract_prefix(path.name)
        if prefix is None:
            errors.append(f"{path.name}: filename does not match NNN_description.py pattern")
            continue

        migrations.append(
            {
                "file": path.name,
                "path": path,
                "prefix": prefix,
                "revision": revision,
                "down_revision": down_revision,
            }
        )
        all_revisions.add(revision)
        file_prefixes.setdefault(prefix, []).append(path.name)

    # Rule 1: 文件名前缀与 revision id 顺序一致（已知例外除外）
    for m in migrations:
        expected_rev_prefix = f"{m['prefix']:03d}_"
        if m["revision"].startswith(expected_rev_prefix):
            continue
        # 检查是否在已知例外 allowlist
        if m["file"] in KNOWN_EXCEPTIONS and m["revision"] == KNOWN_EXCEPTIONS[m["file"]]:
            continue
        # 检查 revision 是否以其他前缀开头（如 019a → 019）
        # 允许 revision id 为 "019a_xxx" 形式（子分支）
        if re.match(rf"^{m['prefix']:03d}[a-z]?_", m["revision"]):
            continue
        errors.append(
            f"{m['file']}: revision='{m['revision']}' does not start with "
            f"expected prefix '{expected_rev_prefix}'"
        )

    # Rule 2: revision 链可追溯
    for m in migrations:
        if m["down_revision"] is None:
            # 首迁移，必须是 prefix=1
            if m["prefix"] != 1:
                warnings.append(
                    f"{m['file']}: down_revision=None but prefix={m['prefix']} "
                    f"(expected 1 for root migration)"
                )
            continue
        if m["down_revision"] not in all_revisions:
            errors.append(
                f"{m['file']}: down_revision='{m['down_revision']}' not found "
                f"in any migration file (broken chain)"
            )

    # Rule 3: 编号跳跃检查
    if file_prefixes:
        max_prefix = max(file_prefixes.keys())
        for prefix in range(1, max_prefix + 1):
            if prefix in file_prefixes:
                continue
            # 缺失编号：检查是否有占位说明
            if prefix in KNOWN_MISSING_NUMBERS:
                continue
            errors.append(
                f"Missing migration number {prefix:03d}: no file with this prefix, "
                f"no placeholder, not in KNOWN_MISSING_NUMBERS"
            )

    # Rule 4: 同一前缀多个文件（如 005 出现两次）必须有合理原因
    for prefix, files in file_prefixes.items():
        if len(files) > 1:
            warnings.append(
                f"Prefix {prefix:03d} has multiple files: {files} "
                f"(ensure revision chain is correct)"
            )

    # 输出结果
    print("=" * 60)
    print(f"Checked {len(migrations)} migration files in {migrations_dir}")
    print("=" * 60)

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  WARN: {w}")

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"\nAll checks passed. {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
