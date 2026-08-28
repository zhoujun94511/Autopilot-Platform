"""需求结构化批量导入（CSV/JSON/MD/TXT），对齐知识导入体验。

TestPilot 主路径是「文档→LLM 分析」；本模块补齐可脚本化/可迁移的结构化导入，
并与文档分析共用切分规则。
"""
from __future__ import annotations
import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import RequirementRow, new_id
from autopilot_platform.platform.services.design.documents.text_extract import extract_text_from_bytes
from autopilot_platform.platform.services.design.requirements.crud import _actor, to_out
logger = logging.getLogger(__name__)
ALLOWED_REQ_IMPORT_EXT = {'.txt', '.md', '.csv', '.json', '.yaml', '.yml'}

def _norm_priority(raw: Any) -> str:
    key = str(raw or 'medium').strip().lower()
    mapping = {'p0': 'P0', 'critical': 'P0', 'high': 'P1', 'p1': 'P1', 'medium': 'P2', 'normal': 'P2', 'p2': 'P2', 'low': 'P3', 'p3': 'P3'}
    if key.upper() in {'P0', 'P1', 'P2', 'P3'}:
        return key.upper()
    return mapping.get(key, 'P2')

def _norm_type(raw: Any) -> str:
    s = str(raw or 'functional').strip().lower()
    allowed = {'functional', 'non-functional', 'non_functional', 'business', 'technical'}
    if s in allowed:
        return 'non-functional' if s == 'non_functional' else s
    return 'functional'

def _draft(*, title: str, content: str, req_key: str='', req_type: str='functional', priority: str='P2') -> dict[str, str]:
    return {'title': (title or '').strip()[:200] or '未命名需求', 'content': (content or '').strip(), 'req_key': (req_key or '').strip()[:64], 'req_type': _norm_type(req_type), 'priority': _norm_priority(priority)}

def _split_markdown(text: str, *, default_title: str) -> list[dict[str, str]]:
    lines = (text or '').splitlines()
    sections: list[tuple[str, list[str]]] = []
    cur_title = default_title
    cur_body: list[str] = []
    for line in lines:
        if line.startswith('# ') or line.startswith('## '):
            if cur_body and any((x.strip() for x in cur_body)):
                sections.append((cur_title, cur_body))
            cur_title = line.lstrip('#').strip() or default_title
            cur_body = []
        else:
            cur_body.append(line)
    if cur_body and any((x.strip() for x in cur_body)):
        sections.append((cur_title, cur_body))
    if not sections and (text or '').strip():
        chunks = [c.strip() for c in re.split('\\n{2,}', text) if c.strip()]
        out = []
        for i, chunk in enumerate(chunks, start=1):
            title = chunk.splitlines()[0][:120]
            out.append(_draft(title=title or f'{default_title}#{i}', content=chunk))
        return out
    return [_draft(title=t, content='\n'.join(b).strip()) for t, b in sections if '\n'.join(b).strip()]

