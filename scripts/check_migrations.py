#!/usr/bin/env python3
"""Alembic 迁移文件一致性检查 (Task 1.2)。

扫描 backend/alembic/versions/ 下所有 .py 迁移文件，使用 AST 解析提取
revision / down_revision，检查:

  a. 迁移链连续性 —— 从 root (down_revision=None) 到 head 可追溯，无分叉/多 head。
  b. 文件名前缀数字与 revision 顺序基本一致 —— 允许历史偏差，仅警告 (WARN)。
  c. 无孤立迁移 —— down_revision 指向的 revision 必须存在于版本目录中。

发现错误 (ERROR) 返回非零退出码；警告 (WARN) 不影响退出码。

用法:
    python scripts/check_migrations.py
    python scripts/check_migrations.py --versions-dir backend/alembic/versions
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MigrationInfo:
    """单个迁移文件的解析结果。"""

    filename: str
    filepath: Path
    revision: Optional[str] = None
    down_revision: Optional[object] = None  # None | str | tuple[str, ...]
    prefix_num: Optional[str] = None  # 文件名前缀数字部分, 如 "005"


@dataclass
class CheckReport:
    """检查报告。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------- 解析 ----------

_PREFIX_RE = re.compile(r"^(\d+[a-z]?)_", re.IGNORECASE)


def extract_prefix(filename: str) -> Optional[str]:
    """从文件名提取前缀数字部分, 如 '005' / '019a'。"""
    match = _PREFIX_RE.match(filename)
    return match.group(1) if match else None


def parse_migration(filepath: Path) -> MigrationInfo:
    """用 AST 解析迁移文件, 提取模块级 revision / down_revision 赋值。

    不执行文件代码, 避免副作用与 import 失败。
    """
    info = MigrationInfo(
        filename=filepath.name,
        filepath=filepath,
        prefix_num=extract_prefix(filepath.name),
    )
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except SyntaxError as exc:
        info.revision = None
        info.down_revision = None
        # 用一个特殊标记让上层报错
        raise RuntimeError(f"语法错误, 无法解析 {filepath.name}: {exc}") from exc

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "revision":
            info.revision = _literal_value(node.value)
        elif target.id == "down_revision":
            info.down_revision = _literal_value(node.value)

    return info


