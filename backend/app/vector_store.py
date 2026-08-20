"""知识库向量存储的统一接口。

业务代码只依赖 VectorStore 协议。当前内置的 memory 实现用于本地开发和测试，
未来接入云向量库时实现相同的 upsert/query/delete/health_check 即可。
"""

import math
import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VectorRecord:
    """准备写入向量库的文本、稳定主键和过滤元数据。"""
    id: str
    text: str
    metadata: dict


@dataclass(frozen=True)
class VectorMatch:
    """向量库返回的匹配主键、相似度和元数据。"""
    id: str
    score: float
    metadata: dict


class VectorStore(Protocol):
    """任何外部向量库适配器都必须实现的最小能力集合。"""
    model_name: str

    def upsert(self, records: list[VectorRecord]) -> list[str]:
        """新增或覆盖向量记录，并按输入顺序返回外部主键。"""
        ...

    def query(self, text: str, limit: int = 8) -> list[VectorMatch]:
        """把自然语言问题向量化并返回最相关记录。"""
        ...

    def delete(self, ids: list[str]) -> None:
        """删除指定外部记录；不存在时应当幂等成功。"""
        ...

    def health_check(self) -> bool:
        """快速检查供应商服务是否可用。"""
        ...


def _tokens(text: str) -> set[str]:
    """本地实现使用字符二元组模拟语义相似度，不等同于真实 Embedding。"""
    compact = re.sub(r"\s+", "", text.lower())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


class MemoryVectorStore:
    """进程内向量库替身：无费用、可测试，重启后数据会清空。"""

    model_name = "local-bigram-v1"

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> list[str]:
        """把记录放入当前Python进程内存；重启即丢失。"""
        for record in records:
            self._records[record.id] = record
        return [record.id for record in records]

    def query(self, text: str, limit: int = 8) -> list[VectorMatch]:
        """以中文字符二元组余弦相似度模拟检索，仅供流程测试。"""
        query_tokens = _tokens(text)
        matches = []
        for record in self._records.values():
            record_tokens = _tokens(record.text)
            denominator = math.sqrt(len(query_tokens) * len(record_tokens))
            score = len(query_tokens & record_tokens) / denominator if denominator else 0.0
            if score > 0:
                matches.append(VectorMatch(record.id, score, record.metadata))
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]

    def delete(self, ids: list[str]) -> None:
        """从内存字典删除记录，重复删除不会报错。"""
        for vector_id in ids:
            self._records.pop(vector_id, None)

    def health_check(self) -> bool:
        """内存实现没有外部依赖，因此进程存活时固定可用。"""
        return True


# 单进程原型使用共享实例。
# TODO（接入向量供应商）：改为持久化客户端；启动时检测数据库映射与远端索引是否一致。
_store: VectorStore = MemoryVectorStore()


def get_vector_store() -> VectorStore:
    """取得当前向量库实现，路由和业务服务不关心具体供应商。"""
    return _store


def set_vector_store(store: VectorStore) -> None:
    """测试及供应商初始化入口。"""
    global _store
    _store = store
