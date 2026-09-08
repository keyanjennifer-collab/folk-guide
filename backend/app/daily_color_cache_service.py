"""公共未来7天与个人未来3天的五色缓存服务。

本模块只把已经确定的规则结果转换成稳定内容，不调用大模型。公共结果不含个人
信息；个人结果必须由路由先验证AI国学权益后才能读取或生成。缓存元数据同时包含
规则版本、配置指纹和档案版本，任何一项变化都会重算。
"""

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .daily_color_context import build_personal_rule_input, build_public_rule_input
from .daily_color_personal_engine import calculate_personal_rule, combined_config_fingerprint
from .daily_color_research_v1 import PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG
from .daily_color_rule_engine import calculate_public_rule
from .models import BirthProfile, DailyGuidance, PublicColorCache
from .public_guide_schemas import PublicGuideInput


PUBLIC_CACHE_DAYS = 7
PERSONAL_CACHE_DAYS = 3
PERSONAL_CONTENT_VERSION = "personal-guidance-v1.1"
DISCLAIMER = "内容用于传统文化了解和生活搭配参考，不构成医疗、法律、投资或其他专业意见。"
PUBLIC_COLOR_LABELS = {"白金": "白色系", "绿金": "绿色系", "黑金": "黑色系", "红金": "红色系", "黄金": "黄色系"}

TENDENCY_TO_LABEL = {
    "strong_support": "今天很顺",
    "support": "比较合适",
    "balanced": "平稳一般",
    "caution": "会比较累",
    "restrained": "成效偏弱",
}

# 角色只用于向本人解释“为什么个人排序与公共排序不同”。这里使用中性的文化说明，
# 不把五行关系包装成确定命运、财富或现实结果的承诺。
PERSONAL_ROLE_EXPLANATION = {
    "resource": "在当前规则中，这一五行与本人日主形成支持关系",
    "peer": "在当前规则中，这一五行与本人日主属于同类关系",
    "output": "在当前规则中，这一五行偏向表达与行动关系",
    "wealth": "在当前规则中，这一五行偏向事务落实与资源安排关系",
    "officer": "在当前规则中，这一五行偏向秩序、边界与责任关系",
}

# 这些是稳定的生活方式文案，不承担命理断语；算法只决定五色顺序和趋势层级。
ELEMENT_CONTENT = {
    "金": {
        "suitable": ["梳理重点", "明确事务边界", "完成需要决断的沟通"],
        "advice": "可用白色、银色或浅金属色作主色或局部点缀，保持简洁清楚。",
        "resistance": "若安排过密，容易只顾效率而忽略沟通余地。",
        "product_code": "WUSE-JIN-01",
        "incense": "清衡香",
        "scent": "白檀与雪松的清朗木质调，适合整理思路时使用。",
    },
    "木": {
        "suitable": ["开始学习计划", "整理成长事项", "进行温和沟通"],
        "advice": "可用绿色、青色或自然纹理作搭配，给日常安排留出伸展感。",
        "resistance": "推进过快时容易分散精力，宜先确定一件最重要的事。",
        "product_code": "WUSE-MU-01",
        "incense": "青和香",
        "scent": "竹叶与柏木的清润草木调，适合阅读与安静工作。",
    },
    "水": {
        "suitable": ["收集信息", "复盘近期计划", "处理需要弹性的事项"],
        "advice": "可用黑色、深蓝或低饱和冷色稳定整体，再以浅色平衡。",
        "resistance": "信息过多时容易反复比较，重要决定仍需设定截止时间。",
        "product_code": "WUSE-SHUI-01",
        "incense": "玄润香",
        "scent": "沉香与淡苔的静润气息，适合独处、复盘与缓慢思考。",
    },
    "火": {
        "suitable": ["表达创意", "开展公开沟通", "安排适度社交"],
        "advice": "可用红色、暖橙或柔和暖色作重点，面积不必过大。",
        "resistance": "表达过满时可能带来急躁感，宜给重要沟通留下停顿。",
        "product_code": "WUSE-HUO-01",
        "incense": "明心香",
        "scent": "桂花与少量辛香的温暖气息，适合需要表达和行动时使用。",
    },
    "土": {
        "suitable": ["落实已有计划", "整理空间", "处理需要耐心的事务"],
        "advice": "可用米黄、驼色或大地色形成稳定基底，再搭配少量亮色。",
        "resistance": "过度求稳时可能拖延变化，宜给计划设置一个小的下一步。",
        "product_code": "WUSE-TU-01",
        "incense": "安土香",
        "scent": "檀木与谷物的温和气息，适合落地计划与整理空间。",
    },
}


