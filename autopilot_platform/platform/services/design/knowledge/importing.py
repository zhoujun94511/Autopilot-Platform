"""知识条目批量导入：借鉴 TestPilot 多文件上传，落为平台 KnowledgeItem 行。"""
from __future__ import annotations
import csv
import io
import json
import logging
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import KnowledgeItemRow, new_id
from autopilot_platform.platform.services.design.documents.text_extract import extract_text_from_bytes
from autopilot_platform.platform.services.design.knowledge.crud import _actor, _to_out, _touch_index
logger = logging.getLogger(__name__)
ALLOWED_IMPORT_EXT = {'.txt', '.md', '.csv', '.json', '.docx', '.pdf', '.yaml', '.yml'}

def _stem_title(filename: str) -> str:
    name = Path(filename or 'import').name
    return Path(name).stem.strip() or 'imported'

def _draft(*, title: str, content: str, category: str, source: str) -> dict[str, str]:
    return {'title': (title or '').strip()[:200] or '未命名', 'content': (content or '').strip(), 'category': (category or 'other').strip() or 'other', 'source': (source or '').strip()[:300]}

def _split_markdown_sections(text: str, *, default_title: str) -> list[dict[str, str]]:
    """按一级/二级标题切分；无标题则整篇一条。"""
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
        return [{'title': default_title, 'content': text.strip()}]
    return [{'title': t, 'content': '\n'.join(b).strip()} for t, b in sections if '\n'.join(b).strip()]

def _parse_json_payload(obj: Any, *, filename: str, category: str) -> list[dict[str, str]]:
    source = f'import:{Path(filename).name}'
    out: list[dict[str, str]] = []

    def from_entry(item: Any, fallback_title: str) -> None:
        if isinstance(item, str) and item.strip():
            out.append(_draft(title=fallback_title, content=item, category=category, source=source))
            return
        if not isinstance(item, dict):
            return
        title = str(item.get('title') or item.get('name') or item.get('标题') or fallback_title).strip()
        content = item.get('content') or item.get('text') or item.get('body') or item.get('内容')
        if content is None and item.get('description') is not None:
            content = item.get('description')
        if content is None:
            content = json.dumps(item, ensure_ascii=False, indent=2)
        cat = str(item.get('category') or category).strip() or category
        out.append(_draft(title=title, content=str(content), category=cat, source=source))
    if isinstance(obj, list):
        for i, entry in enumerate(obj, start=1):
            from_entry(entry, f'{_stem_title(filename)}#{i}')
        return out
    if isinstance(obj, dict):
        for key in ('items', 'knowledge', 'entries', 'data'):
            if isinstance(obj.get(key), list):
                for i, entry in enumerate(obj[key], start=1):
                    from_entry(entry, f'{_stem_title(filename)}#{i}')
                if out:
                    return out
        for key, val in obj.items():
            if key in ('metadata', 'version'):
                continue
            if not isinstance(val, dict):
                continue
            if 'items' not in val and 'category' not in val:
                continue
            sec_label = str(val.get('category') or key)
            section_items = val.get('items')
            if isinstance(section_items, list):
                for i, entry in enumerate(section_items, start=1):
                    if isinstance(entry, dict):
                        name = str(entry.get('name') or entry.get('title') or f'{sec_label}#{i}')
                        aliases = entry.get('aliases')
                        extra = ''
                        if isinstance(aliases, list) and aliases:
                            extra = '别名: ' + '、'.join((str(a) for a in aliases))
                        risk = entry.get('risk')
                        bits = [extra] if extra else []
                        if risk:
                            bits.append(f'风险: {risk}')
                        body = '\n'.join(bits) if bits else json.dumps(entry, ensure_ascii=False, indent=2)
                        out.append(_draft(title=f'{sec_label} · {name}', content=body, category=category, source=source))
                    else:
                        from_entry(entry, f'{sec_label}#{i}')
            elif isinstance(section_items, dict):
                for name, detail in section_items.items():
                    if isinstance(detail, str):
                        body = detail
                    elif isinstance(detail, dict):
                        parts: list[str] = []
                        for field in ('examples', 'subtypes', 'risk', 'description'):
                            if field in detail:
                                parts.append(f'{field}: {json.dumps(detail[field], ensure_ascii=False)}')
                        body = '\n'.join(parts) if parts else json.dumps(detail, ensure_ascii=False, indent=2)
                    else:
                        body = json.dumps(detail, ensure_ascii=False, indent=2)
                    out.append(_draft(title=f'{sec_label} · {name}', content=str(body), category=category, source=source))
        if out:
            return out
        from_entry(obj, _stem_title(filename))
        return out
    return out

