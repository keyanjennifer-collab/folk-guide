from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from generate_code_guide_doc import ROOT, bullets, code, set_styles, shade, steps, table


OUTPUT = ROOT / "docs" / "AI国学知识库文档导入与审核_实施报告_V1.1.docx"


def build():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.1)
    section.right_margin = Cm(2.1)
    set_styles(doc)
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("AI国学知识库\n文档导入、切片与审核实施报告")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("五行五色财库香项目｜开发交付 V1.0")
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(113, 128, 120)
    doc.add_paragraph()
    box = doc.add_table(rows=1, cols=1)
    shade(box.cell(0, 0), "E9F0EB")
    box.cell(0, 0).text = "本阶段完成不绑定向量库厂商的知识库基础层：原文件上传、哈希去重、Word/Markdown/TXT解析、章节切片、人工修改、版权和来源记录、审核、停用及关键词检索预览。Embedding与外部向量库适配器将在确定服务商后接入。"
    doc.add_paragraph()

    doc.add_heading("01｜已经完成", level=1)
    bullets(doc, [
        "支持.docx、.md和.txt文件上传，单文件最大10MB。",
        "原文件按年份和月份保存在storage/knowledge，文件名使用哈希避免冲突。",
        "SHA-256文件哈希去重，同一内容不能重复上传。",
        "保存标题、来源、作者、版权状态、文件名、大小、MIME类型和版本。",
        "Word解析段落、标题样式和表格；Markdown解析标题；TXT按段落解析。",
        "清理异常空格、换行和不可见空白。",
        "优先按章节切片，长内容按句子拆分，目标约700个中文字符。",
        "每个片段保存标题、正文、字数、内容哈希和审核状态。",
        "支持人工查看和修改切片，修改后自动回到待审核。",
        "支持全部或部分片段审核通过。",
        "只有文档和片段均审核通过才参与检索。",
        "文档停用后，所有片段立即退出检索。",
        "提供关键词检索预览，并返回标题、章节、来源和匹配分数。",
        "提供浏览器知识库管理页面。",
    ])

    doc.add_heading("02｜管理页面", level=1)
    code(doc, "启动Python后端后访问：\nhttp://127.0.0.1:8000/admin/knowledge")
    steps(doc, [
        "填写管理员Key、操作人、标题和资料来源。",
        "选择版权状态：项目原创、公版资料、已获授权或等待授权。",
        "上传.docx、.md或.txt文件。",
        "点击解析，系统生成章节和切片。",
        "查看切片内容，必要时人工修改。",
        "确认内容与来源后审核通过。",
        "在检索预览中输入关键词，检查命中片段。",
        "资料失效或有版权问题时点击停用。",
    ])

    doc.add_heading("03｜新增数据表", level=1)
    table(doc, ["表", "主要字段", "作用"], [
        ["knowledge_documents", "title、source、copyright、storage_key、file_hash、status、version", "原文档元数据和状态"],
        ["knowledge_chunks", "document_id、heading、content、content_hash、review_status、vector_id", "检索和向量化的最小片段"],
    ], [4.0, 7.0, 4.7])

    doc.add_heading("04｜状态流程", level=1)
    code(doc, "uploaded 已上传\n→ reviewing 已解析待审核\n→ approved 审核通过\n→ embedded（下一阶段向量化后）\n\n异常：failed 解析失败\n停用：disabled")
    doc.add_paragraph("片段状态包括pending、approved、rejected和disabled。当前文档approved即代表可用于关键词检索；接外部向量库后，将增加embedded和published的明确区分。")

    doc.add_heading("05｜接口", level=1)
    table(doc, ["接口", "作用"], [
        ["POST /api/admin/knowledge/documents", "上传文件和元数据"],
        ["GET /api/admin/knowledge/documents", "文档列表和状态筛选"],
        ["GET /api/admin/knowledge/documents/{id}", "文档详情"],
        ["POST /api/admin/knowledge/documents/{id}/parse", "解析并重新生成切片"],
        ["GET /api/admin/knowledge/documents/{id}/chunks", "查看切片"],
        ["PUT /api/admin/knowledge/chunks/{id}", "修改切片"],
        ["POST /api/admin/knowledge/documents/{id}/approve", "审核全部或指定片段"],
        ["POST /api/admin/knowledge/documents/{id}/disable", "停用文档和片段"],
        ["GET /api/admin/knowledge/search?q=", "关键词检索预览"],
    ], [8.3, 7.4])

    doc.add_heading("06｜版权和数据边界", level=1)
    bullets(doc, [
        "permission_pending资料可以上传和审核准备，但正式运营前应完成授权确认。",
        "现代译注、课程、公众号和付费文章不能因可复制就视为可用。",
        "古籍原文和现代解释应在标题或来源中明确区分。",
        "用户生辰、个人聊天和订单数据不进入公共知识向量库。",
        "已审核文档不能直接修改片段，需先停用，避免线上答案来源悄然改变。",
    ])

    doc.add_heading("07｜代码文件", level=1)
    table(doc, ["文件", "职责"], [
        ["app/knowledge_service.py", "解析、清洗、切片、哈希、检索"],
        ["app/knowledge_routes.py", "上传、审核、编辑、停用和检索接口"],
        ["app/knowledge_schemas.py", "接口输入输出结构"],
        ["app/static/admin_knowledge.html", "知识库运营页面"],
        ["tests/test_knowledge.py", "知识库专项自动测试"],
        ["app/models.py", "KnowledgeDocument和KnowledgeChunk模型"],
    ], [7.0, 8.7])

    doc.add_heading("08｜测试", level=1)
    doc.add_paragraph("知识库专项测试：4 passed；全项目回归：18 passed。")
    table(doc, ["测试范围", "结果"], [
        ["Markdown", "上传、去重、解析、切片、修改、审核、检索、停用"],
        ["Word", "标题、正文和表格解析"],
        ["TXT", "段落解析和切片"],
        ["安全输入", "拒绝PDF等未支持格式和非法版权状态"],
        ["管理页面", "HTML页面可访问"],
        ["回归", "档案、历法、每日五色及原有接口全部通过"],
    ], [5.0, 10.7])

    doc.add_heading("09｜下一阶段", level=1)
    steps(doc, [
        "确定外部向量库产品和Embedding模型。",
        "实现统一VectorStore适配器，支持upsert、query、delete和health check。",
        "只对approved片段生成Embedding并保存vector_id与模型版本。",
        "实现关键词＋向量混合检索和元数据过滤。",
        "接入AI问题分类、安全检查、提示词和模型。",
        "把AI国学前端模拟答案替换为Python /api/ai/chat。",
        "加入问答次数、引用、历史、反馈和成本统计。",
    ])
    doc.add_paragraph("PDF和扫描件OCR本次暂未加入。PDF正文结构差异较大，建议在真实资料样本确定后单独实现和测试。")

    for section in doc.sections:
        header = section.header.paragraphs[0]
        header.text = "AI国学知识库｜实施报告"
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        footer = section.footer.paragraphs[0]
        footer.text = "五行五色财库香项目 V1.0"
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return doc


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = build()
    document.save(OUTPUT)
    print(OUTPUT)
