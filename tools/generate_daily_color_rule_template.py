"""把专业规则空白模板生成到 docs 目录。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.daily_color_rule_template import build_rule_template  # noqa: E402


OUTPUT = ROOT / "docs" / "今日五色专业规则与测试案例填写模板_V1.0.xlsx"
OUTPUT.write_bytes(build_rule_template())
print(OUTPUT)

