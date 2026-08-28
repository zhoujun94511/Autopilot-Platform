"""Design chat services."""
from __future__ import annotations
import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import DesignChatMessageRow, DesignChatSessionRow, new_id
from autopilot_platform.platform.design.design_schemas import ChatMessageIn, ChatMessageOut
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}
from autopilot_platform.platform.services.design.chat.sessions import get_session, _utcnow
from autopilot_platform.platform.services.design.chat.prompts import _build_messages, _resolve_call_kwargs, _resolve_model_name
from autopilot_platform.platform.services.design.chat.errors import normalize_chat_error
from autopilot_platform.platform.services.design.chat.suggestions import simple_suggestions
from autopilot_platform.platform.services.shared.billing_scope import fill_scope as _fill_scope, project_org_id
from autopilot_platform.platform.ai import ai_usage

def _msg_out(row: DesignChatMessageRow) -> ChatMessageOut:
    return ChatMessageOut(id=row.id, session_id=row.session_id, role=row.role, content=row.content, tokens_used=int(row.tokens_used or 0), model_name=row.model_name or '', created_at=row.created_at)

def list_messages(db: Session, session_id: str) -> list[ChatMessageOut]:
    get_session(db, session_id)
    q = select(DesignChatMessageRow).where(DesignChatMessageRow.session_id == session_id.strip()).order_by(DesignChatMessageRow.created_at.asc())
    return [_msg_out(r) for r in db.scalars(q).all()]

def clear_session_messages(db: Session, session_id: str, auth: AuthContext) -> dict[str, Any]:
    _ = auth
    get_session(db, session_id)
    msgs = db.scalars(select(DesignChatMessageRow).where(DesignChatMessageRow.session_id == session_id.strip())).all()
    n = len(msgs)
    for m in msgs:
        db.delete(m)
    db.commit()
    return {'success': True, 'cleared_messages': n}

def _persist_turn(db: Session, session: DesignChatSessionRow, *, user_text: str, assistant_text: str, model_name: str='') -> tuple[ChatMessageOut, ChatMessageOut]:
    u = DesignChatMessageRow(id=new_id(), session_id=session.id, role='user', content=user_text)
    a = DesignChatMessageRow(id=new_id(), session_id=session.id, role='assistant', content=assistant_text, model_name=model_name or '')
    session.updated_at = _utcnow()
    if session.title in {'', '新对话'} and user_text.strip():
        session.title = user_text.strip()[:40]
    db.add(u)
    db.add(a)
    db.commit()
    db.refresh(u)
    db.refresh(a)
    return _msg_out(u), _msg_out(a)

def send_message(db: Session, body: ChatMessageIn, auth: AuthContext) -> dict[str, Any]:
    _ = auth
    session = get_session(db, body.session_id)
    text = (body.message or '').strip()
    if not text:
        raise ValueError('message 不能为空')
    billing_project_id, billing_org_id = _fill_scope(session.project_id or '', project_org_id(db, session.project_id or ''))
    scope_token = ai_usage.set_ai_billing_scope(project_id=billing_project_id, org_id=billing_org_id)
    try:
        want_knowledge = bool(body.use_knowledge) and bool(session.project_id)
        messages = _build_messages(db, session, text, use_knowledge=want_knowledge)
        from autopilot_platform.platform.ai import ai_client  # 延迟：HTTP LLM 客户端
        call_kwargs = _resolve_call_kwargs(body)
        model = _resolve_model_name(body)
        try:
            reply = ai_client.chat_completions(messages, **call_kwargs)
        except Exception as exc:
            err = normalize_chat_error(exc)
            raise RuntimeError(err['message']) from exc
        user_msg, asst_msg = _persist_turn(db, session, user_text=text, assistant_text=reply, model_name=model)
        suggestions = simple_suggestions(reply, user_message=text)
        return {'success': True, 'session_id': session.id, 'response': reply, 'user_message': user_msg, 'assistant_message': asst_msg, 'model_name': model, 'suggestions': suggestions}
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)