def _literal_value(node: ast.AST) -> object:
    """从 AST 节点提取字面量值 (None / str / tuple / list)。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_literal_value(elt) for elt in node.elts)
    if isinstance(node, ast.List):
        return list(_literal_value(elt) for elt in node.elts)
    # 无法静态求值 (如动态计算的表达式)
    return f"<unparsed:{ast.dump(node)}>"


# ---------- 检查 ----------

def _down_revisions(down_revision: object) -> list[str]:
    """归一化 down_revision 为 revision id 列表。"""
    if down_revision is None:
        return []
    if isinstance(down_revision, str):
        return [down_revision]
    if isinstance(down_revision, (tuple, list)):
        return [v for v in down_revision if isinstance(v, str)]
    return []


def _revision_num(revision: str) -> Optional[int]:
    """从 revision id 提取前导数字, 如 '004_summary' -> 4, '019a_chat_prompt_version' -> 19。"""
    match = re.match(r"^0*(\d+)", revision)
    return int(match.group(1)) if match else None


def check_migrations(versions_dir: Path) -> CheckReport:
    """执行全部检查并返回报告。"""
    report = CheckReport()
    py_files = sorted(versions_dir.glob("*.py"))
    # 排除 __init__.py / __pycache__ 等
    py_files = [f for f in py_files if not f.name.startswith("__")]

    if not py_files:
        report.errors.append(f"版本目录下未找到迁移文件: {versions_dir}")
        return report

    infos: list[MigrationInfo] = []
    for f in py_files:
        try:
            infos.append(parse_migration(f))
        except RuntimeError as exc:
            report.errors.append(str(exc))

    # 建立 revision -> info 索引
    by_revision: dict[str, MigrationInfo] = {}
    for info in infos:
        if info.revision is None:
            report.errors.append(
                f"{info.filename}: 未找到模块级 revision 赋值"
            )
            continue
        if not isinstance(info.revision, str):
            report.errors.append(
                f"{info.filename}: revision 不是字符串字面量 ({info.revision!r})"
            )
            continue
        if info.revision in by_revision:
            report.errors.append(
                f"重复的 revision id '{info.revision}': "
                f"{by_revision[info.revision].filename} 与 {info.filename}"
            )
            continue
        by_revision[info.revision] = info

    # --- 检查 c: 无孤立迁移 (down_revision 指向不存在的 revision) ---
    for info in infos:
        if info.revision is None or not isinstance(info.revision, str):
            continue
        parents = _down_revisions(info.down_revision)
        if info.down_revision is not None and not parents:
            report.errors.append(
                f"{info.filename} (revision={info.revision}): "
                f"down_revision 无法静态解析 ({info.down_revision!r})"
            )
            continue
        for parent in parents:
            if parent not in by_revision:
                report.errors.append(
                    f"{info.filename} (revision={info.revision}): "
                    f"down_revision='{parent}' 指向不存在的 revision (孤立迁移)"
                )

    # --- 检查 a: 迁移链连续性 ---
    # root: down_revision 为 None
    roots = [i for i in infos if isinstance(i.revision, str)
             and _down_revisions(i.down_revision) == [] and i.down_revision is None]
    if len(roots) == 0:
        report.errors.append("未找到 root 迁移 (down_revision=None 的初始迁移)")
    elif len(roots) > 1:
        names = ", ".join(f"{r.filename}({r.revision})" for r in roots)
        report.errors.append(f"存在多个 root 迁移 (down_revision=None): {names}")

    # head: 没有被任何其他迁移的 down_revision 引用的 revision
    referenced: set[str] = set()
    for info in infos:
        if isinstance(info.revision, str):
            referenced.update(_down_revisions(info.down_revision))
    heads = [i for i in infos if isinstance(i.revision, str) and i.revision not in referenced]
    if len(heads) > 1:
        names = ", ".join(f"{h.filename}({h.revision})" for h in heads)
        report.errors.append(f"存在多个 head (迁移链分叉): {names}")
    elif len(heads) == 0:
        report.errors.append("未找到 head (可能存在循环依赖)")

    # 从 head 回溯到 root, 检测断裂/循环
    if len(roots) == 1 and len(heads) == 1:
        chain: list[str] = []
        current: Optional[str] = heads[0].revision
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                report.errors.append(f"检测到循环依赖, 起始于 revision='{current}'")
                break
            visited.add(current)
            chain.append(current)
            info = by_revision.get(current)
            if info is None:
                report.errors.append(
                    f"迁移链回溯中断: revision='{current}' 不存在于版本目录"
                )
                break
            parents = _down_revisions(info.down_revision)
            if len(parents) > 1:
                report.errors.append(
                    f"{info.filename} (revision={current}): 存在多个 down_revision {parents}, "
                    f"本检查器暂不支持 merge 迁移的完整链路分析"
                )
                break
            current = parents[0] if parents else None
        # chain 应包含 root
        if roots[0].revision not in chain:
            report.errors.append(
                f"迁移链未回到 root: head={heads[0].revision}, root={roots[0].revision}, "
                f"链路={chain}"
            )

    # --- 检查 b: 文件名前缀与 revision 顺序基本一致 (仅警告) ---
    # 按文件名前缀数字排序, 检查 revision 数字是否单调不减
    sortable = [
        i for i in infos
        if isinstance(i.revision, str) and i.prefix_num is not None
    ]
    # 提取前缀的纯数字部分用于排序
    def prefix_int(prefix: str) -> Optional[int]:
        match = re.match(r"^0*(\d+)", prefix)
        return int(match.group(1)) if match else None

    sortable.sort(key=lambda i: prefix_int(i.prefix_num) or 0)
    last_rev_num = -1
    for info in sortable:
        rev_num = _revision_num(info.revision)
        if rev_num is None:
            continue
        if rev_num < last_rev_num:
            report.warnings.append(
                f"{info.filename} (revision={info.revision}, 前缀={info.prefix_num}): "
                f"revision 数字 {rev_num} 小于前序迁移的 {last_rev_num}, 可能存在命名偏差"
            )
        last_rev_num = max(last_rev_num, rev_num)

    # 文件名前缀与 revision 前缀不一致 (仅警告)
    for info in sortable:
        rev_num = _revision_num(info.revision)
        pre_num = prefix_int(info.prefix_num)
        if rev_num is not None and pre_num is not None and rev_num != pre_num:
            report.warnings.append(
                f"{info.filename}: 文件名前缀 {info.prefix_num} (={pre_num}) 与 "
                f"revision='{info.revision}' (={rev_num}) 数字不一致"
            )

    # 检测文件名前缀编号跳跃 (如 015 -> 019)
    pre_nums = sorted(
        prefix_int(i.prefix_num) for i in sortable
        if prefix_int(i.prefix_num) is not None
    )
    for prev, curr in zip(pre_nums, pre_nums[1:]):
        if curr - prev > 1:
            report.warnings.append(
                f"文件名前缀编号跳跃: {prev:03d} -> {curr:03d} (跳过 "
                f"{', '.join(str(n) for n in range(prev + 1, curr))})"
            )

    return report


# ---------- 入口 ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="Alembic 迁移文件一致性检查")
    parser.add_argument(
        "--versions-dir",
        default="backend/alembic/versions",
        help="迁移版本目录 (默认: backend/alembic/versions)",
    )
    args = parser.parse_args()

    # 支持从项目根或 scripts/ 目录运行
    versions_dir = Path(args.versions_dir)
    if not versions_dir.is_absolute():
        # 尝试相对于当前工作目录
        if not versions_dir.exists():
            # 尝试相对于脚本所在目录的上一级 (项目根)
            project_root = Path(__file__).resolve().parent.parent
            versions_dir = project_root / args.versions_dir

    if not versions_dir.exists():
        print(f"错误: 迁移版本目录不存在: {versions_dir}", file=sys.stderr)
        return 2

    print(f"扫描迁移目录: {versions_dir}")
    print("=" * 70)

    report = check_migrations(versions_dir)

    if report.warnings:
        print(f"\n⚠ 警告 ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  [WARN] {w}")

    if report.errors:
        print(f"\n✗ 错误 ({len(report.errors)}):")
        for e in report.errors:
            print(f"  [ERROR] {e}")
    else:
        print("\n✓ 迁移链检查通过, 无错误。")

    print("=" * 70)
    if report.ok:
        print("结果: PASS")
        return 0
    print("结果: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
