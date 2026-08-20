"""正式 AI 国学问答的分类、安全、权益、检索和历史业务逻辑。"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .llm_provider import AnswerProvider
from .models import AIConversationMessage, AIServiceGrant, User
from .retrieval_service import hybrid_search
from .time_service import beijing_day_bounds_utc_naive, utc_now_naive
from .vector_store import VectorStore


DISCLAIMER = "内容仅用于传统文化学习和生活灵感参考，不构成医疗、法律、投资或其他专业意见。"

# 这些类别不能交给模型自由发挥，否则容易形成健康、死亡、赌博或收益承诺。
HIGH_RISK_TERMS = {
    "死亡", "什么时候死", "血光之灾", "癌症", "诊断", "替代就医",
    "彩票号码", "保证发财", "稳赚", "借钱投资", "违法", "报复",
}
COMPARISON_TERMS = {"七日", "7日", "未来一周", "一周比较", "七天比较"}


@dataclass(frozen=True)
class QuotaState:
    """一次权益计算的结果，路由可直接转换成 API 输出。"""
    active: bool
    plan: str | None
    expires_at: datetime | None
    normal_limit: int
    normal_used: int
    comparison_limit: int
    comparison_used: int

    def remaining(self, category: str) -> int:
        """根据问题类别返回该类别今天还可使用的次数。"""
        if category == "seven_day_comparison":
            return max(self.comparison_limit - self.comparison_used, 0)
        return max(self.normal_limit - self.normal_used, 0)


def classify_question(question: str, requested_type: str | None = None) -> tuple[str, bool]:
    """先做确定性分类和安全拦截；高风险问题不会调用检索或模型。

    当前是可解释的关键词最小实现。TODO（上线前）：增加同义词、拼音变体、上下文规则、
    模型安全分类器及人工抽检；但模型分类不能取代这层硬规则。
    """
    if any(term in question for term in HIGH_RISK_TERMS):
        return "high_risk", True
    if requested_type == "seven_day_comparison" or any(term in question for term in COMPARISON_TERMS):
        return "seven_day_comparison", False
    if any(term in question for term in {"八字", "生辰", "我的档案"}):
        return "profile_culture", False
    return "culture_knowledge", False


def quota_for_user(db: Session, user: User, now: datetime | None = None) -> QuotaState:
    """计算当前有效权益和今天已用次数。

    正式30天权益优先；没有购买记录时，新账号从创建时间起享受72小时赠送。
    每日统计固定以北京时间自然日计算，与服务器部署时区无关。
    """
    now = now or utc_now_naive()
    paid = db.scalar(select(AIServiceGrant).where(
        AIServiceGrant.user_id == user.id,
        AIServiceGrant.start_at <= now,
        AIServiceGrant.end_at > now,
    ).order_by(AIServiceGrant.end_at.desc()))
    trial_end = user.created_at + timedelta(days=3)
    if paid:
        plan, expires_at, normal_limit, comparison_limit = paid.grant_type, paid.end_at, 50, 5
    elif now < trial_end:
        plan, expires_at, normal_limit, comparison_limit = "new_user_3_days", trial_end, 20, 2
    else:
        plan, expires_at, normal_limit, comparison_limit = None, None, 0, 0

    # 数据库存 UTC 时间；查询边界由北京时间当天零点换算成 UTC，不能直接用服务器日期。
    day_start, next_day_start = beijing_day_bounds_utc_naive(now)
    counts = dict(db.execute(
        select(AIConversationMessage.category, func.count(AIConversationMessage.id))
        .where(
            AIConversationMessage.user_id == user.id,
            AIConversationMessage.created_at >= day_start,
            AIConversationMessage.created_at < next_day_start,
        )
        .group_by(AIConversationMessage.category)
    ).all())
    comparison_used = counts.get("seven_day_comparison", 0)
    # 安全拦截不消耗次数；其他可回答类别都计入普通问答。
    normal_used = sum(count for category, count in counts.items() if category not in {"seven_day_comparison", "high_risk"})
    return QuotaState(bool(plan), plan, expires_at, normal_limit, normal_used, comparison_limit, comparison_used)


def citations_from_contexts(contexts: list[dict]) -> list[dict]:
    """只暴露来源字段，不把内部检索分数或向量主键返回给用户。"""
    return [{
        "document_id": item["document_id"], "chunk_id": item["chunk_id"],
        "title": item["title"], "heading": item["heading"], "source_name": item["source_name"],
        "page_start": item.get("page_start"), "page_end": item.get("page_end"),
    } for item in contexts]


def answer_ai_question(
    db: Session,
    user: User,
    question: str,
    requested_type: str | None,
    store: VectorStore,
    provider: AnswerProvider,
    use_knowledge_base: bool,
) -> tuple[AIConversationMessage, QuotaState, bool]:
    """执行一次问答，并在同一事务内保存答案和引用。

    返回消息、提问前的权益状态和是否拦截。调用方可用权益状态减一计算剩余次数。
    """
    category, blocked = classify_question(question, requested_type)
    quota = quota_for_user(db, user)
    if blocked:
        answer = "这类问题涉及灾祸、疾病、死亡、违法或收益保证，不能依据生辰或传统文化作确定性预测。请根据现实信息并咨询相应专业人士。"
        contexts: list[dict] = []
        model_name = "safety-rule-v1"
    else:
        if not quota.active:
            raise PermissionError("AI国学赠送权益已结束，请开通服务后继续使用")
        if quota.remaining(category) <= 0:
            raise OverflowError("今日该功能使用次数已用完，请明日再试")
        # 内部开关为true时沿用完整RAG链路；false时不查询数据库，引用自然为空。
        # 两条链路共用前面的硬安全分类和模型供应器中的系统级回答边界。
        contexts = hybrid_search(db, question, store, limit=5) if use_knowledge_base else []
        answer = provider.generate(
            question,
            contexts,
            use_knowledge_base=use_knowledge_base,
        )
        model_name = provider.model_name

    message = AIConversationMessage(
        user_id=user.id, question=question, answer=answer, category=category,
        references_json=json.dumps(citations_from_contexts(contexts), ensure_ascii=False),
        model_name=model_name, safety_status="blocked" if blocked else "safe",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message, quota, blocked
