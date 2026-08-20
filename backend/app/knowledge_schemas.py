"""知识库后台接口的输入输出数据模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeDocumentOutput(BaseModel):
    """文档元数据、审核状态和切片统计。"""
    id: int
    title: str
    source_name: str
    author: str | None
    copyright_status: str
    original_filename: str
    file_hash: str
    file_size: int
    mime_type: str
    status: str
    page_count: int | None
    extraction_method: str | None
    needs_ocr: bool
    unreadable_pages_json: str | None
    parse_warning: str | None
    version: int
    error_message: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    chunk_count: int = 0
    approved_chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkOutput(BaseModel):
    """单个切片及向量同步状态；不包含真实向量数值。"""
    id: int
    document_id: int
    chunk_index: int
    heading: str | None
    content: str
    content_hash: str
    character_count: int
    review_status: str
    page_start: int | None
    page_end: int | None
    extraction_method: str | None
    ocr_confidence: float | None
    vector_id: str | None
    embedding_model: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeChunkUpdate(BaseModel):
    """运营人员人工修订切片的输入，修改后自动退回 pending。"""
    heading: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=1, max_length=5000)


class KnowledgeSearchResult(BaseModel):
    """检索命中的可引用正文和来源。"""
    chunk_id: int
    document_id: int
    title: str
    heading: str | None
    content: str
    source_name: str
    page_start: int | None = None
    page_end: int | None = None
    score: float


class KnowledgeReviewInput(BaseModel):
    """为空表示全部通过；传 ID 列表表示只批准指定片段。"""
    approved_chunk_ids: list[int] | None = None
"""知识库后台接口的数据契约；ORM 对象不会原样无约束地暴露给前端。"""