def _parse_csv(data: bytes, *, filename: str, category: str) -> list[dict[str, str]]:
    text = data.decode('utf-8-sig', errors='ignore')
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [(f or '').strip().lower() for f in reader.fieldnames or []]
    source = f'import:{Path(filename).name}'
    out: list[dict[str, str]] = []
    if fieldnames and reader.fieldnames:
        title_keys = ('title', '标题', 'name', '名称')
        content_keys = ('content', '内容', 'text', 'body', '描述', 'description')
        cat_keys = ('category', '分类')
        for i, row in enumerate(reader, start=1):
            if not row:
                continue
            title = ''
            content = ''
            cat = category
            for k, v in row.items():
                lk = (k or '').strip().lower()
                if lk in title_keys or (k or '').strip() in title_keys:
                    title = str(v or '').strip()
                elif lk in content_keys or (k or '').strip() in content_keys:
                    content = str(v or '').strip()
                elif lk in cat_keys or (k or '').strip() in cat_keys:
                    if str(v or '').strip():
                        cat = str(v).strip()
            if not title and (not content):
                vals = [str(v or '').strip() for v in row.values()]
                vals = [v for v in vals if v]
                if len(vals) >= 2:
                    title, content = (vals[0], vals[1])
                elif len(vals) == 1:
                    title, content = (f'{_stem_title(filename)}#{i}', vals[0])
            if content or title:
                out.append(_draft(title=title or f'{_stem_title(filename)}#{i}', content=content or title, category=cat, source=source))
        return out
    plain = csv.reader(io.StringIO(text))
    for i, row in enumerate(plain, start=1):
        if not row:
            continue
        if len(row) >= 2:
            out.append(_draft(title=row[0].strip() or f'{_stem_title(filename)}#{i}', content=row[1].strip(), category=category, source=source))
        elif row[0].strip():
            out.append(_draft(title=f'{_stem_title(filename)}#{i}', content=row[0].strip(), category=category, source=source))
    return out

def drafts_from_file(filename: str, data: bytes, *, category: str='other') -> list[dict[str, str]]:
    """单文件 → 多条草稿（title/content/category/source）。"""
    ext = Path(filename or '').suffix.lower()
    if ext not in ALLOWED_IMPORT_EXT:
        raise ValueError(f"不支持的文件类型: {ext or '(无扩展名)'}")
    if not data:
        raise ValueError('空文件')
    source = f'import:{Path(filename).name}'
    default_title = _stem_title(filename)
    if ext == '.json':
        try:
            obj = json.loads(data.decode('utf-8-sig', errors='ignore'))
        except json.JSONDecodeError as exc:
            raise ValueError(f'JSON 无法解析: {exc}') from exc
        drafts = _parse_json_payload(obj, filename=filename, category=category)
        return [d for d in drafts if d.get('content')]
    if ext == '.csv':
        return [d for d in _parse_csv(data, filename=filename, category=category) if d.get('content')]
    if ext in {'.yaml', '.yml'}:
        try:
            import yaml
            obj = yaml.safe_load(data.decode('utf-8-sig', errors='ignore'))
        except Exception as exc:
            raise ValueError(f'YAML 无法解析: {exc}') from exc
        drafts = _parse_json_payload(obj, filename=filename, category=category)
        return [d for d in drafts if d.get('content')]
    text = extract_text_from_bytes(filename, data)
    if not (text or '').strip():
        raise ValueError('未能抽取到文本内容')
    if ext == '.md':
        parts = _split_markdown_sections(text, default_title=default_title)
        return [_draft(title=p['title'], content=p['content'], category=category, source=source) for p in parts if p.get('content')]
    return [_draft(title=default_title, content=text, category=category, source=source)]

def import_knowledge_files(db: Session, *, project_id: str, files: list[tuple[str, bytes]], auth: AuthContext, category: str='other', confirmed: bool=True, description: str='') -> dict[str, Any]:
    """批量导入多个文件；返回 summary + results（对齐 TestPilot upload 摘要形态）。"""
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    if not files:
        raise ValueError('请至少选择一个文件')
    cat = (category or 'other').strip() or 'other'
    actor = _actor(auth)
    desc = (description or '').strip()
    results: list[dict[str, Any]] = []
    created_rows: list[KnowledgeItemRow] = []
    for filename, raw in files:
        name = Path(filename or 'upload.bin').name
        try:
            drafts = drafts_from_file(name, raw, category=cat)
            if not drafts:
                raise ValueError('未解析出有效条目')
            file_created = 0
            for d in drafts:
                content = d['content']
                if desc and (not content.startswith(desc)):
                    pass
                row = KnowledgeItemRow(id=new_id(), project_id=pid, title=d['title'], content=content, category=d.get('category') or cat, source=d.get('source') or f'import:{name}', confirmed=bool(confirmed), created_by=actor)
                db.add(row)
                created_rows.append(row)
                file_created += 1
            results.append({'filename': name, 'success': True, 'status_code': 200, 'created_count': file_created, 'message': f'导入 {file_created} 条'})
        except Exception as exc:
            logger.info('knowledge import failed for %s: %s', name, exc)
            results.append({'filename': name, 'success': False, 'status_code': 400, 'created_count': 0, 'message': str(exc), 'error': str(exc)})
    if created_rows:
        db.commit()
        for row in created_rows:
            db.refresh(row)
        _touch_index(pid)
    success_count = sum((1 for r in results if r.get('success')))
    failed_count = len(results) - success_count
    item_count = sum((int(r.get('created_count') or 0) for r in results))
    items_out = [_to_out(r) for r in created_rows]
    return {'success': failed_count == 0 and success_count > 0, 'summary': {'total': len(results), 'success_count': success_count, 'failed_count': failed_count, 'item_count': item_count}, 'results': results, 'items': items_out, 'message': f'成功 {success_count}/{len(results)} 个文件，共 {item_count} 条知识'}
