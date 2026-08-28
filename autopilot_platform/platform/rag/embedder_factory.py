"""按配置选择嵌入器：本地 hashing / 远程 OpenAI 兼容 / auto。"""

from __future__ import annotations

import logging

from ..ai import ai_config
from .hashing_embedder_adapter import HashingEmbedder
from .openai_embedder import OpenAIEmbedder

logger = logging.getLogger(__name__)


def rag_embedder_mode() -> str:
    """auto | hashing | openai

    - hashing：本地离线（无外网、无 Key）
    - openai：远程 Embedding API（``AP_AI_BASE_URL`` + Key + embedding model）
    - auto：有可用远程配置则 openai，否则 hashing
    """
    return ai_config.rag_embedder()


def get_embedder():
    mode = rag_embedder_mode()
    if mode == "hashing":
        return HashingEmbedder()
    if mode == "openai":
        return OpenAIEmbedder()
    # auto：优先远程，不可用则本地
    if ai_config.ai_api_key():
        try:
            emb = OpenAIEmbedder()
            if emb.api_key and emb.base_url and ai_config.ai_embedding_model():
                return emb
        except Exception as exc:  # noqa: BLE001
            logger.debug("openai embedder unavailable, fallback hashing: %s", exc)
    return HashingEmbedder()
