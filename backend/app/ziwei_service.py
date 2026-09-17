"""复用 ziwei-doushu-main 的 iztro 排盘内核，并生成可复核的双盘观察结果。"""

import json
import subprocess
from pathlib import Path

from lunar_python import Lunar

from .ziwei_schemas import ZiweiBirthInput


RUNTIME_DIR = Path(__file__).with_name("ziwei_runtime")
RUNTIME_SCRIPT = RUNTIME_DIR / "chart.mjs"


def _hour_branch(value: str) -> int:
    """把钟表时间转为 iztro 的时辰索引：子=0、丑=1…亥=11。"""
    hour = int(value[:2])
    if hour in (23, 0):
        return 0
    return (hour + 1) // 2


def _solar_date(data: ZiweiBirthInput) -> tuple[int, int, int]:
    """iztro 接收公历；农历输入先由 lunar-python 可靠转换，支持闰月。"""
    if data.calendar_type == "solar":
        return data.birth_date.year, data.birth_date.month, data.birth_date.day
    try:
        lunar_month = -data.birth_date.month if data.is_leap_month else data.birth_date.month
        solar = Lunar.fromYmd(data.birth_date.year, lunar_month, data.birth_date.day).getSolar()
        if solar.getYear() > 9999:
            raise ValueError
        return solar.getYear(), solar.getMonth(), solar.getDay()
    except Exception as exc:
        raise ValueError("农历出生日期或闰月选择无效") from exc


def generate_chart(data: ZiweiBirthInput) -> dict:
    """调用与原紫微项目相同的 iztro 版本，返回完整十二宫、星曜和大限数据。"""
    solar_year, solar_month, solar_day = _solar_date(data)
    payload = {
        "year": solar_year, "month": solar_month, "day": solar_day,
        "hour": _hour_branch(data.birth_time), "gender": data.gender,
        "name": data.name, "location": data.birth_location,
    }
    try:
        process = subprocess.run(
            ["node", str(RUNTIME_SCRIPT)], input=json.dumps(payload, ensure_ascii=False),
            text=True, encoding="utf-8", capture_output=True, cwd=RUNTIME_DIR, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("紫微排盘运行环境暂不可用") from exc
    if process.returncode != 0:
        raise ValueError("出生信息无法完成紫微排盘")
    try:
        chart = json.loads(process.stdout)
        chart["inputCalendar"] = {
            "calendarType": data.calendar_type, "sourceDate": data.birth_date.isoformat(),
            "isLeapMonth": data.is_leap_month, "solarDate": f"{solar_year:04d}-{solar_month:02d}-{solar_day:02d}",
        }
        return chart
    except json.JSONDecodeError as exc:
        raise RuntimeError("紫微排盘结果格式异常") from exc


def _palace(chart: dict, name: str) -> dict:
    candidates = {name, f"{name}宫"}
    return next((item for item in chart["palaces"] if item["name"] in candidates), {"name": name, "stars": []})


def _stars(chart: dict, names: list[str]) -> str:
    result: list[str] = []
    for name in names:
        palace = _palace(chart, name)
        major = [star["name"] for star in palace["stars"] if star["type"] == "major"]
        result.append(f"{name}宫：{'、'.join(major) if major else '空宫（需参看对宫）'}")
    return "；".join(result)


def build_compatibility(chart_a: dict, chart_b: dict, relation_type: str) -> dict:
    """基于双盘关键宫位给出结构化观察，避免把不可验证结论伪装成确定预测。"""
    config = {
        "business": ("生意与合伙", ["命", "官禄", "财帛", "兄弟"], ["职责边界", "资金与收益分配", "沟通与决策节奏"]),
        "love": ("姻缘与相处", ["命", "夫妻", "福德"], ["沟通方式", "亲密边界", "共同生活安排"]),
        "family": ("亲子与家庭", ["命", "父母", "子女", "田宅"], ["家庭角色", "照顾分工", "长期居住安排"]),
        "friend": ("朋友与协作", ["命", "兄弟", "仆役"], ["相处边界", "承诺兑现", "分歧处理"]),
    }[relation_type]
    title, palaces, practical_topics = config
    a_name = chart_a["birthInfo"].get("name") or "第一位"
    b_name = chart_b["birthInfo"].get("name") or "第二位"
    same_wuxing = chart_a["wuxingJu"] == chart_b["wuxingJu"]
    return {
        "title": title,
        "basis": "依据双方命宫及关系主题相关宫位的主星配置整理；空宫须连同对宫理解。",
        "observations": [
            f"{a_name}：{_stars(chart_a, palaces)}。",
            f"{b_name}：{_stars(chart_b, palaces)}。",
            "双方同为%s，节奏感可能较接近；仍应以各自关键宫位星曜和现实沟通为准。" % chart_a["wuxingJuName"] if same_wuxing else f"双方分别为{chart_a['wuxingJuName']}、{chart_b['wuxingJuName']}，可将差异视为分工与协商的切入点。",
        ],
        "discussion_topics": practical_topics,
        "disclaimer": "内容用于传统紫微斗数学习与关系观察，不构成商业、婚姻、医疗或法律决策建议。",
    }
