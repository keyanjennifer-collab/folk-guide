"""可选网页搜索适配器的请求清洗、失败隐藏和结果边界测试。"""

import json

import httpx
import pytest

from app.web_search_service import TavilyWebSearchProvider, WebSearchServiceError, web_search_is_requested


def test_tavily_search_sends_key_server_side_and_cleans_results():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/api/search"
        return httpx.Response(200, json={"results": [{
            "title": "传统节气资料",
            "url": "https://example.com/solar-term",
            "content": "这是网页摘要。",
            "published_date": "2026-08-21",
            "raw_content": "不应传给模型的整页内容",
        }, {
            "title": "无效项",
            "url": "javascript:alert(1)",
            "content": "不应保留",
        }]})

    provider = TavilyWebSearchProvider(
        api_key="search-secret",
        base_url="https://search.example/api",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    results = provider.search("今天是什么节气", max_results=5)
    assert captured["api_key"] == "search-secret"
    assert results == [{
        "title": "传统节气资料",
        "url": "https://example.com/solar-term",
        "content": "这是网页摘要。",
        "published_date": "2026-08-21",
    }]


def test_tavily_error_does_not_expose_upstream_body():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "secret search response"})

    provider = TavilyWebSearchProvider(
        api_key="bad",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(WebSearchServiceError, match="网页搜索服务调用失败") as raised:
        provider.search("测试")
    assert "secret search response" not in str(raised.value)


@pytest.mark.parametrize("question", ["最新节气资料", "请查一下官方来源", "当前政策是什么"])
def test_on_demand_terms_request_search(question: str):
    assert web_search_is_requested(question) is True


def test_normal_question_does_not_request_search_without_always_switch():
    assert web_search_is_requested("《周易》主要讲什么") is False
    assert web_search_is_requested("《周易》主要讲什么", always=True) is True
