"""OpenAI 兼容 Embeddings API。"""

from __future__ import annotations

import logging
from typing import Sequence

import httpx

from ..ai import ai_config

logger = logging.getLogger(__name__)


#: 单次索引重建最多送多少条文本（超出截断），避免一次刷全量知识库打爆 token
MAX_EMBED_ITEMS = 512
EMBED_BATCH_SIZE = 16


class OpenAIEmbedder:
    name = "openai_embeddings_v1"

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or ai_config.ai_base_url()).rstrip("/")
        self.api_key = api_key or ai_config.ai_api_key()
        self.model = model or ai_config.ai_embedding_model()
        self.timeout = timeout

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """批量嵌入；受日 token 预算约束，厂商异常统一转 RuntimeError 以便上层降级。"""
        from ..ai import ai_usage

        items = [str(t or "") for t in texts]
        if not items:
            return []
        if len(items) > MAX_EMBED_ITEMS:
            raise RuntimeError(
                f"单次嵌入条数超上限（{len(items)}>{MAX_EMBED_ITEMS}），请分批重建索引"
            )
        if not self.api_key:
            raise RuntimeError("OpenAI embedder 需要 AP_AI_API_KEY")
        ai_usage.check_budget_before_call()
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        out: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for i in range(0, len(items), EMBED_BATCH_SIZE):
                    batch = items[i : i + EMBED_BATCH_SIZE]
                    resp = client.post(
                        url,
                        headers=headers,
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    self._record(data)
                    rows = list(data.get("data") or [])
                    rows.sort(key=lambda r: int(r.get("index", 0)))
                    for row in rows:
                        emb = row.get("embedding") or []
                        out.append([float(x) for x in emb])
        except httpx.HTTPError as exc:
            raise RuntimeError(f"embeddings 调用失败: {exc}") from exc
        if len(out) != len(items):
            raise RuntimeError(
                f"embeddings 数量不匹配：期望 {len(items)} 实际 {len(out)}"
            )
        return out

    def _record(self, payload: dict) -> None:
        """按响应 usage 记账到当前 billing scope（无 usage 时按 0 记录）。"""
        from ..ai import ai_usage

        try:
            ai_usage.record_usage(
                ai_usage.extract_usage(payload),
                source="embedding",
                model=self.model,
            )
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.debug("embedding usage record skipped: %s", exc)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
