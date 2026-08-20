"""PDF 逐页解析服务。

这个模块刻意不把扫描版古籍默认上传到第三方：

1. ``native`` 使用 pypdf 在本机提取已有文字层；
2. ``mineru`` 只有显式配置并选择后才会把文件发送到指定服务；
3. ``auto`` 先本地检查，只有发现扫描页且 MinerU 已启用时才使用 MinerU；
4. 没有 OCR 能力时返回 ``PdfOcrRequiredError``，绝不把空白或残缺文本当作成功。

解析结果始终保留 PDF 页码，后续切块可以生成可核查的引用位置。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx


PDF_PARSER_MODES = {"auto", "native", "mineru"}


class PdfParseError(ValueError):
    """PDF 损坏、加密、超页数或解析服务响应不合法。"""


class PdfOcrRequiredError(PdfParseError):
    """PDF 含有本地文字提取无法读取的扫描页。"""

    def __init__(self, page_count: int, scanned_pages: list[int]) -> None:
        self.page_count = page_count
        self.scanned_pages = scanned_pages
        preview = "、".join(str(page) for page in scanned_pages[:20])
        if len(scanned_pages) > 20:
            preview += "等"
        super().__init__(
            f"检测到需要OCR的扫描页：{preview or '无法确定页码'}。"
            "请配置MinerU后重新解析，不能把未识别页面直接用于AI问答。"
        )


@dataclass(frozen=True)
class PdfTextBlock:
    """PDF 解析后的最小结构块，还没有执行知识切片。"""

    kind: str
    text: str
    page_number: int
    heading_level: int | None = None
    extraction_method: str = "pdf_native"
    ocr_confidence: float | None = None


@dataclass
class PdfExtractionResult:
    """一份 PDF 的逐页解析结果与质量信息。"""

    blocks: list[PdfTextBlock]
    page_count: int
    extraction_method: str
    scanned_pages: list[int] = field(default_factory=list)
    blank_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_pdf_text(value: str) -> str:
    """只做安全的空白归一化，不擅自繁简转换或修改古籍用字。"""
    value = value.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _looks_like_heading(line: str) -> tuple[bool, int | None, str]:
    """保守识别常见古籍卷篇标题，避免把每一个短句都误判成标题。"""
    markdown = re.match(r"^(#{1,6})\s+(.+)$", line)
    if markdown:
        return True, len(markdown.group(1)), markdown.group(2).strip()
    compact = line.strip()
    if len(compact) > 40:
        return False, None, compact
    patterns = (
        r"^第[一二三四五六七八九十百千〇零两0-9]+[卷篇章节部]",
        r"^卷[一二三四五六七八九十百千〇零两0-9]+",
        r"^[上中下]篇$",
        r"^[乾坤屯蒙需讼师比小畜履泰否同人大有谦豫随蛊临观噬嗑贲剥复无妄大畜颐大过坎离咸恒遁大壮晋明夷家人睽蹇解损益夬姤萃升困井革鼎震艮渐归妹丰旅巽兑涣节中孚小过既济未济]卦",
        r"^(序|自序|凡例|目录|目次)$",
    )
    return any(re.search(pattern, compact) for pattern in patterns), 1, compact


def _text_to_blocks(text: str, page_number: int, method: str) -> list[PdfTextBlock]:
    """把一页文字按空行和明确标题拆成结构块，同时保留原页码。"""
    blocks: list[PdfTextBlock] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        content = _normalize_pdf_text("\n".join(paragraph_lines))
        paragraph_lines.clear()
        if content:
            blocks.append(PdfTextBlock("paragraph", content, page_number, extraction_method=method))

    for raw_line in text.splitlines():
        line = _normalize_pdf_text(raw_line)
        if not line:
            flush_paragraph()
            continue
        is_heading, level, heading_text = _looks_like_heading(line)
        if is_heading:
            flush_paragraph()
            blocks.append(PdfTextBlock("heading", heading_text, page_number, level, method))
        else:
            paragraph_lines.append(line)
    flush_paragraph()
    return blocks


def _page_has_image(page: Any) -> bool:
    """检查页面资源是否含图片，用于区分空白页和疑似扫描页。

    某些 PDF 使用内联图片，pypdf 不一定能全部识别。因此当整份文档完全没有
    可提取文字时，调用方仍会把全部页面视为可能需要 OCR。
    """
    try:
        resources = page.get("/Resources")
        if not resources:
            return False
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if not xobjects:
            return False
        for reference in xobjects.get_object().values():
            obj = reference.get_object()
            if str(obj.get("/Subtype")) == "/Image":
                return True
        return False
    except Exception:
        # 图片识别失败不能影响文字页提取；整份无文字时还有最终兜底判断。
        return False


def extract_pdf_native(path: Path, *, max_pages: int, min_text_chars: int) -> PdfExtractionResult:
    """使用 pypdf 在本机逐页提取文字层，并标记疑似扫描页。"""
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - 部署缺依赖时才会发生
        raise PdfParseError("处理PDF需要安装pypdf，请重新安装后端依赖") from exc

    try:
        reader = pypdf.PdfReader(str(path), strict=False)
    except Exception as exc:
        raise PdfParseError("PDF文件损坏或不是有效的PDF") from exc

    if reader.is_encrypted:
        # 即使某些加密 PDF 可以用空密码打开，也不在知识库中静默绕过保护。
        raise PdfParseError("PDF已加密或受密码保护，请提供解除保护且有权使用的版本")

    page_count = len(reader.pages)
    if page_count == 0:
        raise PdfParseError("PDF没有可读取页面")
    if page_count > max_pages:
        raise PdfParseError(f"PDF共{page_count}页，超过当前{max_pages}页的安全上限")

    blocks: list[PdfTextBlock] = []
    scanned_pages: list[int] = []
    blank_pages: list[int] = []
    failed_pages: list[int] = []

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            extracted = page.extract_text() or ""
        except Exception:
            failed_pages.append(page_number)
            continue
        text = _normalize_pdf_text(extracted)
        visible_chars = len(re.sub(r"\s+", "", text))
        has_image = _page_has_image(page)
        if visible_chars < min_text_chars:
            if has_image:
                scanned_pages.append(page_number)
            else:
                blank_pages.append(page_number)
            continue
        blocks.extend(_text_to_blocks(text, page_number, "pdf_native"))

    if failed_pages:
        pages = "、".join(str(page) for page in failed_pages[:20])
        raise PdfParseError(f"PDF第{pages}页提取失败，为避免资料缺失已停止解析")

    # 全文无字时，即便资源字典没有识别到图片，也应按扫描件处理，而不是报告“成功0片”。
    if not blocks:
        suspected = sorted(set(scanned_pages + blank_pages)) or list(range(1, page_count + 1))
        scanned_pages = suspected
        blank_pages = []

    warnings = []
    if blank_pages:
        preview = "、".join(str(page) for page in blank_pages[:20])
        warnings.append(f"检测到无文字空白页：{preview}")
    return PdfExtractionResult(
        blocks=blocks,
        page_count=page_count,
        extraction_method="pdf_native",
        scanned_pages=scanned_pages,
        blank_pages=blank_pages,
        warnings=warnings,
    )


class _TableTextParser(HTMLParser):
    """把 MinerU 返回的简单 HTML 表格转成可检索的行列文字。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"}:
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.current_cell is not None:
            self.current_row.append(_normalize_pdf_text("".join(self.current_cell)))
            self.current_cell = None
        elif tag == "tr" and self.current_row:
            self.rows.append(self.current_row)


