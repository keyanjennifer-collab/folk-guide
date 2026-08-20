"""公共五色与个人五色的规则输入构建器。

本模块负责把历法库和生辰档案转换为稳定、最小化、可做指纹校验的输入。
它不计算五色排名；正式排名必须由下一阶段经专业复核的版本化规则引擎完成。
"""

import hashlib
import json
from datetime import date, datetime

from lunar_python import Solar

from .calendar_service import CALCULATION_VERSION, DAY_BOUNDARY_RULE, TIME_STANDARD, load_calendar_payload
from .daily_color_schemas import (
    EARTHLY_BRANCH_PRIMARY_ELEMENT,
    HEAVENLY_STEM_ELEMENT,
    BirthPillars,
    BirthRuleContext,
    DailyCalendarContext,
    DatePillars,
    PersonalColorRuleInput,
    PillarContext,
    PublicColorRuleInput,
    SolarTermPoint,
)
from .models import BirthProfile
from .time_service import BEIJING_TIMEZONE


# 当前版本只表示“数据结构已经确定、排序公式尚未通过专业复核”。使用这个版本
# 构建的输入可以测试，但不能直接生成并发布正式五色排名。
RULE_FRAMEWORK_VERSION = "wuse-rule-framework-v0.1"

WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _fingerprint(payload: dict) -> str:
    """对规范 JSON 计算 SHA-256；相同输入必定得到相同指纹。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pillar(text: str) -> PillarContext:
    """把两字干支转换成带主五行且会自动校验的结构。"""
    stem, branch = text[:1], text[1:2]
    try:
        return PillarContext(
            text=text,
            stem=stem,
            branch=branch,
            stem_element=HEAVENLY_STEM_ELEMENT[stem],
            branch_primary_element=EARTHLY_BRANCH_PRIMARY_ELEMENT[branch],
        )
    except KeyError as exc:
        raise ValueError(f"无法识别干支：{text}") from exc


def _solar_term(term) -> SolarTermPoint:
    """lunar-python 返回无时区字符串；按产品口径明确附加北京时间。"""
    local_time = datetime.strptime(term.getSolar().toYmdHms(), "%Y-%m-%d %H:%M:%S")
    return SolarTermPoint(name=term.getName(), at_beijing=local_time.replace(tzinfo=BEIJING_TIMEZONE))


def build_daily_calendar_context(target_date: date) -> DailyCalendarContext:
    """计算目标日期的公共历法事实，固定使用北京时间当天中午取日上下文。"""
    solar = Solar.fromYmdHms(target_date.year, target_date.month, target_date.day, 12, 0, 0)
    lunar = solar.getLunar()
    eight_char = lunar.getEightChar()
    eight_char.setSect(2)
    lunar_month = lunar.getMonth()
    solar_term = (lunar.getJieQi() or "").strip() or None

    return DailyCalendarContext(
        target_date=target_date,
        weekday=WEEKDAY_NAMES[target_date.weekday()],
        lunar_date=f"{lunar.getYear()}-{abs(lunar_month):02d}-{lunar.getDay():02d}",
        lunar_text=lunar.toString(),
        zodiac=lunar.getYearShengXiaoExact(),
        solar_term_on_day=solar_term,
        previous_solar_term=_solar_term(lunar.getPrevJieQi()),
        next_solar_term=_solar_term(lunar.getNextJieQi()),
        pillars=DatePillars(
            year=_pillar(eight_char.getYear()),
            month=_pillar(eight_char.getMonth()),
            day=_pillar(eight_char.getDay()),
        ),
        calendar_version=CALCULATION_VERSION,
        day_boundary_rule=DAY_BOUNDARY_RULE,
    )


def build_public_rule_input(
    target_date: date,
    rule_version: str = RULE_FRAMEWORK_VERSION,
) -> PublicColorRuleInput:
    """构建不含用户数据的公共规则输入，并附上可复现指纹。"""
    context = build_daily_calendar_context(target_date)
    return build_public_rule_input_from_context(context, rule_version)


def build_public_rule_input_from_context(
    context: DailyCalendarContext,
    rule_version: str = RULE_FRAMEWORK_VERSION,
) -> PublicColorRuleInput:
    """从已经算好的历法上下文构建公共输入。

    个人五色计算本来就带有目标日的公共历法上下文。提供这个入口后，个人引擎可
    复用同一份不可变数据，不必再次调用历法库，也避免两次计算在交节边界产生歧义。
    """
    core = {"audience": "public", "calendar": context.model_dump(mode="json"), "rule_version": rule_version}
    return PublicColorRuleInput(**core, input_fingerprint=_fingerprint(core))


def _birth_context(profile: BirthProfile) -> BirthRuleContext:
    """从已缓存的历法结果提取最小个人规则上下文，不复制用户身份字段。"""
    calendar = load_calendar_payload(profile)
    if not calendar:
        raise ValueError("生辰档案缺少历法计算结果，请先重新保存档案")

    raw_pillars = calendar.get("pillars") or {}
    try:
        year = _pillar(raw_pillars["year"]["text"])
        month = _pillar(raw_pillars["month"]["text"])
        day = _pillar(raw_pillars["day"]["text"])
        raw_time = raw_pillars.get("time")
        time = _pillar(raw_time["text"]) if raw_time else None
    except (KeyError, TypeError) as exc:
        raise ValueError("生辰档案中的四柱结构不完整，请先重新保存档案") from exc

    return BirthRuleContext(
        pillars=BirthPillars(year=year, month=month, day=day, time=time),
        time_pillar_available=time is not None,
        day_master_stem=day.stem,
        day_master_element=day.stem_element,
        calendar_version=calendar.get("calculation_version") or profile.calculation_version or CALCULATION_VERSION,
        time_standard=calendar.get("time_standard") or TIME_STANDARD,
        day_boundary_rule=calendar.get("day_boundary_rule") or DAY_BOUNDARY_RULE,
    )


def build_personal_rule_input(
    profile: BirthProfile,
    target_date: date,
    rule_version: str = RULE_FRAMEWORK_VERSION,
) -> PersonalColorRuleInput:
    """构建个人规则输入；同一档案版本、日期和规则版本会得到相同指纹。"""
    public_context = build_daily_calendar_context(target_date)
    birth_context = _birth_context(profile)
    precision_mode = "four_pillars" if birth_context.time_pillar_available else "three_pillars"
    core = {
        "audience": "personal",
        "public_context": public_context.model_dump(mode="json"),
        "birth_context": birth_context.model_dump(mode="json"),
        "profile_version": profile.profile_version,
        "precision_mode": precision_mode,
        "rule_version": rule_version,
    }
    return PersonalColorRuleInput(**core, input_fingerprint=_fingerprint(core))
