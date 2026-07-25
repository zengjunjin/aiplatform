"""对比 backend/app/config.py 与 backend/.env.example，输出缺失的配置项。

解析 config.py 中 Settings 类的所有带类型注解的字段（AnnAssign），
与 .env.example 中已文档化的 KEY= 行对比，列出：
  - 缺失：config.py 有但 .env.example 无
  - 多余：.env.example 有但 config.py 无（仅提示，不影响退出码）

运行：
    python scripts/diff_config_env.py

退出码：
    0 = 无缺失
    1 = 存在缺失（便于 CI 检测）
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# 脚本位于 aiplatform/scripts/diff_config_env.py
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "backend" / "app" / "config.py"
ENV_EXAMPLE_PATH = ROOT / "backend" / ".env.example"


def extract_settings_fields(config_path: Path) -> dict[str, str]:
    """从 config.py 中解析 Settings 类的字段名和默认值。

    仅识别 AnnAssign（带类型注解的赋值），跳过：
      - @property（FunctionDef）
      - 方法（FunctionDef）
      - ClassVar 注解字段
      - 私有字段（以下划线开头，如 _WEAK_JWT_SECRETS）
      - 普通赋值（如 model_config = SettingsConfigDict(...)）
    """
    source = config_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    fields: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            name = item.target.id
            if name.startswith("_"):
                continue
            annotation = ast.unparse(item.annotation)
            if "ClassVar" in annotation:
                continue
            if item.value is None:
                continue
            try:
                fields[name] = ast.unparse(item.value)
            except Exception:
                fields[name] = "<unparseable>"
    return fields


def extract_env_keys(env_path: Path) -> set[str]:
    """从 .env.example 中提取已文档化的配置项 key（KEY= 形式，忽略纯注释行）。"""
    keys: set[str] = set()
    pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = pattern.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.py 未找到：{CONFIG_PATH}", file=sys.stderr)
        return 2
    if not ENV_EXAMPLE_PATH.exists():
        print(f"[ERROR] .env.example 未找到：{ENV_EXAMPLE_PATH}", file=sys.stderr)
        return 2

    fields = extract_settings_fields(CONFIG_PATH)
    env_keys = extract_env_keys(ENV_EXAMPLE_PATH)

    config_keys = set(fields.keys())
    missing = sorted(config_keys - env_keys)
    extra = sorted(env_keys - config_keys)

    print(f"config.py Settings 字段数：{len(config_keys)}")
    print(f".env.example 已文档化配置项数：{len(env_keys)}")
    print(f"缺失（config.py 有但 .env.example 无）：{len(missing)}")
    print(f"多余（.env.example 有但 config.py 无）：{len(extra)}")

    if missing:
        print("\n---- 缺失的配置项 ----")
        for name in missing:
            print(f"  {name} = {fields[name]}")
    if extra:
        print("\n---- 多余的配置项（.env.example 独有，仅提示）----")
        for name in extra:
            print(f"  {name}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