def _public_payload(target_date: date) -> tuple[dict, str]:
    """计算一天公共规则，并转换成首页现有的五色内容结构。"""
    rule_input = build_public_rule_input(target_date, PUBLIC_RESEARCH_CONFIG.version)
    calculation = calculate_public_rule(rule_input, PUBLIC_RESEARCH_CONFIG)
    calendar = rule_input.calendar
    items = []
    for item in calculation.result.ranking.items:
        content = ELEMENT_CONTENT[item.element]
        items.append({
            "rank": item.rank,
            "color": PUBLIC_COLOR_LABELS[item.color],
            "element": item.element,
            "smoothness": TENDENCY_TO_LABEL[item.tendency],
            "suitable": content["suitable"],
            "resistance": content["resistance"],
            "advice": content["advice"],
            "product_code": content["product_code"],
            "incense_name": content["incense"],
            "scent": content["scent"],
        })
    first = items[0]
    payload = PublicGuideInput(
        guide_date=target_date,
        weekday=calendar.weekday,
        lunar_date=calendar.lunar_text,
        solar_term=calendar.solar_term_on_day or calendar.previous_solar_term.name,
        day_ganzhi=calendar.pillars.day.text,
        items=items,
        share_title=f"{target_date.month}月{target_date.day}日今日五色｜{first['color']}居首",
        share_summary=f"五色应时，知时而行。今日公共五色以{first['color']}为首选参考。",
        push_summary=f"今日五色已更新：{first['color']}居首，查看完整穿搭与生活建议。",
        rule_version=PUBLIC_RESEARCH_CONFIG.version,
    ).model_dump(mode="json")
    return payload, calculation.result.input_fingerprint


def ensure_public_color_cache(db: Session, target_date: date) -> dict:
    """取得一天公共缓存；版本或配置变化时原位重算。"""
    expected_fingerprint = PUBLIC_RESEARCH_CONFIG.fingerprint()
    cached = db.scalar(select(PublicColorCache).where(PublicColorCache.guide_date == target_date))
    if cached and cached.rule_version == PUBLIC_RESEARCH_CONFIG.version and cached.config_fingerprint == expected_fingerprint:
        return json.loads(cached.payload_json)

    payload, _ = _public_payload(target_date)
    serialized = json.dumps(payload, ensure_ascii=False)
    if cached:
        cached.rule_version = PUBLIC_RESEARCH_CONFIG.version
        cached.config_fingerprint = expected_fingerprint
        cached.payload_json = serialized
    else:
        db.add(PublicColorCache(
            guide_date=target_date,
            rule_version=PUBLIC_RESEARCH_CONFIG.version,
            config_fingerprint=expected_fingerprint,
            payload_json=serialized,
        ))
    return payload


def warm_public_color_cache(db: Session, start_date: date, days: int = PUBLIC_CACHE_DAYS) -> dict[date, dict]:
    """从指定北京时间日期起预热公共缓存，默认包含当天在内未来7天。"""
    payloads = {
        start_date + timedelta(days=offset): ensure_public_color_cache(db, start_date + timedelta(days=offset))
        for offset in range(days)
    }
    db.commit()
    return payloads


