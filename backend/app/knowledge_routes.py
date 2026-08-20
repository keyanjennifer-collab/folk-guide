"""知识库后台路由：上传、解析、审核、向量同步和检索预览。"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .admin_auth import require_admin
from .database import get_db
from .knowledge_schemas import (
    KnowledgeChunkOutput,
    KnowledgeChunkUpdate,
    KnowledgeDocumentOutput,
    KnowledgeReviewInput,
    KnowledgeSearchResult,
)
from .knowledge_service import (
    ALLOWED_EXTENSIONS,
    COPYRIGHT_VALUES,
    MAX_FILE_SIZE,
    MAX_PDF_FILE_SIZE,
    chunk_blocks,
    document_output,
    keyword_search,
    normalize_text,
    parse_file,
    replace_chunks,
    sha256_bytes,
)
from .models import KnowledgeChunk, KnowledgeDocument
from .pdf_service import PDF_PARSER_MODES, PdfOcrRequiredError
from .retrieval_service import hybrid_search, remove_document_vectors, sync_approved_chunks
from .vector_store import get_vector_store
from .config import get_settings


router = APIRouter(tags=["AI国学·知识库后台"])
_configured_storage = get_settings().knowledge_storage_root.strip()
STORAGE_ROOT = Path(_configured_storage).resolve() if _configured_storage else Path(__file__).resolve().parents[2] / "storage" / "knowledge"
ADMIN_PAGE = Path(__file__).with_name("static") / "admin_knowledge.html"


@router.get("/admin/knowledge", include_in_schema=False)
def admin_page():
    """返回本地运营页面；真正的数据接口仍需要管理员 Key。"""
    return FileResponse(ADMIN_PAGE)


def document_or_404(db: Session, document_id: int) -> KnowledgeDocument:
    """集中处理文档不存在的情况，让各路由保持简洁。"""
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return document


def safe_filename(filename: str) -> str:
    """只保留安全文件名字符，并限制长度；返回值不包含任何目录。"""
    # 丢弃客户端路径并限制字符，防止通过文件名越出知识库存储目录。
    base = Path(filename).name
    return re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", base)[:180]


@router.post(
    "/api/admin/knowledge/documents",
    response_model=KnowledgeDocumentOutput,
    summary="上传AI国学知识文档",
)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    source_name: str = Form(...),
    copyright_status: str = Form(...),
    author: str | None = Form(default=None),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """保存原文件与来源信息，但此时既不解析，也不进入检索。"""
    filename = safe_filename(file.filename or "")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="仅支持.docx、.md、.txt和.pdf")
    if copyright_status not in COPYRIGHT_VALUES:
        raise HTTPException(status_code=422, detail="版权状态无效")
    # 当前上限仅 10MB，可以一次读取；如以后放宽限制应改为流式写入。
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件为空")
    size_limit = MAX_PDF_FILE_SIZE if extension == ".pdf" else MAX_FILE_SIZE
    if len(content) > size_limit:
        limit_mb = size_limit // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"{extension}文件不能超过{limit_mb}MB")
    if extension == ".pdf" and not content[:1024].lstrip().startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="文件扩展名是.pdf，但内容不是有效PDF")
    digest = sha256_bytes(content)
    existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.file_hash == digest))
    if existing:
        raise HTTPException(status_code=409, detail=f"文件已上传，文档ID为{existing.id}")
    now = datetime.utcnow()
    directory = STORAGE_ROOT / str(now.year) / f"{now.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    storage_path = directory / f"{digest[:16]}_{filename}"
    # TODO（上线前）：写入对象存储前增加恶意文件扫描；数据库失败时补偿删除孤儿文件。
    storage_path.write_bytes(content)
    document = KnowledgeDocument(
        title=normalize_text(title), source_name=normalize_text(source_name),
        author=normalize_text(author) if author else None, copyright_status=copyright_status,
        original_filename=filename, storage_key=str(storage_path.relative_to(STORAGE_ROOT.parent)),
        file_hash=digest, file_size=len(content), mime_type=file.content_type or "application/octet-stream",
        status="uploaded",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document_output(db, document)


@router.get(
    "/api/admin/knowledge/documents",
    response_model=list[KnowledgeDocumentOutput],
    summary="查询知识文档列表",
)
def list_documents(
    status: str | None = Query(default=None, description="按uploaded、reviewing、approved、failed或disabled状态筛选"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """按最新优先列出文档，可用状态筛选运营工作队列。"""
    query = select(KnowledgeDocument).order_by(desc(KnowledgeDocument.id))
    if status:
        query = query.where(KnowledgeDocument.status == status)
    return [document_output(db, document) for document in db.scalars(query).all()]


@router.get(
    "/api/admin/knowledge/documents/{document_id}",
    response_model=KnowledgeDocumentOutput,
    summary="读取单份知识文档及切片统计",
)
def get_document(document_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """读取单份知识文档及其实时切片统计。"""
    return document_output(db, document_or_404(db, document_id))


@router.post(
    "/api/admin/knowledge/documents/{document_id}/parse",
    response_model=KnowledgeDocumentOutput,
    summary="解析文档并生成待审核切片",
)
def parse_document(
    document_id: int,
    parser_mode: str = Query(default="auto", description="PDF解析模式：auto、native或mineru"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """从原文件提取正文并重新切片，成功后进入 reviewing 状态。"""
    document = document_or_404(db, document_id)
    if document.status == "disabled":
        raise HTTPException(status_code=409, detail="停用文档不能解析")
    if parser_mode not in PDF_PARSER_MODES:
        raise HTTPException(status_code=422, detail="PDF解析模式只能是auto、native或mineru")
    path = STORAGE_ROOT.parent / document.storage_key
    try:
        parsed = parse_file(path, pdf_parser_mode=parser_mode)
        chunks = chunk_blocks(parsed.blocks)
        if not chunks:
            raise ValueError("未提取到可用正文")
        # 解析后先进入人工审核，不能直接进入问答检索。
        replace_chunks(db, document, chunks)
        document.status = "reviewing"
        document.error_message = None
        document.page_count = parsed.page_count
        document.extraction_method = parsed.extraction_method
        document.needs_ocr = parsed.needs_ocr
        document.unreadable_pages_json = json.dumps(parsed.unreadable_pages or [], ensure_ascii=False)
        document.parse_warning = parsed.warning
        document.version += 1
        db.commit()
        db.refresh(document)
    except PdfOcrRequiredError as exc:
        # OCR缺失不是普通“解析崩溃”，保留独立状态供后台明确提示下一步。
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete()
        document.status = "ocr_required"
        document.page_count = exc.page_count
        document.extraction_method = "pdf_native_check"
        document.needs_ocr = True
        document.unreadable_pages_json = json.dumps(exc.scanned_pages, ensure_ascii=False)
        document.parse_warning = str(exc)
        document.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        document.status = "failed"
        document.error_message = str(exc)[:1000]
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return document_output(db, document)


@router.get(
    "/api/admin/knowledge/documents/{document_id}/chunks",
    response_model=list[KnowledgeChunkOutput],
    summary="查看文档的全部知识切片",
)
def list_chunks(document_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """按原文顺序列出切片，供人工检查内容和章节归属。"""
    document_or_404(db, document_id)
    return db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.chunk_index)).all()


@router.put(
    "/api/admin/knowledge/chunks/{chunk_id}",
    response_model=KnowledgeChunkOutput,
    summary="人工修订单个知识切片",
)
def update_chunk(chunk_id: int, data: KnowledgeChunkUpdate, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """修订未发布片段；内容变化会清空旧向量标识并要求重新审核。"""
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="知识片段不存在")
    document = document_or_404(db, chunk.document_id)
    if document.status == "approved":
        raise HTTPException(status_code=409, detail="已发布文档请先停用后再修改")
    content = normalize_text(data.content)
    chunk.heading = normalize_text(data.heading) if data.heading else None
    chunk.content = content
    chunk.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunk.character_count = len(content)
    chunk.review_status = "pending"
    chunk.vector_id = None
    chunk.embedding_model = None
    if chunk.extraction_method in {"pdf_mineru", "pdf_ocr"}:
        # 人工改过的OCR文本不再沿用机器置信度，后续审核依据修订后的正文。
        chunk.extraction_method = "manual_review"
        chunk.ocr_confidence = None
    document.version += 1
    db.commit()
    db.refresh(chunk)
    return chunk


@router.post(
    "/api/admin/knowledge/documents/{document_id}/approve",
    response_model=KnowledgeDocumentOutput,
    summary="审核通过文档及指定切片",
)
def approve_document(
    document_id: int,
    data: KnowledgeReviewInput,
    operator: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审核文档及片段。审核通过仍不代表已经完成向量同步。"""
    document = document_or_404(db, document_id)
    if document.status not in {"reviewing", "failed"}:
        raise HTTPException(status_code=409, detail="只有待审核文档可以审核通过")
    if document.needs_ocr:
        raise HTTPException(status_code=409, detail="文档仍有未识别扫描页，完成OCR后才能审核通过")
    chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    if not chunks:
        raise HTTPException(status_code=409, detail="文档还没有切片")
    # 未指定片段代表全选；指定时会严格校验片段确实属于当前文档。
    selected = set(data.approved_chunk_ids or [chunk.id for chunk in chunks])
    if not selected.issubset({chunk.id for chunk in chunks}):
        raise HTTPException(status_code=422, detail="包含不属于该文档的片段ID")
    low_confidence = [
        chunk for chunk in chunks
        if chunk.id in selected
        and chunk.ocr_confidence is not None
        and chunk.ocr_confidence < get_settings().pdf_min_ocr_confidence
    ]
    if low_confidence:
        preview = "、".join(str(chunk.chunk_index + 1) for chunk in low_confidence[:20])
        raise HTTPException(
            status_code=422,
            detail=f"片段{preview}的OCR置信度过低，请对照原PDF人工修订后再审核",
        )
    for chunk in chunks:
        chunk.review_status = "approved" if chunk.id in selected else "rejected"
    if not any(chunk.review_status == "approved" for chunk in chunks):
        raise HTTPException(status_code=422, detail="至少审核通过一个片段")
    document.status = "approved"
    document.reviewed_by = operator
    document.reviewed_at = datetime.utcnow()
    document.error_message = None
    db.commit()
    db.refresh(document)
    return document_output(db, document)


