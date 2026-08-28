"""Design chat services."""
from __future__ import annotations
from autopilot_platform.platform.services.shared.actors import actor as _actor
import logging
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import DesignChatMessageRow, DesignChatSessionRow, new_id
from autopilot_platform.platform.design.design_schemas import ChatSessionCreate, ChatSessionOut, ChatSessionUpdate
from autopilot_platform.platform.core.models import db_get
from autopilot_platform.platform.services.shared.pagination import paginate
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _session_out(row: DesignChatSessionRow, *, message_count: int=0, preview: str='') -> ChatSessionOut:
    return ChatSessionOut(id=row.id, project_id=row.project_id, title=row.title, created_by=row.created_by, created_at=row.created_at, updated_at=row.updated_at, message_count=int(message_count or 0), preview=(preview or '')[:120])

def create_session(db: Session, body: ChatSessionCreate, auth: AuthContext) -> ChatSessionOut:
    title = (body.title or '').strip() or '新对话'
    row = DesignChatSessionRow(id=new_id(), project_id=(body.project_id or '').strip(), title=title[:256], created_by=_actor(auth))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _session_out(row)

def list_sessions(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, created_by: str | None=None, page: int=1, page_size: int=50) -> tuple[list[ChatSessionOut], int]:
    q = select(DesignChatSessionRow).order_by(DesignChatSessionRow.updated_at.desc())
    if project_ids is not None:
        if not project_ids:
            return [], 0
        q = q.where(DesignChatSessionRow.project_id.in_(project_ids + ['']))
    elif project_id:
        q = q.where(DesignChatSessionRow.project_id == project_id.strip())
    if created_by:
        q = q.where(DesignChatSessionRow.created_by == created_by)
    size = max(1, min(200, int(page_size or 50)))
    pg = max(1, int(page or 1))
    rows, total = paginate(db, q, page=pg, page_size=size)
    if not rows:
        return [], total
    ids = [r.id for r in rows]
    count_rows = db.execute(select(DesignChatMessageRow.session_id, func.count()).where(DesignChatMessageRow.session_id.in_(ids)).group_by(DesignChatMessageRow.session_id)).all()
    counts = {sid: int(n) for sid, n in count_rows}
    previews: dict[str, str] = {}
    for sid in ids:
        last = db.scalars(select(DesignChatMessageRow).where(DesignChatMessageRow.session_id == sid, DesignChatMessageRow.role.in_(('user', 'assistant'))).order_by(DesignChatMessageRow.created_at.desc()).limit(1)).first()
        if last and str(last.content or '').strip():
            text = str(last.content or '').strip().replace('\n', ' ')
            previews[sid] = text[:100] + ('…' if len(text) > 100 else '')
    return [_session_out(r, message_count=counts.get(r.id, 0), preview=previews.get(r.id, '')) for r in rows], total

def get_session(db: Session, session_id: str) -> DesignChatSessionRow:
    row = db_get(db, DesignChatSessionRow, (session_id or '').strip())
    if row is None:
        raise LookupError('会话不存在')
    return row

def assert_session_owner(row: DesignChatSessionRow, auth: AuthContext) -> None:
    """会话按 created_by 隔离：同项目他人不得凭 session_id 读写。"""
    owner = (row.created_by or '').strip()
    if not owner:
        return
    actors = {(auth.username or '').strip(), (auth.user_id or '').strip()} - {''}
    if owner not in actors:
        raise PermissionError('无权访问他人会话')

def load_session_for_user(db: Session, session_id: str, auth: AuthContext) -> DesignChatSessionRow:
    row = get_session(db, session_id)
    assert_session_owner(row, auth)
    return row

def rename_session(db: Session, session_id: str, body: ChatSessionUpdate, auth: AuthContext) -> ChatSessionOut:
    _ = auth
    row = get_session(db, session_id)
    title = (body.title or '').strip()
    if not title:
        raise ValueError('标题不能为空')
    row.title = title[:256]
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    count = int(db.scalar(select(func.count()).where(DesignChatMessageRow.session_id == row.id)) or 0)
    last = db.scalars(select(DesignChatMessageRow).where(DesignChatMessageRow.session_id == row.id, DesignChatMessageRow.role.in_(('user', 'assistant'))).order_by(DesignChatMessageRow.created_at.desc()).limit(1)).first()
    preview = ''
    if last and str(last.content or '').strip():
        text = str(last.content or '').strip().replace('\n', ' ')
        preview = text[:100] + ('…' if len(text) > 100 else '')
    return _session_out(row, message_count=count, preview=preview)

def delete_session(db: Session, session_id: str, auth: AuthContext) -> None:
    _ = auth
    row = get_session(db, session_id)
    msgs = db.scalars(select(DesignChatMessageRow).where(DesignChatMessageRow.session_id == row.id)).all()
    for m in msgs:
        db.delete(m)
    db.delete(row)
    db.commit()
