"""AI 输出的第二道安全检查。

输入关键词拦截只能阻止一部分高风险问题，模型即使收到安全提示词，也可能因为
上下文、网页摘要或模型自身偏差输出确定性预测。因此答案在写入数据库和返回小
程序之前，还要经过本模块的确定性复核。这里不尝试判断传统文化观点是否“正确”，
只拦截明显的医疗、死亡、收益保证、违法和内部信息泄露表达。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


SAFE_FALLBACK_ANSWER = (
    "这次回答包含不适合由AI作确定性判断的内容，已停止展示相关结论。"
    "传统文化内容只能作为一般学习和生活灵感参考；涉及健康、法律、投资或其他重要事项，"
    "请以现实信息和相应专业人士意见为准。"
)


@dataclass(frozen=True)
class OutputReview:
    """答案复核结果；只把复核后的文本交给外部调用方。"""

    answer: str
    status: str
    reason: str | None = None

    @property
    def filtered(self) -> bool:
        """是否替换了模型原文，供接口和审计状态使用。"""
        return self.status == "output_filtered"


# 只匹配“确定性结论”，不把安全免责声明中单独出现的“疾病/死亡”等词误判为违规。
# 模型输出可能有空格或标点，因此统一用短语和有限范围通配，而不是依赖一整句固定文案。
DETERMINISTIC_RISK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:一定|必然|注定|保证|稳稳?地)(?:会|能|可以)?(?:发财|赚钱|中奖|暴富|升职|盈利|收益)"),
    re.compile(r"(?:一定|必然|注定)(?:会|将)?(?:死亡|得癌症|患癌|坐牢|离婚)"),
    re.compile(r"(?:预测|算出|看出|断定).{0,16}(?:死亡|癌症|中奖|发财|稳赚|坐牢)"),
    re.compile(r"(?:你|您|本人).{0,10}(?:患有|就是|诊断为).{0,16}(?:癌症|疾病|抑郁|重病)"),
    re.compile(r"(?:无需|不用|不必)(?:就医|治疗|咨询律师|听取专业意见)"),
    re.compile(r"(?:投资|买入|借钱).{0,16}(?:稳赚|保证收益|必赚|不会亏)"),
)

# 内部字段不会作为正常答案的一部分。出现这些内容时直接替换，避免把账号、令牌
# 或提示词结构暴露给用户；具体命中内容只写成枚举原因，不写进日志。
INTERNAL_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:system prompt|系统提示词|开发者消息|内部提示词|内部开关)"),
    re.compile(r"(?:openid|user_id|profile_version|config_fingerprint|entitlement_plan)"),
    re.compile(r"(?:api[_ -]?key|appsecret|jwt[_ -]?secret|管理员key)", re.IGNORECASE),
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """限制模型输出长度，尽量在中文句号、换行处截断。"""
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", "\n"))
    # 如果前半段没有完整句子，宁可按长度截断，也不能返回空答案。
    if boundary >= max_chars // 2:
        clipped = clipped[: boundary + 1].rstrip()
    return clipped + "\n\n（回答较长，已按服务长度限制截取。）"


def review_model_output(answer: str, *, max_chars: int = 6000) -> OutputReview:
    """复核并规范化模型输出。

    复核顺序是：空文本兜底 → 内部信息泄露 → 明显确定性高风险结论 → 长度限制。
    被替换的原文不会写入数据库，也不会出现在异常日志中。
    """
    normalized = (answer or "").strip()
    if not normalized:
        return OutputReview(SAFE_FALLBACK_ANSWER, "output_filtered", "empty_output")
    if any(pattern.search(normalized) for pattern in INTERNAL_LEAK_PATTERNS):
        return OutputReview(SAFE_FALLBACK_ANSWER, "output_filtered", "internal_leak")
    if any(pattern.search(normalized) for pattern in DETERMINISTIC_RISK_PATTERNS):
        return OutputReview(SAFE_FALLBACK_ANSWER, "output_filtered", "deterministic_risk")
    # 下限只保留一个可读的短答案空间，仍允许测试和运营把上限调到较小值。
    bounded_limit = max(128, min(int(max_chars), 20000))
    bounded = _truncate_at_sentence(normalized, bounded_limit)
    if bounded != normalized:
        return OutputReview(bounded, "output_truncated", "max_output_chars")
    return OutputReview(normalized, "safe")