@router.post(
    "/api/admin/knowledge/documents/{document_id}/disable",
    response_model=KnowledgeDocumentOutput,
    summary="停用文档并移除其向量",
)
def disable_document(document_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """停用文档、停用其片段并删除外部向量映射。"""
    document = document_or_404(db, document_id)
    document.status = "disabled"
    remove_document_vectors(db, document_id, get_vector_store())
    # 停用文档立即使全部片段退出关键词和向量检索。
    for chunk in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all():
        chunk.review_status = "disabled"
    db.commit()
    db.refresh(document)
    return document_output(db, document)


@router.get(
    "/api/admin/knowledge/search",
    response_model=list[KnowledgeSearchResult],
    summary="预览纯关键词知识检索",
)
def search_knowledge(
    q: str = Query(min_length=1, max_length=200, description="要检索的问题或关键词"),
    limit: int = Query(default=8, ge=1, le=20, description="最多返回的知识片段数量"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """纯关键词检索预览，用于向量服务不可用时的基础召回。"""
    return keyword_search(db, q, limit)


@router.post(
    "/api/admin/knowledge/documents/{document_id}/sync-vectors",
    summary="将审核通过的切片同步到向量库",
)
def sync_document_vectors(document_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """人工审核后显式同步，避免未审核文本进入外部服务。"""
    document = document_or_404(db, document_id)
    if document.status != "approved":
        raise HTTPException(status_code=409, detail="只有审核通过的文档可以同步向量")
    store = get_vector_store()
    if not store.health_check():
        raise HTTPException(status_code=503, detail="向量库当前不可用")
    # 目前由运营人员显式触发；接入持久化向量库后应在审核通过时自动提交后台任务。
    count = sync_approved_chunks(db, document, store)
    return {"document_id": document.id, "synced_chunk_count": count, "embedding_model": store.model_name}


@router.get(
    "/api/admin/knowledge/hybrid-search",
    response_model=list[KnowledgeSearchResult],
    summary="预览关键词与向量混合检索",
)
def search_knowledge_hybrid(
    q: str = Query(min_length=1, max_length=200, description="要检索的问题或关键词"),
    limit: int = Query(default=8, ge=1, le=20, description="最多返回的融合检索结果数量"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """运营调试接口；正式 AI 问答之后会复用同一检索服务。"""
    return hybrid_search(db, q, get_vector_store(), limit)
"""AI 国学知识库后台路由：上传、解析、人工审核、向量同步和检索预览。"""
