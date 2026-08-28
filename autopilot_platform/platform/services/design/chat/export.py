"""Design chat services."""
from __future__ import annotations
import csv
import io
import json
import logging
from typing import Any
from sqlalchemy.orm import Session
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}
from autopilot_platform.platform.services.design.chat.sessions import get_session, _session_out, _utcnow
from autopilot_platform.platform.services.design.chat.messages import list_messages

def export_session_json(db: Session, session_id: str) -> dict[str, Any]:
    session = get_session(db, session_id)
    msgs = list_messages(db, session_id)
    return {'session': _session_out(session).model_dump(mode='json'), 'messages': [m.model_dump(mode='json') for m in msgs], 'exported_at': _utcnow().isoformat()}

def export_session(db: Session, session_id: str, fmt: str='json') -> tuple[bytes, str, str]:
    """返回 (content_bytes, media_type, filename)。"""
    session = get_session(db, session_id)
    msgs = [m for m in list_messages(db, session_id) if m.role in {'user', 'assistant'}]
    fmt_l = (fmt or 'json').strip().lower()
    stamp = session_id[:8]
    if fmt_l == 'json':
        data = export_session_json(db, session_id)
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        return raw, 'application/json', f'chat_{stamp}.json'
    if fmt_l == 'txt':
        lines = [f"聊天记录导出 - {_utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", f'会话: {session.title}', f'会话ID: {session_id}', f'消息数量: {len(msgs)}', '=' * 50, '']
        for msg in msgs:
            role_name = '用户' if msg.role == 'user' else '助手'
            ts = msg.created_at.strftime('%Y-%m-%d %H:%M:%S') if msg.created_at else ''
            lines.extend([f'[{ts}] {role_name}:', msg.content, ''])
        raw = '\n'.join(lines).encode('utf-8')
        return raw, 'text/plain; charset=utf-8', f'chat_{stamp}.txt'
    if fmt_l == 'csv':
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=['role', 'content', 'model_name', 'created_at'])
        writer.writeheader()
        for msg in msgs:
            writer.writerow({'role': msg.role, 'content': msg.content, 'model_name': msg.model_name or '', 'created_at': msg.created_at.isoformat() if msg.created_at else ''})
        raw = ('\ufeff' + buf.getvalue()).encode('utf-8')
        return raw, 'text/csv; charset=utf-8', f'chat_{stamp}.csv'
    if fmt_l in {'xlsx', 'excel'}:
        from openpyxl import Workbook  # 延迟：可选 extra
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = 'chat'
        ws.append(['role', 'content', 'model_name', 'created_at'])
        for msg in msgs:
            ws.append([msg.role, msg.content, msg.model_name or '', msg.created_at.isoformat() if msg.created_at else ''])
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', f'chat_{stamp}.xlsx'
    raise ValueError(f'不支持的导出格式: {fmt}')
