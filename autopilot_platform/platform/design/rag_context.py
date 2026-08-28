"""兼容旧 import：``from .rag_context import retrieve_knowledge_context``。"""

from __future__ import annotations

from ..rag import retrieve_knowledge_context

__all__ = ["retrieve_knowledge_context"]
