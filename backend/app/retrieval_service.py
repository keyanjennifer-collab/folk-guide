"""审核片段向量同步与关键词/向量混合检索。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .knowledge_service import keyword_search
from .models import KnowledgeChunk, KnowledgeDocument
from .vector_store import VectorRecord, VectorStore


def sync_approved_chunks(db: Session, document: KnowledgeDocument, store: VectorStore) -> int:
    """只同步已通过审核的片段，并把外部主键和模型版本写回数据库。"""
    # 重要安全边界：查询条件必须同时限制document_id和approved，不能向外部服务发送待审核文本。
    chunks = db.scalars(select(KnowledgeChunk).where(
        KnowledgeChunk.document_id == document.id,
        KnowledgeChunk.review_status == "approved",
    )).all()
    records = [VectorRecord(
        id=f"knowledge:{chunk.id}:{chunk.content_hash[:12]}",
        text=chunk.content,
        metadata={key: value for key, value in {
            "chunk_id": chunk.id,
            "document_id": document.id,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        }.items() if value is not None},
    ) for chunk in chunks]
    # 当前同步发生在HTTP请求内。
    # TODO（接入外部向量库）：改成任务队列，记录 pending/running/failed 状态并支持退避重试。
    ids = store.upsert(records)
    for chunk, vector_id in zip(chunks, ids, strict=True):
        chunk.vector_id = vector_id
        chunk.embedding_model = store.model_name
    db.commit()
    return len(ids)


def remove_document_vectors(db: Session, document_id: int, store: VectorStore) -> None:
    """先删除外部向量，再清空本地映射，确保停用资料不会继续被召回。"""
    chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    # 先删远端再清本地，避免本地已经忘记vector_id、远端却仍能召回资料。
    # TODO：生产环境需要删除失败补偿任务，处理数据库与远端系统的分布式一致性。
    store.delete([chunk.vector_id for chunk in chunks if chunk.vector_id])
    for chunk in chunks:
        chunk.vector_id = None
        chunk.embedding_model = None


def hybrid_search(db: Session, query: str, store: VectorStore, limit: int = 8) -> list[dict]:
    """以倒数排名融合两路结果，避免不同供应商分数尺度不一致。"""
    # 两路多取一些候选后再融合。60是RRF常用平滑常数，减少第一名分数过度主导。
    keyword_rows = keyword_search(db, query, limit * 2)
    vector_rows = store.query(query, limit * 2)
    scores: dict[int, float] = {}
    for rank, row in enumerate(keyword_rows, start=1):
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0) + 1 / (60 + rank)
    for rank, match in enumerate(vector_rows, start=1):
        chunk_id = int(match.metadata["chunk_id"])
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (60 + rank)
    if not scores:
        return []
    rows = db.execute(
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(
            KnowledgeChunk.id.in_(scores),
            KnowledgeChunk.review_status == "approved",
            KnowledgeDocument.status == "approved",
        )
    ).all()
    result = [{
        "chunk_id": chunk.id, "document_id": document.id, "title": document.title,
        "heading": chunk.heading, "content": chunk.content, "source_name": document.source_name,
        "page_start": chunk.page_start, "page_end": chunk.page_end,
        "score": scores[chunk.id],
    } for chunk, document in rows]
    return sorted(result, key=lambda item: item["score"], reverse=True)[:limit]
