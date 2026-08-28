"""项目知识检索（RAG）公共入口。

实现拆分在 ``autopilot_platform.platform.rag`` 包内：
- hashing 向量检索（默认）
- 关键词回退 / 融合
"""

from __future__ import annotations

from .service import retrieve_for_generation, retrieve_knowledge_context

__all__ = ["retrieve_knowledge_context", "retrieve_for_generation"]
