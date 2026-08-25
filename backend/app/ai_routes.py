"""正式 AI 国学问答、权益、历史和反馈的用户端路由。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .ai_schemas import AIFeedbackInput, AIChatInput, AIChatOutput, AIHistoryItem, AIQuotaOutput
from .ai_rate_limit import AIRateLimitExceeded, enforce_ai_rate_limit
from .ai_service import DISCLAIMER, answer_ai_question, quota_for_user
from .auth import current_user
from .config import get_settings
from .database import get_db
from .llm_provider import ModelServiceError, get_answer_provider
from .models import AIConversationMessage, KnowledgeChunk, KnowledgeDocument, User
from .vector_store import get_vector_store
from .web_search_service import get_web_search_provider


router = APIRouter(prefix="/api/ai", tags=["AI国学·用户问答"])


def quota_output(quota, provider, approved_chunk_count: int, use_knowledge_base: bool) -> dict:
    """把内部权益对象转换成前端所需字段。"""
    return {
        "active": quota.active, "plan": quota.plan, "expires_at": quota.expires_at,
        "normal_limit": quota.normal_limit, "normal_used": quota.normal_used,
        "normal_remaining": quota.remaining("culture_knowledge"),
        "comparison_limit": quota.comparison_limit, "comparison_used": quota.comparison_used,
        "comparison_remaining": quota.remaining("seven_day_comparison"),
        # 前端只需要知道问答是否就绪，不暴露内部是否启用知识库或片段数量。
        "answer_ready": provider.ready and (not use_knowledge_base or approved_chunk_count > 0),
    }


@router.get(
    "/quota",
    response_model=AIQuotaOutput,
    summary="读取AI国学权益与今日剩余次数",
    response_description="当前服务计划、到期时间及普通问答/七日比较次数",
)
def get_quota(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """前端进入AI国学页面时首先调用。

    新用户从账号创建时间起获得3天体验；普通问答与七日比较分别计算每日次数。
    本接口不扣次数，只返回当前JWT所属用户的真实权益状态。
    """
    approved_chunk_count = db.scalar(
        select(func.count(KnowledgeChunk.id))
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(
            KnowledgeChunk.review_status == "approved",
            KnowledgeDocument.status == "approved",
        )
    ) or 0
    settings = get_settings()
    return quota_output(
        quota_for_user(db, user), get_answer_provider(), approved_chunk_count,
        settings.ai_use_knowledge_base,
    )


@router.post(
    "/chat",
    response_model=AIChatOutput,
    summary="提交AI国学问题并返回引用",
    response_description="回答、问题分类、安全状态、引用资料及提问后的剩余次数",
)
def chat_ai(data: AIChatInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """执行完整的AI国学问答链路。

    处理顺序为：安全分类 → 权益/次数检查 → 按后端策略准备回答上下文 →
    答案生成 → 保存历史和可用引用。高风险问题会被规则拦截且不扣次数。
    小程序只通过 ``GET /api/ai/quota`` 的 ``answer_ready`` 判断服务是否可用；
    是否启用知识库检索由后端环境配置控制，不暴露给用户页面。
    """
    settings = get_settings()
    try:
        enforce_ai_rate_limit(
            user.id,
            enabled=settings.ai_rate_limit_enabled,
            max_requests=settings.ai_rate_limit_max_requests,
            window_seconds=settings.ai_rate_limit_window_seconds,
        )
    except AIRateLimitExceeded as exc:
        # 短窗口限流与每日权益是两层不同边界；这里不消耗AI次数，也不写入问答历史。
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试",
            headers={"Retry-After": str(max(1, int(settings.ai_rate_limit_window_seconds)))},
        ) from exc
    # PermissionError和OverflowError是服务层业务信号，在HTTP边界分别转换为403和429。
    try:
        message, before_quota, blocked = answer_ai_question(
            db, user, data.question.strip(), data.question_type,
            get_vector_store(), get_answer_provider(),
            settings.ai_use_knowledge_base,
            get_web_search_provider(),
            settings.ai_web_search_enabled,
            settings.ai_web_search_always,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ModelServiceError as exc:
        # 不把供应商原始响应或异常堆栈返回给小程序。
        raise HTTPException(status_code=502, detail="AI模型服务暂时不可用，请稍后重试") from exc
    # 安全拦截和“尚无本人档案”的确定性引导都没有调用模型，不消耗用户次数。
    consumed = 0 if blocked or message.category == "profile_required" else 1
    return {
        "message_id": message.id, "answer": message.answer, "category": message.category,
        "blocked": blocked, "citations": json.loads(message.references_json),
        "remaining_today": max(before_quota.remaining(message.category) - consumed, 0),
        "model_name": message.model_name, "safety_status": message.safety_status,
        "disclaimer": DISCLAIMER,
    }


@router.get(
    "/history",
    response_model=list[AIHistoryItem],
    summary="读取本人的AI国学问答历史",
)
def history(
    limit: int = Query(default=20, ge=1, le=100, description="最多返回的历史记录数量，按最新优先"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """按最新优先读取本人历史，user_id 条件防止跨账号访问。"""
    # TODO（数据规模增长后）：使用游标分页，避免深页OFFSET性能下降和新消息导致页码漂移。
    rows = db.scalars(select(AIConversationMessage).where(
        AIConversationMessage.user_id == user.id
    ).order_by(desc(AIConversationMessage.id)).limit(limit)).all()
    return [{
        "id": row.id, "question": row.question, "answer": row.answer,
        "category": row.category, "citations": json.loads(row.references_json),
        "feedback": row.feedback, "safety_status": row.safety_status,
        "created_at": row.created_at,
    } for row in rows]


@router.put(
    "/messages/{message_id}/feedback",
    response_model=AIHistoryItem,
    summary="评价或纠正一条AI国学回答",
)
def feedback(
    message_id: int,
    data: AIFeedbackInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """反馈只能修改本人消息，不能通过猜测 ID 操作他人记录。"""
    message = db.scalar(select(AIConversationMessage).where(
        AIConversationMessage.id == message_id,
        AIConversationMessage.user_id == user.id,
    ))
    if not message:
        raise HTTPException(status_code=404, detail="问答记录不存在")
    message.feedback = data.rating
    message.feedback_note = data.note.strip() if data.note else None
    db.commit()
    db.refresh(message)
    return {
        "id": message.id, "question": message.question, "answer": message.answer,
        "category": message.category, "citations": json.loads(message.references_json),
        "feedback": message.feedback, "safety_status": message.safety_status,
        "created_at": message.created_at,
    }