def _personal_payload(profile: BirthProfile, target_date: date, entitlement_plan: str) -> dict:
    """按当前档案计算一天个人五色，并加入缓存校验元数据。"""
    rule_input = build_personal_rule_input(profile, target_date, PERSONAL_RESEARCH_CONFIG.version)
    calculation = calculate_personal_rule(rule_input, PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG)
    traces_by_color = {trace.color: trace for trace in calculation.color_traces}
    colors = []
    for item in calculation.result.ranking.items:
        content = ELEMENT_CONTENT[item.element]
        trace = traces_by_color[item.color]
        colors.append({
            "rank": item.rank,
            "name": item.color,
            "element": item.element,
            "tendency": TENDENCY_TO_LABEL[item.tendency],
            "suitable": content["suitable"],
            "resistance": content["resistance"],
            "advice": content["advice"],
            "incense": content["incense"],
            "scent": content["scent"],
            "reason": (
                f"结合本人出生结构与{target_date.month}月{target_date.day}日的公共时序，"
                f"{item.color}排在个人第{item.rank}位；{PERSONAL_ROLE_EXPLANATION[trace.role]}。"
            ),
        })
    top = colors[0]
    supporting = [colors[1]["name"], colors[2]["name"]]
    public_top = calculation.public_calculation.result.ranking.items[0].color
    if public_top == top["name"]:
        comparison_note = (
            f"你的个人首位与今日公共首位同为{public_top}。个人排序仍按出生结构70%与"
            "今日公共环境30%综合计算，因此后续颜色的次序仍可能不同。"
        )
    else:
        comparison_note = (
            f"今日公共首位为{public_top}；结合本人出生结构后，个人首位调整为{top['name']}。"
            "个人排序按出生结构70%与今日公共环境30%综合计算，所以不应直接照搬公共排名。"
        )
    return {
        "date": target_date.isoformat(),
        "timezone": "Asia/Shanghai",
        "content_version": PERSONAL_CONTENT_VERSION,
        "rule_version": calculation.result.rule_version,
        "rule_status": calculation.result.rule_status,
        "precision_mode": calculation.result.precision_mode,
        "profile_version": calculation.result.profile_version,
        "calendar_version": profile.calculation_version,
        "entitlement_plan": entitlement_plan,
        "primary_color": top["name"],
        "supporting_colors": supporting,
        "combination_advice": (
            f"可用{top['name']}作为今天的主要参考色，以{supporting[0]}辅助，"
            f"再用{supporting[1]}作小面积点缀；不必全身使用单一颜色。"
        ),
        "personal_focus": (
            f"今天可优先从{top['suitable'][0]}开始。{top['advice']}"
        ),
        "comparison_note": comparison_note,
        "colors": colors,
        "suitable": top["suitable"],
        "reminders": [
            "个人排序是传统五行资料的生活化参考，不替代现实信息与专业判断。",
            "不必全身使用首位颜色，可从上衣、围巾、包或小配件开始。",
        ],
        "culture_note": (
            f"本结果使用{'完整四柱' if calculation.result.precision_mode == 'four_pillars' else '年、月、日三柱'}"
            "与当天公共时序综合计算；未知时辰时不会补造时柱。"
        ),
        "disclaimer": DISCLAIMER,
        # 以下字段只用于服务端判断缓存有效性，FastAPI响应模型不会返回给小程序。
        "config_fingerprint": calculation.result.config_fingerprint,
        "input_fingerprint": calculation.result.input_fingerprint,
    }


def _personal_cache_valid(payload: dict, profile: BirthProfile, target_date: date) -> bool:
    """检查缓存是否仍对应当前规则、档案版本、日期与配置。"""
    return (
        payload.get("date") == target_date.isoformat()
        and payload.get("content_version") == PERSONAL_CONTENT_VERSION
        and payload.get("rule_version") == PERSONAL_RESEARCH_CONFIG.version
        and payload.get("profile_version") == profile.profile_version
        and payload.get("calendar_version") == profile.calculation_version
        and payload.get("config_fingerprint") == combined_config_fingerprint(
            PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG
        )
    )


def ensure_personal_color_cache(
    db: Session,
    profile: BirthProfile,
    target_date: date,
    entitlement_plan: str,
) -> dict:
    """取得一个用户某天的个人缓存；调用前必须已经完成权益校验。"""
    cached = db.scalar(select(DailyGuidance).where(
        DailyGuidance.user_id == profile.user_id,
        DailyGuidance.guidance_date == target_date,
    ))
    if cached:
        try:
            payload = json.loads(cached.payload_json)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if _personal_cache_valid(payload, profile, target_date):
            # 权益计划可能从体验升级为正式服务，不需要因此重算五色。
            payload["entitlement_plan"] = entitlement_plan
            return payload

    payload = _personal_payload(profile, target_date, entitlement_plan)
    serialized = json.dumps(payload, ensure_ascii=False)
    if cached:
        cached.payload_json = serialized
    else:
        db.add(DailyGuidance(
            user_id=profile.user_id,
            guidance_date=target_date,
            payload_json=serialized,
        ))
    return payload


def warm_personal_color_cache(
    db: Session,
    profile: BirthProfile,
    entitlement_plan: str,
    start_date: date,
    days: int = PERSONAL_CACHE_DAYS,
    *,
    commit: bool = True,
) -> dict[date, dict]:
    """预热个人未来3天；此函数不自行判断权益，防止调用方绕过门槛。"""
    # 每个用户只保留本次窗口，避免服务长期运行后累积已经过期的个人派生数据。
    end_date = start_date + timedelta(days=days)
    db.query(DailyGuidance).filter(
        DailyGuidance.user_id == profile.user_id,
        (DailyGuidance.guidance_date < start_date) | (DailyGuidance.guidance_date >= end_date),
    ).delete(synchronize_session=False)
    payloads = {
        start_date + timedelta(days=offset): ensure_personal_color_cache(
            db, profile, start_date + timedelta(days=offset), entitlement_plan
        )
        for offset in range(days)
    }
    if commit:
        db.commit()
    return payloads
