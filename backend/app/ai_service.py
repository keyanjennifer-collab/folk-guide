"""正式 AI 国学问答的分类、安全、权益、检索和历史业务逻辑。"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_safety import review_model_output
from .config import get_settings
from .daily_color_cache_service import ensure_personal_color_cache
from .llm_provider import AnswerProvider
from .models import AIConversation, AIConversationMessage, AIDeletedUsage, AIServiceGrant, BirthProfile, User
from .retrieval_service import hybrid_search
from .time_service import beijing_day_bounds_utc_naive, beijing_today, utc_now_naive
from .vector_store import VectorStore
from .web_search_service import WebSearchProvider, WebSearchServiceError, web_search_is_requested


DISCLAIMER = "内容仅用于传统文化学习和生活灵感参考，不构成医疗、法律、投资或其他专业意见。"
logger = logging.getLogger("folk_guide.ai")

# 这些类别不能交给模型自由发挥，否则容易形成健康、死亡、赌博或收益承诺。
HIGH_RISK_TERMS = {
    "死亡", "什么时候死", "血光之灾", "癌症", "诊断", "替代就医",
    "彩票号码", "保证发财", "稳赚", "借钱投资", "违法", "报复",
}
COMPARISON_TERMS = {"七日", "7日", "未来一周", "一周比较", "七天比较"}

# 个人上下文识别使用“明确个人表达”或“当天 + 行动主题”的组合，不能只见到
# “颜色”就读取档案。例如“传统文化中五行怎样对应五色”仍是通用知识问题。
PERSONAL_EXPLICIT_TERMS = {
    "我的五色", "个人五色", "结合我的", "根据我的", "按照我的", "按我的",
    "我的八字", "我的生辰", "我的档案", "我的排名", "个人排名", "我的结果",
    "个人结果", "适合我", "我适合", "我今天",
}
PERSONAL_SUBJECT_TERMS = {"我的", "本人", "个人", "自己"}
TODAY_TERMS = {"今天", "今日", "当天", "本日"}
PERSONAL_ACTION_TERMS = {
    "颜色", "五色", "穿搭", "穿什么", "衣服", "配色", "香品", "用什么香",
    "财库香", "适合做", "适合处理", "不适合", "不宜", "宜做", "注意什么",
    "今日重点", "排名", "结果", "行动", "推进", "合作", "项目", "沟通", "财务", "工作",
}
PROFILE_TERMS = {"八字", "生辰", "四柱", "档案"}


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
    if question_requests_personal_context(question):
        return "personal_daily", False
    if any(term in question for term in {"八字", "生辰", "我的档案"}):
        return "profile_culture", False
    return "culture_knowledge", False


def question_requests_personal_context(question: str) -> bool:
    """判断回答是否确实需要读取当前登录用户的个人五色。

    本函数只做后端可审计的最小分类，不把分类工作交给外部模型。这样普通典籍问题
    不会无故触碰生辰派生结果，个人问题也不会因模型误判而漏读当天结果。
    """
    if any(term in question for term in PERSONAL_EXPLICIT_TERMS):
        return True
    has_action_topic = any(term in question for term in PERSONAL_ACTION_TERMS)
    has_personal_subject = any(term in question for term in PERSONAL_SUBJECT_TERMS)
    asks_about_today = any(term in question for term in TODAY_TERMS)
    has_profile_topic = any(term in question for term in PROFILE_TERMS)
    return has_action_topic and (has_personal_subject or asks_about_today or has_profile_topic)


def quota_for_user(db: Session, user: User, now: datetime | None = None) -> QuotaState:
    """计算当前有效权益和今天已用次数。

    正式30天权益优先；没有购买记录时，新账号从创建时间起享受72小时赠送。
    每日统计固定以北京时间自然日计算，与服务器部署时区无关。
    """
    now = now or utc_now_naive()
    settings = get_settings()
    paid = db.scalar(select(AIServiceGrant).where(
        AIServiceGrant.user_id == user.id,
        AIServiceGrant.start_at <= now,
        AIServiceGrant.end_at > now,
    ).order_by(AIServiceGrant.end_at.desc()))
    trial_end = user.created_at + timedelta(days=3)
    if paid:
        plan, expires_at = paid.grant_type, paid.end_at
        normal_limit = max(0, settings.ai_paid_normal_limit)
        comparison_limit = max(0, settings.ai_paid_comparison_limit)
    elif now < trial_end:
        plan, expires_at = "new_user_3_days", trial_end
        normal_limit = max(0, settings.ai_trial_normal_limit)
        comparison_limit = max(0, settings.ai_trial_comparison_limit)
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
    deleted_counts = db.execute(select(AIDeletedUsage.category, func.count(AIDeletedUsage.id)).where(
        AIDeletedUsage.user_id == user.id, AIDeletedUsage.created_at >= day_start,
        AIDeletedUsage.created_at < next_day_start).group_by(AIDeletedUsage.category)).all()
    for category, count in deleted_counts:
        counts[category] = counts.get(category, 0) + count
    comparison_used = counts.get("seven_day_comparison", 0)
    # 安全拦截不消耗次数；其他可回答类别都计入普通问答。
    normal_used = sum(
        count for category, count in counts.items()
        if category not in {"seven_day_comparison", "high_risk", "profile_required"}
    )
    return QuotaState(bool(plan), plan, expires_at, normal_limit, normal_used, comparison_limit, comparison_used)


def citations_from_contexts(contexts: list[dict]) -> list[dict]:
    """只暴露来源字段，不把内部检索分数或向量主键返回给用户。"""
    return [{
        "kind": "knowledge",
        "document_id": item["document_id"], "chunk_id": item["chunk_id"],
        "title": item["title"], "heading": item["heading"], "source_name": item["source_name"],
        "page_start": item.get("page_start"), "page_end": item.get("page_end"),
    } for item in contexts]


def citations_from_web_results(results: list[dict]) -> list[dict]:
    """把网页来源标成web，不与人工审核知识库或个人规则结果混淆。"""
    return [{
        "kind": "web",
        "document_id": None,
        "chunk_id": None,
        "title": item.get("title") or "网页资料",
        "heading": item.get("published_date"),
        "source_name": item.get("url") or "网页来源",
        "page_start": None,
        "page_end": None,
    } for item in results]


def personal_context_from_payload(payload: dict) -> dict:
    """从个人五色缓存中提取允许发给模型的最小上下文。

    明确采用字段白名单，不能直接把整个 ``payload`` 交给模型。缓存中的档案版本、
    配置指纹、权益计划等内部元数据不属于回答所需信息；原始生辰、手机号、openid
    本来也不在个人五色响应中，仍通过白名单再守一道边界。
    """
    colors = [{
        "rank": item["rank"],
        "name": item["name"],
        "element": item["element"],
        "tendency": item["tendency"],
        "suitable": item["suitable"],
        "resistance": item["resistance"],
        "advice": item["advice"],
        "incense": item["incense"],
        "scent": item["scent"],
        "reason": item["reason"],
    } for item in payload["colors"]]
    return {
        "date": payload["date"],
        "timezone": payload["timezone"],
        "rule_version": payload["rule_version"],
        "precision_mode": payload["precision_mode"],
        "primary_color": payload["primary_color"],
        "supporting_colors": payload["supporting_colors"],
        "combination_advice": payload["combination_advice"],
        "personal_focus": payload["personal_focus"],
        "comparison_note": payload["comparison_note"],
        "culture_note": payload["culture_note"],
        "reminders": payload["reminders"],
        "colors": colors,
    }


def personal_context_citation(context: dict) -> dict:
    """把个人规则结果标成独立来源，不冒充古籍或知识库切片。"""
    precision = "完整四柱" if context["precision_mode"] == "four_pillars" else "三柱参考"
    return {
        "kind": "personal_daily",
        "document_id": None,
        "chunk_id": None,
        "title": "今日个人五色",
        "heading": context["date"],
        "source_name": f"个人规则结果·{precision}·{context['rule_version']}",
        "page_start": None,
        "page_end": None,
    }


def answer_ai_question(
    db: Session,
    user: User,
    question: str,
    requested_type: str | None,
    store: VectorStore,
    provider: AnswerProvider,
    use_knowledge_base: bool,
    web_search_provider: WebSearchProvider | None = None,
    web_search_enabled: bool = False,
    web_search_always: bool = False,
    conversation_id: int | None = None,
) -> tuple[AIConversationMessage, QuotaState, bool]:
    """执行一次问答，并在同一事务内保存答案和引用。

    返回消息、提问前的权益状态和是否拦截。调用方可用权益状态减一计算剩余次数。
    """
    if conversation_id is not None:
        conversation = db.scalar(select(AIConversation).where(
            AIConversation.id == conversation_id, AIConversation.user_id == user.id))
        if conversation is None or conversation.archived:
            raise PermissionError("会话不存在或已归档")
    category, blocked = classify_question(question, requested_type)
    quota = quota_for_user(db, user)
    settings = get_settings()
    personal_context: dict | None = None
    web_results: list[dict] = []
    safety_status = "blocked" if blocked else "safe"
    if blocked:
        answer = "这类问题涉及灾祸、疾病、死亡、违法或收益保证，不能依据生辰或传统文化作确定性预测。请根据现实信息并咨询相应专业人士。"
        contexts: list[dict] = []
        model_name = "safety-rule-v1"
    else:
        if not quota.active:
            raise PermissionError("AI国学赠送权益已结束，请开通服务后继续使用")
        if quota.remaining(category) <= 0:
            raise OverflowError("今日该功能使用次数已用完，请明日再试")

        # 个人问题才读取当前JWT所属用户的档案。普通典籍问答不会查询BirthProfile，
        # 更不会把无关个人数据附加到模型请求中。
        if question_requests_personal_context(question):
            profile = db.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id))
            if profile is None:
                category = "profile_required"
                answer = (
                    "这个问题需要结合你的本人档案和今日个人五色回答。"
                    "请先到“我的 → 本人档案”填写出生日期；不知道时辰也可以使用三柱参考。"
                )
                contexts = []
                model_name = "profile-context-rule-v1"
            else:
                # quota.active为真时plan必然存在；个人缓存函数仍由调用方显式传入权益计划，
                # 保证无权益请求无法绕过门槛生成个人结果。
                if quota.plan is None:  # pragma: no cover - 防御性保护
                    raise PermissionError("当前没有有效的AI国学体验或服务权益")
                personal_payload = ensure_personal_color_cache(
                    db, profile, beijing_today(), quota.plan
                )
                personal_context = personal_context_from_payload(personal_payload)

        if category != "profile_required":
            # 内部开关为true时沿用完整RAG链路；false时不查询知识库，引用自然为空。
            # 个人规则上下文与知识库片段使用不同参数，不能把个人数据写进公共向量库。
            contexts = hybrid_search(db, question, store, limit=5) if use_knowledge_base else []
            # 网页搜索是可选的外部参考层。关闭、未配置Key、非触发问题或上游失败时，
            # 安全降级为模型已有知识，不把搜索异常变成整次问答失败。
            if (
                web_search_enabled
                and web_search_provider is not None
                and web_search_is_requested(question, always=web_search_always)
            ):
                try:
                    web_results = web_search_provider.search(
                        question,
                        max_results=get_settings().web_search_max_results,
                    )
                except WebSearchServiceError:
                    logger.warning("web_search_failed category=%s", category, exc_info=True)
                    web_results = []
            # 仅带入当前账号、当前会话的最近六轮安全通用问答，限制模型上下文体积。
            # 不重用个人五色或生辰回答，避免把过期个人信息作为当天结果。
            history = []
            if conversation_id is not None:
                recent = db.scalars(select(AIConversationMessage).where(
                    AIConversationMessage.user_id == user.id,
                    AIConversationMessage.conversation_id == conversation_id,
                    AIConversationMessage.safety_status == "safe",
                    AIConversationMessage.category.notin_(["high_risk", "profile_required"]),
                ).order_by(AIConversationMessage.id.desc()).limit(6)).all()
                for prior in reversed(recent):
                    citations = json.loads(prior.references_json)
                    if question_requests_personal_context(prior.question) or any(
                        c.get("kind") == "personal_daily" for c in citations):
                        continue
                    history.extend([{"role": "user", "content": prior.question[:500]},
                                    {"role": "assistant", "content": prior.answer[:1000]}])
            history_options = {"conversation_history": history} if history else {}
            answer = provider.generate(
                question,
                contexts,
                use_knowledge_base=use_knowledge_base,
                personal_context=personal_context,
                web_results=web_results,
                **history_options,
            )
            # 模型提示词是第一道约束；这里在持久化和返回前再做确定性复核，
            # 被拦截的原文不会进入数据库，也不会写入日志。
            reviewed = review_model_output(
                answer,
                max_chars=settings.ai_max_output_chars,
            )
            answer = reviewed.answer
            safety_status = reviewed.status
            if reviewed.filtered:
                logger.warning(
                    "ai_output_filtered category=%s reason=%s",
                    category,
                    reviewed.reason,
                )
            model_name = provider.model_name

    citations = citations_from_contexts(contexts)
    citations.extend(citations_from_web_results(web_results))
    if personal_context is not None:
        citations.append(personal_context_citation(personal_context))

    # 持久化会话与回答共用事务；模型失败不会留下空会话。
    if conversation_id is None:
        conversation = AIConversation(user_id=user.id, title=question[:200])
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
    message = AIConversationMessage(
        user_id=user.id, conversation_id=conversation_id, question=question, answer=answer, category=category,
        references_json=json.dumps(citations, ensure_ascii=False),
        model_name=model_name, safety_status=safety_status,
    )
    db.add(message)
    if conversation_id is not None:
        conversation = db.get(AIConversation, conversation_id)
        if conversation:
            conversation.updated_at = utc_now_naive()
            if conversation.title == "新对话":
                conversation.title = question[:200]
    db.commit()
    db.refresh(message)
    return message, quota, blocked
