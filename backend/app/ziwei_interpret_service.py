"""紫微单盘/合盘解读服务。

接口刻意接收结构化命盘快照，而不是让小程序把提示词和模型密钥带到客户端。
公开仓库没有原平台的私有 prompt/API，本服务以公开排盘字段和版本化本地方法论为基础，
后续可替换知识版本而不改变接口。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .ziwei_knowledge import KNOWLEDGE_VERSION, HEMING_FRAMEWORK, PALACE_ROLES, PLAIN_LANGUAGE_RULES, TOPIC_LABELS, palace_role, topic_instruction


def _major_stars(palace: dict) -> list[str]:
    return [str(star.get("name")) for star in palace.get("stars", []) if star.get("type") == "major"]


def _compact_palace(palace: dict) -> dict:
    return {
        "branch": palace.get("branch"),
        "stem": palace.get("stem"),
        "name": palace.get("name"),
        "major_stars": _major_stars(palace),
        "other_stars": [
            {"name": star.get("name"), "type": star.get("type"), "siHua": star.get("siHua")}
            for star in palace.get("stars", []) if star.get("type") != "major"
        ][:16],
        "da_xian_age": palace.get("daXianAge"),
        "is_ming_gong": bool(palace.get("isMingGong")),
        "is_shen_gong": bool(palace.get("isShenGong")),
        "opposite_branch": palace.get("oppositeBranch"),
        "borrowed_stars": palace.get("borrowedStars", []),
    }


def compact_chart(chart: dict) -> dict:
    """只给模型提供解读需要的字段，去掉姓名、地址和原始输入隐私。"""
    palaces = [_compact_palace(palace) for palace in chart.get("palaces", [])]
    return {
        "calculation_version": chart.get("calculationVersion", "iztro"),
        "lunar_info": chart.get("lunarInfo", {}),
        "ming_gong_branch": chart.get("mingGongBranch"),
        "shen_gong_branch": chart.get("shenGongBranch"),
        "wuxing_ju_name": chart.get("wuxingJuName"),
        "current_age": chart.get("currentAge"),
        "current_da_xian_index": chart.get("currentDaXianIndex"),
        "da_xians": chart.get("daXians", []),
        "palaces": palaces,
    }


def _period_description(chart: dict, period_type: str, period_key: str | None) -> str:
    if period_type == "daxian":
        index = int(period_key) if period_key and period_key.isdigit() else chart.get("currentDaXianIndex", -1)
        da_xians = chart.get("daXians", [])
        if 0 <= index < len(da_xians):
            item = da_xians[index]
            return f"大限 {item.get('startAge')}–{item.get('endAge')}岁，落{item.get('palaceName')}。"
        return "当前大限资料不完整。"
    if period_type == "liunian":
        return f"流年 {period_key or '当前年份'}。"
    labels = {"mingpan": "本命盘", "xiaoxian": "小限", "liuyue": "流月", "liuri": "流日", "liushi": "流时"}
    return labels.get(period_type, period_type) + "。"


def _selected_palace(chart: dict, branch: int | None) -> dict | None:
    if branch is None:
        return None
    return next((palace for palace in chart.get("palaces", []) if palace.get("branch") == branch), None)


def single_prompt(chart: dict, topic: str, period_type: str, period_key: str | None, palace_branch: int | None) -> tuple[str, dict]:
    compact = compact_chart(chart)
    selected = _selected_palace(chart, palace_branch)
    selected_name = selected.get("name", "") if selected else "命宫总览"
    selected_stars = "、".join(_major_stars(selected)) if selected else "未指定"
    role = palace_role(str(selected_name).replace("宫", "")) if selected else "命主整体格局"
    context = {
        "kind": "ziwei_single_chart",
        "topic": TOPIC_LABELS.get(topic, topic),
        "period": _period_description(chart, period_type, period_key),
        "selected_palace": {"name": selected_name, "role": role, "major_stars": selected_stars} if selected else None,
        "chart": compact,
    }
    question = f"""请根据下面的紫微命盘结构，生成一份详细但通俗的中文传统文化分析。

分析主题：{TOPIC_LABELS.get(topic, topic)}
分析时期：{_period_description(chart, period_type, period_key)}
本次要求：{topic_instruction(topic)}
选中宫位：{selected_name}（主管：{role}；主星：{selected_stars}）

{PLAIN_LANGUAGE_RULES}

请严格使用以下结构，每个标题单独一行。标题下面要有具体解释，不要只写一句空泛判断：
【结论先说】先用两三句话说明重点，避免吓人和绝对化。
【宫位与主星】说明所选宫位、主星、辅星和四化分别代表什么。
【联动观察】结合命宫、身宫、对宫和相关三方宫位解释，不要只讲单星。
【当前时期】说明本命、大限或流年怎样影响这个主题；如果资料不足要明确说出来。
【具体建议】给出三条现实、可执行的建议。

方法论版本：{KNOWLEDGE_VERSION}。{HEMING_FRAMEWORK}
只作传统文化学习和生活观察，不能作医疗、法律、投资收益或确定性命运判断。不要输出出生日期、地址、姓名、账号或内部字段。"""
    return question, context


def compatibility_prompt(chart_a: dict, chart_b: dict, relation_type: str, question: str | None = None) -> tuple[str, dict]:
    relation_labels = {"business": "生意与合伙", "love": "姻缘与相处", "family": "亲子与家庭", "friend": "朋友与协作"}
    relation = relation_labels.get(relation_type, relation_type)
    context = {
        "kind": "ziwei_compatibility",
        "relation_type": relation,
        "chart_a": compact_chart(chart_a),
        "chart_b": compact_chart(chart_b),
    }
    question_line = f"用户追加问题：{question.strip()}" if question and question.strip() else "没有追加问题，请先给出整体观察。"
    prompt = f"""请根据两张紫微命盘，生成一份详细但通俗的{relation}双盘分析。

{HEMING_FRAMEWORK}
{PLAIN_LANGUAGE_RULES}
{question_line}

请严格使用以下结构，每个标题单独一行：
【整体匹配】说明双方的互补点和容易卡住的地方，避免用“注定”“必然”等词。
【双方命格】分别说明双方命宫、身宫和核心性格倾向。
【关系主题】围绕{relation}，分析相关宫位、主星、四化、对宫和三方联动。
【阶段观察】结合双方当前大限或流年资料；资料不足时明确说明，不要虚构年份。
【相处建议】给出三到五条可以执行的沟通、分工或边界建议。

只作传统文化学习和关系观察，不对婚姻、商业收益、健康或人生结果作保证。不要输出生日、地址、姓名、账号或内部字段。"""
    return prompt, context


def request_hash(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
