from fastapi.testclient import TestClient

from app.main import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_routes_are_grouped_and_ai_status_is_explicit():
    """防止新接口重新掉进Swagger的default分组或误称正式AI已经接入。"""
    schema = app.openapi()
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {
        "账号与微信登录", "生辰档案与历法", "今日五色·用户端",
        "今日五色·运营后台", "AI国学·用户问答", "AI国学·知识库后台",
    }.issubset(tag_names)

    operations = [
        operation
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "delete", "patch"}
    ]
    assert operations
    assert all(operation.get("tags") for operation in operations)
    assert all("default" not in operation["tags"] for operation in operations)

    ai_chat = schema["paths"]["/api/ai/chat"]["post"]
    assert ai_chat["tags"] == ["AI国学·用户问答"]
    assert ai_chat["summary"] == "提交AI国学问题并返回引用"
    assert "answer_ready" in ai_chat["description"]
    assert "环境配置控制" in ai_chat["description"]

    legacy_chat = schema["paths"]["/api/chat"]["post"]
    assert legacy_chat["deprecated"] is True
    assert legacy_chat["tags"] == ["旧版兼容接口"]
