"""可选网页搜索供应器。

网页搜索与古籍知识库是两条不同链路：搜索结果未经人工审核，只能作为临时网页
参考；知识库结果才可以标为 ``knowledge``。本模块默认关闭，关闭时不会创建网络
客户端，也不会发出任何搜索请求。

当前使用 Tavily 的通用 HTTP 接口，因为项目已有 httpx 依赖，且不把某家模型供应商
绑定到搜索层。以后替换供应商只需实现 ``WebSearchProvider.search`` 协议。
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from .config import get_settings


logger = logging.getLogger("folk_guide.web_search")


class WebSearchServiceError(RuntimeError):
    """搜索服务超时、限流、上游错误或返回结构无效。"""


class WebSearchProvider(Protocol):
    """AI问答链路依赖的最小搜索接口。"""

    provider_name: str
    ready: bool

    def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        """返回标题、摘要、URL和可选发布日期，不返回搜索供应商原始响应。"""
        ...


class TavilyWebSearchProvider:
    """Tavily搜索适配器；API Key只保存在服务端，不进入模型提示词。"""

    provider_name = "tavily"
    ready = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("网页搜索API Key未配置")
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/search"
        self.client = client or httpx.Client(timeout=max(timeout_seconds, 1.0))

    def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        """搜索并清洗为模型需要的最小字段，限制摘要长度防止提示词膨胀。"""
        cleaned_query = query.strip()
        if not cleaned_query:
            return []
        payload = {
            "api_key": self.api_key,
            "query": cleaned_query[:500],
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            response = self.client.post(self.endpoint, json=payload)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "搜索服务暂时不可用", request=response.request, response=response
                )
            response.raise_for_status()
            body = response.json()
            raw_results = body.get("results")
            if not isinstance(raw_results, list):
                raise ValueError("搜索结果结构无效")
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
            # 不把上游响应正文或Key信息带到小程序；调用方会安全降级到模型已有知识。
            raise WebSearchServiceError("网页搜索服务调用失败") from exc
        except (TypeError, AttributeError, KeyError) as exc:
            raise WebSearchServiceError("网页搜索结果无法解析") from exc

        cleaned: list[dict] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "网页资料").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or "").strip()
            if not url.startswith(("http://", "https://")) or not content:
                continue
            cleaned.append({
                "title": title[:300],
                "url": url[:1000],
                "content": content[:3000],
                "published_date": str(item.get("published_date") or "").strip()[:40] or None,
            })
        return cleaned[: max(1, min(max_results, 10))]


def _build_provider() -> WebSearchProvider | None:
    """根据配置构造搜索供应器；关闭或缺Key时返回None并安全降级。"""
    settings = get_settings()
    if not settings.ai_web_search_enabled:
        return None
    if settings.web_search_provider.lower() != "tavily":
        logger.warning("web_search_disabled reason=unsupported_provider provider=%s", settings.web_search_provider)
        return None
    if not settings.web_search_api_key:
        logger.warning("web_search_disabled reason=missing_api_key")
        return None
    try:
        return TavilyWebSearchProvider(
            api_key=settings.web_search_api_key,
            base_url=settings.web_search_base_url,
            timeout_seconds=settings.web_search_timeout_seconds,
        )
    except ValueError:
        logger.warning("web_search_disabled reason=invalid_configuration")
        return None


_provider: WebSearchProvider | None = _build_provider()


def get_web_search_provider() -> WebSearchProvider | None:
    """获取启动时根据.env构造的搜索供应器；修改.env后需要重启后端。"""
    return _provider


def set_web_search_provider(provider: WebSearchProvider | None) -> None:
    """仅供测试替换搜索供应器，不能由用户请求动态修改。"""
    global _provider
    _provider = provider


def web_search_is_requested(question: str, *, always: bool = False) -> bool:
    """判断是否值得联网，避免每个普通问题都产生搜索费用。

    ``always`` 由后端环境配置控制，不接受用户输入；高风险问题在更早的AI规则层
    已拦截，不会进入搜索。个人五色等确定性结果默认也可只用后端规则和模型知识。
    """
    if always:
        return True
    terms = {
        "最新", "实时", "目前", "当前", "最近", "新闻", "政策", "法规", "官方",
        "来源", "出处", "原文", "查一下", "搜索", "联网", "网上", "资料",
    }
    return any(term in question for term in terms)