def _mineru_item_text(item: dict[str, Any]) -> str:
    """兼容 MinerU content_list 中常见的正文、公式、表格和图片说明字段。"""
    for key in ("text", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_pdf_text(value)
    table = item.get("table_body")
    if isinstance(table, str) and table.strip():
        parser = _TableTextParser()
        parser.feed(table)
        if parser.rows:
            return "\n".join(" | ".join(cell for cell in row) for row in parser.rows)
        return _normalize_pdf_text(re.sub(r"<[^>]+>", " ", table))
    for key in ("image_caption", "table_caption", "image_footnote", "table_footnote"):
        value = item.get(key)
        if isinstance(value, list):
            joined = _normalize_pdf_text("\n".join(str(part) for part in value if part))
            if joined:
                return joined
    return ""


def _parse_mineru_response(data: dict[str, Any], expected_page_count: int) -> PdfExtractionResult:
    """校验 MinerU 响应并按 ``page_idx`` 还原逐页结构。"""
    results = data.get("results")
    if not isinstance(results, dict) or not results:
        raise PdfParseError("MinerU响应缺少results，无法确认解析结果")
    file_result = next(iter(results.values()))
    if not isinstance(file_result, dict):
        raise PdfParseError("MinerU返回的文件结果格式不正确")
    content_list: Any = file_result.get("content_list", [])
    if isinstance(content_list, str):
        try:
            content_list = json.loads(content_list)
        except json.JSONDecodeError as exc:
            raise PdfParseError("MinerU的content_list不是有效JSON") from exc
    if not isinstance(content_list, list) or not content_list:
        # md_content没有可靠逐页定位，不能降级为“全部算第1页”。
        raise PdfParseError("MinerU没有返回可按页定位的content_list")

    blocks: list[PdfTextBlock] = []
    pages_seen: set[int] = set()
    missing_page_index = False
    for item in content_list:
        if not isinstance(item, dict):
            continue
        page_idx = item.get("page_idx")
        if not isinstance(page_idx, int) or page_idx < 0:
            missing_page_index = True
            continue
        page_number = page_idx + 1
        pages_seen.add(page_number)
        text = _mineru_item_text(item)
        if not text:
            continue
        level = item.get("text_level")
        is_heading = isinstance(level, int) and 1 <= level <= 6
        confidence = item.get("score", item.get("confidence"))
        if not isinstance(confidence, (int, float)):
            confidence = None
        elif 1 < confidence <= 100:
            confidence = confidence / 100
        elif confidence < 0 or confidence > 1:
            confidence = None
        blocks.append(PdfTextBlock(
            kind="heading" if is_heading else "paragraph",
            text=text,
            page_number=page_number,
            heading_level=level if is_heading else None,
            extraction_method="pdf_mineru",
            ocr_confidence=float(confidence) if confidence is not None else None,
        ))

    if missing_page_index:
        raise PdfParseError("MinerU部分内容缺少page_idx，为避免错误引用页码已停止入库")
    if not blocks:
        raise PdfParseError("MinerU没有返回可用正文")
    warnings = []
    absent_pages = [page for page in range(1, expected_page_count + 1) if page not in pages_seen]
    if absent_pages:
        preview = "、".join(str(page) for page in absent_pages[:20])
        warnings.append(f"MinerU未返回正文的页面：{preview}；请在审核时对照原PDF")
    return PdfExtractionResult(
        blocks=blocks,
        page_count=expected_page_count,
        extraction_method="pdf_mineru",
        warnings=warnings,
    )


def extract_pdf_mineru(
    path: Path,
    *,
    base_url: str,
    timeout_seconds: float,
    page_count: int,
    client: httpx.Client | None = None,
) -> PdfExtractionResult:
    """调用用户显式配置的 MinerU 服务；函数不会记录文件内容或响应正文。"""
    if not base_url.strip():
        raise PdfParseError("尚未配置MINERU_BASE_URL，不能处理扫描版PDF")
    normalized = base_url.rstrip("/")
    endpoint = normalized if normalized.endswith("/file_parse") else f"{normalized}/file_parse"
    owned_client = client is None
    http_client = client or httpx.Client(timeout=max(timeout_seconds, 1.0))
    try:
        with path.open("rb") as stream:
            response = http_client.post(
                endpoint,
                files={"files": (path.name, stream, "application/pdf")},
                data={
                    "backend": "pipeline",
                    "parse_method": "auto",
                    "formula_enable": "true",
                    "table_enable": "true",
                    "return_md": "true",
                    "return_images": "false",
                    "return_content_list": "true",
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise PdfParseError("MinerU响应不是JSON对象")
        return _parse_mineru_response(payload, page_count)
    except PdfParseError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise PdfParseError("MinerU连接超时或网络不可用") from exc
    except httpx.HTTPStatusError as exc:
        raise PdfParseError(f"MinerU返回HTTP {exc.response.status_code}") from exc
    except (ValueError, KeyError) as exc:
        raise PdfParseError("MinerU响应格式无法识别") from exc
    finally:
        if owned_client:
            http_client.close()


def extract_pdf(
    path: Path,
    *,
    parser_mode: str,
    max_pages: int,
    min_text_chars: int,
    mineru_enabled: bool,
    mineru_base_url: str,
    mineru_timeout_seconds: float,
) -> PdfExtractionResult:
    """按选择的模式解析PDF，并在自动模式下安全决定是否调用OCR。"""
    if parser_mode not in PDF_PARSER_MODES:
        raise PdfParseError("PDF解析模式只能是auto、native或mineru")

    native = extract_pdf_native(path, max_pages=max_pages, min_text_chars=min_text_chars)
    if parser_mode == "native":
        if native.scanned_pages:
            raise PdfOcrRequiredError(native.page_count, native.scanned_pages)
        return native

    if parser_mode == "mineru":
        if not mineru_enabled:
            raise PdfParseError("MinerU未启用，请先配置MINERU_ENABLED=true")
        return extract_pdf_mineru(
            path,
            base_url=mineru_base_url,
            timeout_seconds=mineru_timeout_seconds,
            page_count=native.page_count,
        )

    # auto：文字层完整时留在本机；检测到扫描页时才考虑外部OCR。
    if not native.scanned_pages:
        return native
    if mineru_enabled and mineru_base_url.strip():
        return extract_pdf_mineru(
            path,
            base_url=mineru_base_url,
            timeout_seconds=mineru_timeout_seconds,
            page_count=native.page_count,
        )
    raise PdfOcrRequiredError(native.page_count, native.scanned_pages)
