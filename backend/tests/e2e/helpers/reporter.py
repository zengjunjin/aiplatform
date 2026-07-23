"""HTML 测试报告生成器"""
import html
from pathlib import Path
from datetime import datetime
from typing import List


class TestRecord:
    def __init__(self, name: str, status: str, duration: float,
                 error: str = "", screenshot: str = ""):
        self.name = name
        self.status = status  # PASS/FAIL/SKIP
        self.duration = duration
        self.error = error
        self.screenshot = screenshot
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_html_report(records: List[TestRecord], output_path: Path) -> None:
    total = len(records)
    passed = sum(1 for r in records if r.status == "PASS")
    failed = sum(1 for r in records if r.status == "FAIL")
    skipped = sum(1 for r in records if r.status == "SKIP")
    pass_rate = (passed / total * 100) if total else 0

    rows = []
    for r in records:
        status_color = {"PASS": "#52c41a", "FAIL": "#ff4d4f",
                        "SKIP": "#faad14"}.get(r.status, "#999")
        error_html = html.escape(r.error).replace("\n", "<br>") if r.error else ""
        screenshot_html = (f'<a href="{r.screenshot}" target="_blank">查看截图</a>'
                           if r.screenshot else "")
        rows.append(f"""
            <tr>
                <td>{r.timestamp}</td>
                <td>{html.escape(r.name)}</td>
                <td style="color:{status_color};font-weight:bold;">{r.status}</td>
                <td>{r.duration:.2f}s</td>
                <td>{error_html}</td>
                <td>{screenshot_html}</td>
            </tr>
        """)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>E2E 测试报告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               margin: 24px; background: #f5f5f5; }}
        h1 {{ color: #1f1f1f; }}
        .summary {{ display: flex; gap: 16px; margin: 24px 0; }}
        .card {{ background: white; padding: 16px 24px; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .card .num {{ font-size: 32px; font-weight: bold; }}
        .card .label {{ color: #666; font-size: 14px; }}
        table {{ width: 100%; border-collapse: collapse; background: white;
                border-radius: 8px; overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        th {{ background: #fafafa; padding: 12px; text-align: left;
              border-bottom: 1px solid #eee; }}
        td {{ padding: 12px; border-bottom: 1px solid #f0f0f0;
              vertical-align: top; }}
    </style>
</head>
<body>
    <h1>E2E 测试报告</h1>
    <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <div class="summary">
        <div class="card"><div class="num">{total}</div><div class="label">总数</div></div>
        <div class="card"><div class="num" style="color:#52c41a">{passed}</div><div class="label">通过</div></div>
        <div class="card"><div class="num" style="color:#ff4d4f">{failed}</div><div class="label">失败</div></div>
        <div class="card"><div class="num" style="color:#faad14">{skipped}</div><div class="label">跳过</div></div>
        <div class="card"><div class="num">{pass_rate:.1f}%</div><div class="label">通过率</div></div>
    </div>
    <table>
        <thead><tr>
            <th>时间</th><th>测试名</th><th>状态</th><th>耗时</th><th>错误</th><th>截图</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
</body>
</html>"""
    output_path.write_text(html_content, encoding="utf-8")
