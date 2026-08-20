"""PDF解析器的逐页结构和MinerU响应边界测试。"""

import json

import pytest

from app.pdf_service import PdfParseError, _parse_mineru_response


def test_mineru_content_list_keeps_real_page_numbers_and_headings():
    payload = {
        "results": {
            "classic.pdf": {
                "content_list": json.dumps([
                    {"type": "text", "text": "卷一 五行名义", "text_level": 1, "page_idx": 2},
                    {"type": "text", "text": "五行者，往来乎天地之间。", "page_idx": 2, "score": 0.91},
                    {"type": "table", "table_body": "<table><tr><th>行</th><th>色</th></tr><tr><td>木</td><td>青</td></tr></table>", "page_idx": 3},
                ], ensure_ascii=False),
            }
        }
    }
    result = _parse_mineru_response(payload, expected_page_count=4)
    assert result.extraction_method == "pdf_mineru"
    assert [block.page_number for block in result.blocks] == [3, 3, 4]
    assert result.blocks[0].kind == "heading"
    assert result.blocks[1].ocr_confidence == 0.91
    assert "木 | 青" in result.blocks[2].text


def test_mineru_rejects_content_without_page_index():
    payload = {
        "results": {
            "classic.pdf": {
                "content_list": [{"type": "text", "text": "无法定位的正文"}],
            }
        }
    }
    with pytest.raises(PdfParseError, match="page_idx"):
        _parse_mineru_response(payload, expected_page_count=1)
