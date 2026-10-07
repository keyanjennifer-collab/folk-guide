"""会话管理：账号隔离、游标分页、物理删除正文与保留已用次数。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from .ai_schemas import (AIConversationDetail, AIConversationItem, AIConversationPage,
                         AIConversationUpdate, AIFavoriteInput, AIHistoryItem)
from .auth import current_user
from .database import get_db
from .models import AIConversation, AIConversationMessage, AIDeletedUsage, User
from .time_service import utc_now_naive

router = APIRouter()


def owned_conversation(db: Session, user_id: int, conversation_id: int) -> AIConversation:
    row = db.scalar(select(AIConversation).where(
        AIConversation.id == conversation_id, AIConversation.user_id == user_id))
    if row is None:
        raise HTTPException(404, "会话不存在")
    return row


def owned_message(db: Session, user_id: int, message_id: int) -> AIConversationMessage:
    row = db.scalar(select(AIConversationMessage).where(
        AIConversationMessage.id == message_id, AIConversationMessage.user_id == user_id))
    if row is None:
        raise HTTPException(404, "问答记录不存在")
    return row


def message_output(row: AIConversationMessage) -> dict:
    return {"id": row.id, "conversation_id": row.conversation_id,
            "question": row.question, "answer": row.answer, "category": row.category,
            "citations": json.loads(row.references_json), "feedback": row.feedback,
            "favorite": row.favorite, "safety_status": row.safety_status,
            "created_at": row.created_at}


def conversation_output(row: AIConversation, count: int = 0) -> dict:
    return {"id": row.id, "title": row.title, "archived": row.archived,
            "message_count": count, "created_at": row.created_at, "updated_at": row.updated_at}


def delete_messages(db: Session, user_id: int, conversation_id: int | None = None,
                    message_id: int | None = None) -> None:
    filters = [AIConversationMessage.user_id == user_id]
    if conversation_id is not None:
        filters.append(AIConversationMessage.conversation_id == conversation_id)
    if message_id is not None:
        filters.append(AIConversationMessage.id == message_id)
    # 不保留正文和引用；仅当天已用次数必须在删除后仍计入额度。
    rows = db.execute(select(AIConversationMessage.category, AIConversationMessage.created_at)
                      .where(*filters)).all()
    db.add_all([AIDeletedUsage(user_id=user_id, category=category, created_at=created_at)
                for category, created_at in rows
                if category not in {"high_risk", "profile_required"}])
    db.execute(delete(AIConversationMessage).where(*filters))


@router.post("/conversations", response_model=AIConversationItem, status_code=201)
def create_conversation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = AIConversation(user_id=user.id, title="新对话")
    db.add(row)
    db.commit()
    db.refresh(row)
    return conversation_output(row)


@router.get("/conversations", response_model=AIConversationPage)
def list_conversations(
    q: str = Query(default="", max_length=100),
    archived: bool = False, favorites: bool = False,
    limit: int = Query(default=20, ge=1, le=50), cursor: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    filters = [AIConversation.user_id == user.id, AIConversation.archived == archived]
    message_filters = [AIConversationMessage.user_id == user.id,
                       AIConversationMessage.conversation_id == AIConversation.id]
    # 空会话不展示；前端“新建对话”只切换状态，避免历史数量被空记录污染。
    filters.append(select(AIConversationMessage.id).where(*message_filters).exists())
    if q.strip():
        needle = q.strip().lower()
        match = select(AIConversationMessage.id).where(*message_filters, or_(
            func.lower(AIConversationMessage.question).contains(needle, autoescape=True),
            func.lower(AIConversationMessage.answer).contains(needle, autoescape=True))).exists()
        filters.append(or_(func.lower(AIConversation.title).contains(needle, autoescape=True), match))
    if favorites:
        filters.append(select(AIConversationMessage.id).where(
            *message_filters, AIConversationMessage.favorite.is_(True)).exists())
    if cursor:
        try:
            date_text, id_text = cursor.split("|")
            when, row_id = datetime.fromisoformat(date_text), int(id_text)
            if when.tzinfo is not None or row_id < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "分页游标无效") from None
        filters.append(or_(AIConversation.updated_at < when, and_(
            AIConversation.updated_at == when, AIConversation.id < row_id)))
    counts = select(AIConversationMessage.conversation_id.label("cid"),
                    func.count().label("count")).where(
        AIConversationMessage.user_id == user.id).group_by(AIConversationMessage.conversation_id).subquery()
    rows = db.execute(select(AIConversation, func.coalesce(counts.c.count, 0)).outerjoin(
        counts, counts.c.cid == AIConversation.id).where(*filters).order_by(
        AIConversation.updated_at.desc(), AIConversation.id.desc()).limit(limit + 1)).all()
    visible = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = visible[-1][0]
        next_cursor = f"{last.updated_at.isoformat()}|{last.id}"
    return {"items": [conversation_output(row, count) for row, count in visible], "next_cursor": next_cursor}


@router.delete("/conversations", status_code=204)
def clear_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    delete_messages(db, user.id)
    db.execute(delete(AIConversation).where(AIConversation.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}", response_model=AIConversationDetail)
def conversation_detail(conversation_id: int, before_id: int | None = Query(default=None, ge=1),
                        limit: int = Query(default=20, ge=1, le=50),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = owned_conversation(db, user.id, conversation_id)
    filters = [AIConversationMessage.user_id == user.id,
               AIConversationMessage.conversation_id == conversation_id]
    count = db.scalar(select(func.count()).select_from(AIConversationMessage).where(*filters)) or 0
    if before_id:
        filters.append(AIConversationMessage.id < before_id)
    messages = list(db.scalars(select(AIConversationMessage).where(*filters)
                              .order_by(AIConversationMessage.id.desc()).limit(limit + 1)))
    recent = messages[:limit]
    return {**conversation_output(row, count), "messages": [message_output(m) for m in reversed(recent)],
            "next_before_id": recent[-1].id if len(messages) > limit else None}


@router.patch("/conversations/{conversation_id}", response_model=AIConversationItem)
def update_conversation(conversation_id: int, data: AIConversationUpdate,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = owned_conversation(db, user.id, conversation_id)
    if data.title is not None:
        row.title = data.title
    if data.archived is not None:
        row.archived = data.archived
    row.updated_at = utc_now_naive()
    db.commit()
    count = db.scalar(select(func.count()).select_from(AIConversationMessage).where(
        AIConversationMessage.user_id == user.id, AIConversationMessage.conversation_id == row.id)) or 0
    return conversation_output(row, count)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = owned_conversation(db, user.id, conversation_id)
    delete_messages(db, user.id, conversation_id=conversation_id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.delete("/messages/{message_id}", status_code=204)
def delete_message(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    message = owned_message(db, user.id, message_id)
    if message.conversation_id:
        owned_conversation(db, user.id, message.conversation_id).updated_at = utc_now_naive()
    delete_messages(db, user.id, message_id=message_id)
    db.commit()
    return Response(status_code=204)


@router.put("/messages/{message_id}/favorite", response_model=AIHistoryItem)
def favorite_message(message_id: int, data: AIFavoriteInput,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = owned_message(db, user.id, message_id)
    row.favorite = data.favorite
    db.commit()
    return message_output(row)
