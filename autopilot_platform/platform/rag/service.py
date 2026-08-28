"""RAG 编排：嵌入器工厂 + SQLite/FTS5/sqlite-vec 混合检索。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..design.design_models import KnowledgeItemRow
from .context_format import build_context_text
from .embedder_factory import get_embedder
from .index_builder import ensure_index_vectors
from .keyword_retriever import retrieve_keyword
from .types import RagHit, RagResult
from .vector_index_sqlite import hybrid_search
from .vector_retriever import retrieve_vector

logger = logging.getLogger(__name__)


def _load_rows(
    db: Session,
    *,
    project_id: str,
    confirmed_only: bool,
) -> list[KnowledgeItemRow]:
    q = select(KnowledgeItemRow).where(KnowledgeItemRow.project_id == project_id)
    if confirmed_only:
        q = q.where(KnowledgeItemRow.confirmed.is_(True))
    return list(db.scalars(q.order_by(KnowledgeItemRow.created_at.desc()).limit(2000)).all())


def _merge_hits(primary: list[RagHit], secondary: list[RagHit], *, top_k: int) -> list[RagHit]:
    best: dict[str, RagHit] = {}
    for hit in primary + secondary:
        cur = best.get(hit.id)
        if cur is None or hit.score > cur.score:
            best[hit.id] = hit
    merged = sorted(best.values(), key=lambda h: h.score, reverse=True)
    return merged[: max(1, min(int(top_k), 20))]


def retrieve_knowledge_context(
    db: Session,
    *,
    project_id: str,
    query: str,
    top_k: int = 5,
    confirmed_only: bool = False,
    score_threshold: float | None = None,
) -> dict:
    pid = (project_id or "").strip()
    if not pid:
        return RagResult(engine="none").to_dict()

    rows = _load_rows(db, project_id=pid, confirmed_only=confirmed_only)
    if not rows:
        return RagResult(engine="vector_v2").to_dict()

    prev_expire = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = prev_expire

    embedder = get_embedder()
    embedder_name = str(getattr(embedder, "name", "") or "embedder")
    rows_by_id = {str(r.id): r for r in rows}

    try:
        from . import health as rag_health

        ensure_index_vectors(pid, rows, embedder)
        q_vec = embedder.embed_query(query)
        raw_hits, engine_tag = hybrid_search(
            pid, query=query, query_vector=q_vec, top_k=top_k
        )
        vector_hits = [
            RagHit(
                id=str(h["id"]),
                score=float(h["score"]),
                title=str(h.get("title") or ""),
                category=str(h.get("category") or ""),
            )
            for h in raw_hits
        ]
        vector_hits = [h for h in vector_hits if h.id in rows_by_id]
        rag_health.record_success(embedder=f"{embedder_name}:{engine_tag}")
        engine = f"{embedder_name}+{engine_tag}"
        hits = vector_hits
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        logger.warning("hybrid retrieve failed, fallback legacy: %s", exc)
        try:
            from . import health as rag_health

            rag_health.record_failure(
                embedder=embedder_name,
                error=str(exc),
                fallback="legacy_vector+keyword",
            )
        except (OSError, RuntimeError, AttributeError) as health_exc:
            logger.debug("rag health record_failure skipped: %s", health_exc)
        vector_hits = retrieve_vector(rows, query=query, top_k=top_k)
        keyword_hits = retrieve_keyword(rows, query=query, top_k=top_k)
        if vector_hits and keyword_hits:
            hits = _merge_hits(vector_hits, keyword_hits, top_k=top_k)
            engine = f"{embedder_name}+keyword_fallback"
        elif vector_hits:
            hits = vector_hits
            engine = f"{embedder_name}_fallback"
        else:
            hits = keyword_hits
            engine = "keyword_v1"

    thr = 0.0 if score_threshold is None else float(score_threshold)
    if thr > 0:
        hits = [h for h in hits if float(h.score) >= thr]

    context = build_context_text(hits, rows_by_id)
    return RagResult(context_text=context, hits=hits, engine=engine).to_dict()


def retrieve_for_generation(
    db: Session,
    *,
    project_id: str,
    query: str,
    top_k: int | None = None,
    confirmed_only: bool = False,
    score_threshold: float | None = None,
) -> dict:
    """生成 / Chat 用检索：默认读取 AP_RAG_TOP_K / AP_RAG_SCORE_THRESHOLD。"""
    from ..ops.runtime_config import cfg_str

    if top_k is None:
        try:
            top_k = int(cfg_str("AP_RAG_TOP_K", "5") or 5)
        except ValueError:
            top_k = 5
    if score_threshold is None:
        try:
            score_threshold = float(cfg_str("AP_RAG_SCORE_THRESHOLD", "0.3") or 0.3)
        except ValueError:
            score_threshold = 0.3
    return retrieve_knowledge_context(
        db,
        project_id=project_id,
        query=query,
        top_k=top_k,
        confirmed_only=confirmed_only,
        score_threshold=score_threshold,
    )