def _parse_json(obj: Any, *, filename: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    def add_entry(item: Any, fallback: str) -> None:
        if isinstance(item, str) and item.strip():
            out.append(_draft(title=fallback, content=item))
            return
        if not isinstance(item, dict):
            return
        title = str(item.get('title') or item.get('name') or item.get('标题') or fallback).strip()
        content = item.get('content') or item.get('text') or item.get('body') or item.get('内容') or item.get('description')
        if content is None:
            content = json.dumps(item, ensure_ascii=False, indent=2)
        out.append(_draft(title=title, content=str(content), req_key=str(item.get('req_key') or item.get('req_id') or ''), req_type=str(item.get('req_type') or item.get('type') or 'functional'), priority=str(item.get('priority') or 'P2')))
    stem = Path(filename).stem or 'req'
    if isinstance(obj, list):
        for i, entry in enumerate(obj, start=1):
            add_entry(entry, f'{stem}#{i}')
        return out
    if isinstance(obj, dict):
        for key in ('requirements', 'items', 'data', 'entries'):
            if isinstance(obj.get(key), list):
                for i, entry in enumerate(obj[key], start=1):
                    add_entry(entry, f'{stem}#{i}')
                if out:
                    return out
        add_entry(obj, stem)
    return out

def _parse_csv(data: bytes, *, filename: str) -> list[dict[str, str]]:
    text = data.decode('utf-8-sig', errors='ignore')
    reader = csv.DictReader(io.StringIO(text))
    stem = Path(filename).stem or 'req'
    out: list[dict[str, str]] = []
    if reader.fieldnames:
        for i, row in enumerate(reader, start=1):
            if not row:
                continue
            title = ''
            content = ''
            req_key = ''
            req_type = 'functional'
            priority = 'P2'
            for k, v in row.items():
                lk = (k or '').strip().lower()
                val = str(v or '').strip()
                if lk in ('title', '标题', 'name', '名称'):
                    title = val
                elif lk in ('content', '内容', 'text', 'body', '描述', 'description'):
                    content = val
                elif lk in ('req_key', 'req_id', '编号', 'key'):
                    req_key = val
                elif lk in ('req_type', 'type', '类型'):
                    req_type = val or req_type
                elif lk in ('priority', '优先级'):
                    priority = val or priority
            if not title and (not content):
                vals = [str(v or '').strip() for v in row.values() if str(v or '').strip()]
                if len(vals) >= 2:
                    title, content = (vals[0], vals[1])
                elif len(vals) == 1:
                    title, content = (f'{stem}#{i}', vals[0])
            if content or title:
                out.append(_draft(title=title or f'{stem}#{i}', content=content or title, req_key=req_key, req_type=req_type, priority=priority))
        return out
    plain = csv.reader(io.StringIO(text))
    for i, row in enumerate(plain, start=1):
        if not row:
            continue
        if len(row) >= 2:
            out.append(_draft(title=row[0].strip() or f'{stem}#{i}', content=row[1].strip()))
        elif row[0].strip():
            out.append(_draft(title=f'{stem}#{i}', content=row[0].strip()))
    return out

def drafts_from_file(filename: str, data: bytes) -> list[dict[str, str]]:
    ext = Path(filename or '').suffix.lower()
    if ext not in ALLOWED_REQ_IMPORT_EXT:
        raise ValueError(f"不支持的文件类型: {ext or '(无扩展名)'}（结构化导入请用 csv/json/md/txt）")
    if not data:
        raise ValueError('空文件')
    stem = Path(filename).stem or 'req'
    if ext == '.json':
        try:
            obj = json.loads(data.decode('utf-8-sig', errors='ignore'))
        except json.JSONDecodeError as exc:
            raise ValueError(f'JSON 无法解析: {exc}') from exc
        return [d for d in _parse_json(obj, filename=filename) if d.get('content')]
    if ext in {'.yaml', '.yml'}:
        try:
            import yaml
            obj = yaml.safe_load(data.decode('utf-8-sig', errors='ignore'))
        except Exception as exc:
            raise ValueError(f'YAML 无法解析: {exc}') from exc
        return [d for d in _parse_json(obj, filename=filename) if d.get('content')]
    if ext == '.csv':
        return [d for d in _parse_csv(data, filename=filename) if d.get('content')]
    text = extract_text_from_bytes(filename, data)
    if not (text or '').strip():
        raise ValueError('未能抽取到文本内容')
    return [d for d in _split_markdown(text, default_title=stem) if d.get('content')]

def import_requirement_files(db: Session, *, project_id: str, files: list[tuple[str, bytes]], auth: AuthContext) -> dict[str, Any]:
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    if not files:
        raise ValueError('请至少选择一个文件')
    actor = _actor(auth)
    results: list[dict[str, Any]] = []
    created_rows: list[RequirementRow] = []
    for filename, raw in files:
        name = Path(filename or 'upload.bin').name
        try:
            drafts = drafts_from_file(name, raw)
            if not drafts:
                raise ValueError('未解析出有效需求')
            n = 0
            for i, d in enumerate(drafts, start=1):
                row = RequirementRow(id=new_id(), project_id=pid, req_key=(d.get('req_key') or f'REQ-{new_id()[:8]}-{i:02d}').strip(), title=d['title'], content=d['content'][:20000], req_type=d.get('req_type') or 'functional', priority=d.get('priority') or 'P2', source_document_id=None, source_excerpt=d['content'][:500], created_by=actor)
                db.add(row)
                created_rows.append(row)
                n += 1
            results.append({'filename': name, 'success': True, 'status_code': 200, 'created_count': n, 'message': f'导入 {n} 条需求'})
        except Exception as exc:
            logger.info('requirement import failed for %s: %s', name, exc)
            results.append({'filename': name, 'success': False, 'status_code': 400, 'created_count': 0, 'message': str(exc), 'error': str(exc)})
    if created_rows:
        db.commit()
        for row in created_rows:
            db.refresh(row)
    success_count = sum((1 for r in results if r.get('success')))
    failed_count = len(results) - success_count
    item_count = sum((int(r.get('created_count') or 0) for r in results))
    return {'success': failed_count == 0 and success_count > 0, 'summary': {'total': len(results), 'success_count': success_count, 'failed_count': failed_count, 'item_count': item_count}, 'results': results, 'items': [to_out(r) for r in created_rows], 'message': f'成功 {success_count}/{len(results)} 个文件，共 {item_count} 条需求'}
