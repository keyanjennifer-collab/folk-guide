"""OpenAI兼容模型供应器的请求、引用提示和失败边界测试。"""

import json

import httpx
import pytest

from app.llm_provider import ModelServiceError, OpenAICompatibleAnswerProvider, classic_scope_for_question


def context() -> list[dict]:
    return [{
        "title": "五行大义",
        "heading": "论五行",
        "source_name": "公版整理本",
        "content": "五行者，金木水火土也。此处为自动测试资料。",
    }]


def test_openai_compatible_provider_sends_grounded_prompt():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "五行是传统分类框架。[资料1]"}}]})

    provider = OpenAICompatibleAnswerProvider(
        api_key="test-key",
        base_url="https://model.example/v1",
        model="test-model",
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    answer = provider.generate("什么是五行？", context())
    assert provider.endpoint == "https://model.example/v1/chat/completions"
    assert answer == "五行是传统分类框架。[资料1]"
    assert captured["model"] == "test-model"
    assert "唯一允许使用的参考资料" in captured["messages"][1]["content"]
    assert "五行大义" in captured["messages"][1]["content"]


def test_provider_does_not_call_model_without_approved_context():
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("没有知识片段时不应请求外部模型")

    provider = OpenAICompatibleAnswerProvider(
        api_key="test-key",
        base_url="https://model.example/v1",
        model="test-model",
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert "没有找到足够相关的资料" in provider.generate("未知问题", [])


def test_direct_mode_calls_model_with_internal_classic_scope_and_no_fake_citation():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "五行是传统分类与关系框架。"}}]})

    provider = OpenAICompatibleAnswerProvider(
        api_key="test-key",
        base_url="https://model.example/v1",
        model="test-model",
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    answer = provider.generate("《五行大义》如何理解五色？", [], use_knowledge_base=False)
    assert answer == "五行是传统分类与关系框架。"
    assert "《五行大义》" in captured["messages"][1]["content"]
    assert "不要向用户解释训练数据" in captured["messages"][0]["content"]
    assert "不要输出[资料1]" in captured["messages"][0]["content"]


@pytest.mark.parametrize(("question", "expected"), [
    ("《周易》主要讲什么", "《周易》"),
    ("《五行大义》怎样解释五色", "《五行大义》"),
    ("《增删卜易》的世应是什么", "《增删卜易》"),
    ("《渊海子平》的十神概念", "《渊海子平》"),
    ("《奇门遁甲统宗》的八门", "《奇门遁甲统宗》"),
    ("《紫微斗数全书》的命宫", "《紫微斗数全书》"),
    ("《协纪辨方书》与时序", "《协纪辨方书》"),
    ("《三命通会》的格局", "《三命通会》"),
    ("《滴天髓》如何谈日主", "《滴天髓》"),
    ("《子平真诠》的格局", "《子平真诠》"),
    ("《穷通宝鉴》中的调候", "《穷通宝鉴》"),
    ("《梅花易数》的体用", "《梅花易数》"),
    ("《黄帝内经》的五色观", "《黄帝内经》"),
])
def test_each_planned_classic_routes_to_its_internal_scope(question: str, expected: str):
    assert expected in classic_scope_for_question(question)


def test_provider_hides_upstream_error_body():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "secret upstream detail"}})

    provider = OpenAICompatibleAnswerProvider(
        api_key="bad-key",
        base_url="https://model.example/v1/chat/completions",
        model="test-model",
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ModelServiceError, match="模型服务调用失败") as raised:
        provider.generate("什么是五行？", context())
    assert "secret upstream detail" not in str(raised.value)
