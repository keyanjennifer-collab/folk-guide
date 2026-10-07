"""紫微单盘与合盘 AI 解读接口。"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_safety import review_model_output
from .auth import current_user
from .config import get_settings
from .database import get_db
from .llm_provider import ModelServiceError, get_answer_provider
from .models import User, ZiweiAnalysisCache, ZiweiChartRecord, ZiweiCompatibilityRecord
from .ziwei_interpret_service import KNOWLEDGE_VERSION, compatibility_prompt, request_hash, single_prompt
from .ziwei_schemas import (
    ZiweiCompatibilityInterpretInput,
    ZiweiCompatibilityInterpretOutput,
    ZiweiInterpretInput,
    ZiweiInterpretOutput,
)

router = APIRouter(prefix="/api/ziwei", tags=["紫微命盘 AI 解读"])


def _clean_answer(answer: str) -> str:
    """清理模型偶尔重复的中文标点，避免小程序出现“。。”。"""
    cleaned = re.sub(r"([。！？；])\1+", r"\1", answer.strip())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _model_answer(prompt: str, context: dict) -> tuple[str, str]:
    provider = get_answer_provider()
    if not provider.ready:
        raise HTTPException(status_code=503, detail="AI模型服务尚未配置")
    try:
        raw = provider.generate(prompt, [], use_knowledge_base=False, ziwei_context=context)
    except ModelServiceError as exc:
        raise HTTPException(status_code=502, detail="紫微解读模型暂时不可用，请稍后重试") from exc
    reviewed = review_model_output(raw, max_chars=get_settings().ai_max_output_chars)
    return _clean_answer(reviewed.answer), provider.model_name


@router.post("/interpret", response_model=ZiweiInterpretOutput, summary="生成紫微单盘主题解读")
def interpret_chart(
    data: ZiweiInterpretInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    record = db.scalar(select(ZiweiChartRecord).where(
        ZiweiChartRecord.id == data.chart_id,
        ZiweiChartRecord.user_id == user.id,
    ))
    if record is None:
        raise HTTPException(status_code=404, detail="命盘不存在")
    chart = json.loads(record.chart_json)
    period_key = data.period_key or (str(chart.get("currentDaXianIndex")) if data.period_type == "daxian" else None)
    key_hash = request_hash("single", chart, data.topic, data.period_type, period_key, data.palace_branch, KNOWLEDGE_VERSION)
    cached = db.scalar(select(ZiweiAnalysisCache).where(
        ZiweiAnalysisCache.user_id == user.id,
        ZiweiAnalysisCache.chart_id == record.id,
        ZiweiAnalysisCache.compatibility_id.is_(None),
        ZiweiAnalysisCache.period_type == data.period_type,
        ZiweiAnalysisCache.period_key == (period_key or ""),
        ZiweiAnalysisCache.topic == data.topic,
        ZiweiAnalysisCache.palace_branch == data.palace_branch,
        ZiweiAnalysisCache.question_hash == key_hash,
        ZiweiAnalysisCache.knowledge_version == KNOWLEDGE_VERSION,
    ))
    if cached:
        return {
            "chart_id": record.id, "topic": data.topic, "period_type": data.period_type,
            "period_key": period_key, "palace_branch": data.palace_branch,
            "answer": cached.answer, "model_name": cached.model_name, "cached": True,
            "knowledge_version": cached.knowledge_version,
        }
    prompt, context = single_prompt(chart, data.topic, data.period_type, period_key, data.palace_branch)
    answer, model_name = _model_answer(prompt, context)
    cache = ZiweiAnalysisCache(
        user_id=user.id, chart_id=record.id, compatibility_id=None,
        period_type=data.period_type, period_key=period_key or "", topic=data.topic,
        palace_branch=data.palace_branch, question_hash=key_hash, answer=answer,
        model_name=model_name, knowledge_version=KNOWLEDGE_VERSION,
    )
    db.add(cache)
    db.commit()
    return {
        "chart_id": record.id, "topic": data.topic, "period_type": data.period_type,
        "period_key": period_key, "palace_branch": data.palace_branch,
        "answer": answer, "model_name": model_name, "cached": False,
        "knowledge_version": KNOWLEDGE_VERSION,
    }


@router.post("/compatibility/analyze", response_model=ZiweiCompatibilityInterpretOutput, summary="生成紫微合盘 AI 解读")
def interpret_compatibility(
    data: ZiweiCompatibilityInterpretInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    record = db.scalar(select(ZiweiCompatibilityRecord).where(
        ZiweiCompatibilityRecord.id == data.compatibility_id,
        ZiweiCompatibilityRecord.user_id == user.id,
    ))
    if record is None:
        raise HTTPException(status_code=404, detail="合盘不存在")
    chart_a, chart_b = json.loads(record.person_a_json), json.loads(record.person_b_json)
    question = (data.question or "").strip()
    key_hash = request_hash("compatibility", chart_a, chart_b, record.relation_type, question, KNOWLEDGE_VERSION)
    cached = db.scalar(select(ZiweiAnalysisCache).where(
        ZiweiAnalysisCache.user_id == user.id,
        ZiweiAnalysisCache.compatibility_id == record.id,
        ZiweiAnalysisCache.chart_id.is_(None),
        ZiweiAnalysisCache.period_type == "compatibility",
        ZiweiAnalysisCache.period_key == record.relation_type,
        ZiweiAnalysisCache.topic == "compatibility",
        ZiweiAnalysisCache.question_hash == key_hash,
        ZiweiAnalysisCache.knowledge_version == KNOWLEDGE_VERSION,
    ))
    if cached:
        return {
            "compatibility_id": record.id, "answer": cached.answer,
            "model_name": cached.model_name, "cached": True,
            "knowledge_version": cached.knowledge_version,
        }
    prompt, context = compatibility_prompt(chart_a.get("chart", chart_a), chart_b.get("chart", chart_b), record.relation_type, question)
    answer, model_name = _model_answer(prompt, context)
    cache = ZiweiAnalysisCache(
        user_id=user.id, chart_id=None, compatibility_id=record.id,
        period_type="compatibility", period_key=record.relation_type, topic="compatibility",
        palace_branch=None, question_hash=key_hash, answer=answer,
        model_name=model_name, knowledge_version=KNOWLEDGE_VERSION,
    )
    db.add(cache)
    db.commit()
    return {
        "compatibility_id": record.id, "answer": answer,
        "model_name": model_name, "cached": False,
        "knowledge_version": KNOWLEDGE_VERSION,
    }
