"""Document analysis services."""
from __future__ import annotations
import logging
import re
from autopilot_platform.platform.ops.runtime_config import design_chunk_size
logger = logging.getLogger(__name__)


def _normalize_analysis_type(raw: str | None) -> str:
    t = (raw or 'requirements').strip().lower()
    allowed = {'requirements', 'test_points', 'business_rules', 'comprehensive'}
    if t not in allowed:
        raise ValueError(f'不支持的分析类型: {raw}（允许: requirements|test_points|business_rules|comprehensive）')
    return t

def _split_text_chunks(text: str, *, max_items: int, chunk_limit: int | None=None) -> list[str]:
    """按空行/标题切分，并用 AP_CHUNK_SIZE 限制单块长度（过长再切）。"""
    limit = int(chunk_limit if chunk_limit is not None else design_chunk_size())
    limit = max(32, limit)
    raw = [c.strip() for c in re.split('\\n{2,}', text or '') if c.strip()]
    if len(raw) <= 1:
        parts = re.split('(?m)^#{1,3}\\s+', text or '')
        raw = [c.strip() for c in parts if c.strip()] or raw
    if not raw and (text or '').strip():
        raw = [(text or '').strip()]
    chunks: list[str] = []
    for block in raw:
        if len(block) <= limit:
            chunks.append(block)
            continue
        start = 0
        while start < len(block) and len(chunks) < max(1, max_items) * 2:
            end = min(len(block), start + limit)
            if end < len(block):
                cut = block.rfind('\n', start, end)
                if cut > start + limit // 4:
                    end = cut
            piece = block[start:end].strip()
            if piece:
                chunks.append(piece)
            start = end if end > start else start + limit
    return chunks[:max(1, max_items)]

def _heuristic_test_points(text: str, *, max_items: int=20) -> list[dict[str, str]]:
    chunks = _split_text_chunks(text, max_items=max_items)
    out: list[dict[str, str]] = []
    for i, chunk in enumerate(chunks[:max(1, max_items)], start=1):
        title = chunk.splitlines()[0][:120]
        out.append({'id': f'TP_{i:03d}', 'name': title or f'测试点#{i}', 'description': chunk[:4000], 'type': 'functional', 'priority': 'P2'})
    return out

def _heuristic_business_rules(text: str, *, max_items: int=20) -> list[dict[str, str]]:
    chunks = _split_text_chunks(text, max_items=max_items)
    out: list[dict[str, str]] = []
    for i, chunk in enumerate(chunks[:max(1, max_items)], start=1):
        title = chunk.splitlines()[0][:120]
        out.append({'id': f'BR_{i:03d}', 'name': title or f'业务规则#{i}', 'description': chunk[:4000], 'type': 'validation', 'condition': '文档段落触发', 'priority': 'P2'})
    return out

def _heuristic_requirement_drafts(text: str, *, max_requirements: int=20) -> list[dict[str, str]]:
    """按空行 / Markdown 标题切分（无 LLM 时的回退）；单块受 AP_CHUNK_SIZE 约束。"""
    limit = max(100, design_chunk_size())
    content_cap = max(limit, min(8000, limit * 4))
    chunks = _split_text_chunks(text, max_items=max_requirements, chunk_limit=limit)
    out: list[dict[str, str]] = []
    for i, chunk in enumerate(chunks[:max(1, max_requirements)], start=1):
        title = chunk.splitlines()[0][:120]
        out.append({'title': title or f'需求#{i}', 'content': chunk[:content_cap], 'req_type': 'functional', 'priority': 'P2'})
    return out
