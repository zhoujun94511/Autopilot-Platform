"""Design chat services."""
from __future__ import annotations
import json
import logging
from typing import Any, Iterator
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_schemas import ChatMessageIn
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}
from autopilot_platform.platform.services.design.chat.sessions import get_session
from autopilot_platform.platform.services.design.chat.prompts import _build_messages, _resolve_call_kwargs, _resolve_model_name
from autopilot_platform.platform.services.design.chat.messages import _persist_turn
from autopilot_platform.platform.services.design.chat.errors import normalize_chat_error
from autopilot_platform.platform.services.design.chat.suggestions import simple_suggestions
from autopilot_platform.platform.services.shared.billing_scope import scope_for_session_id as _scope_for_session_id
from autopilot_platform.platform.ai import ai_usage
from autopilot_platform.platform.ops.runtime_config import design_chunk_size, streaming_enabled

def iter_sse_chunks(db: Session, body: ChatMessageIn, auth: AuthContext) -> Iterator[str]:
    """SSE 流式对话（外层只负责计费作用域，避免流式绕过项目/组织日配额）。"""
    project_id, org_id = _scope_for_session_id(db, getattr(body, 'session_id', ''), auth)
    scope_token = ai_usage.set_ai_billing_scope(project_id=project_id, org_id=org_id)
    try:
        yield from _iter_sse_chunks_inner(db, body, auth)
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)

def _iter_sse_chunks_inner(db: Session, body: ChatMessageIn, auth: AuthContext) -> Iterator[str]:
    """优先上游 token 流；失败则降级为整段生成后再分块推送。

    AP_ENABLE_STREAMING=0 时跳过 token 流，直接缓冲推送。
    """
    _ = auth
    session = get_session(db, body.session_id)
    text = (body.message or '').strip()
    if not text:
        yield _sse({'type': 'error', **normalize_chat_error(ValueError('message 不能为空'))})
        return
    from autopilot_platform.platform.ai import ai_client  # 延迟：HTTP LLM 客户端
    model = _resolve_model_name(body)
    call_kwargs = _resolve_call_kwargs(body)
    try:
        messages = _build_messages(db, session, text, use_knowledge=bool(body.use_knowledge) and bool(session.project_id))
    except Exception as exc:
        yield _sse({'type': 'error', **normalize_chat_error(exc), 'content': normalize_chat_error(exc)['message']})
        return
    full = ''
    stream_mode = 'token'
    token_started = False
    buf_step = max(16, min(64, design_chunk_size() // 40 or 24))

    def _yield_buffered(reason: str) -> Iterator[str]:
        nonlocal full, stream_mode
        stream_mode = 'buffered'
        yield _sse({'type': 'start', 'session_id': session.id, 'model_name': model, 'stream_mode': 'buffered', 'content': reason})
        full = ai_client.chat_completions(messages, **call_kwargs)
        for i in range(0, len(full), buf_step):
            chunk = full[i:i + buf_step]
            yield _sse({'type': 'chunk', 'content': chunk, 'full_response': full[:i + len(chunk)], 'session_id': session.id, 'stream_mode': 'buffered'})
    if not streaming_enabled():
        try:
            yield from _yield_buffered('运维已关闭流式（AP_ENABLE_STREAMING=0），改用缓冲推送')
        except Exception as exc:
            err = normalize_chat_error(exc)
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
        if not full.strip():
            err = normalize_chat_error(ValueError('模型返回空内容'))
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
        _persist_turn(db, session, user_text=text, assistant_text=full, model_name=model)
        suggestions = simple_suggestions(full, user_message=text)
        yield _sse({'type': 'end', 'content': full, 'full_response': full, 'session_id': session.id, 'model_name': model, 'stream_mode': stream_mode, 'suggestions': suggestions})
        return
    try:
        stream_iter = ai_client.chat_completions_stream(messages, **call_kwargs)
        first = next(stream_iter)
        token_started = True
        yield _sse({'type': 'start', 'session_id': session.id, 'model_name': model, 'stream_mode': 'token'})

        def _emit_piece(delta: str) -> Iterator[str]:
            nonlocal full
            if not delta:
                return
            full += delta
            yield _sse({'type': 'chunk', 'content': delta, 'full_response': full, 'session_id': session.id, 'stream_mode': 'token'})
        yield from _emit_piece(first)
        for token in stream_iter:
            yield from _emit_piece(token)
    except StopIteration:
        log.warning('token stream empty, fallback to buffered')
        try:
            yield from _yield_buffered('上游流式返回空，已降级为整段生成后再分块推送')
        except Exception as exc:
            err = normalize_chat_error(exc)
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
    except Exception as stream_exc:
        if token_started:
            err = normalize_chat_error(stream_exc)
            yield _sse({'type': 'error', **err, 'content': f"流式中断: {err['message']}"})
            return
        log.warning('token stream unavailable, fallback to buffered: %s', stream_exc)
        try:
            yield from _yield_buffered('上游流式不可用，已降级为整段生成后再分块推送')
        except Exception as exc:
            err = normalize_chat_error(exc)
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
    if not full.strip():
        err = normalize_chat_error(ValueError('模型返回空内容'))
        yield _sse({'type': 'error', **err, 'content': err['message']})
        return
    _persist_turn(db, session, user_text=text, assistant_text=full, model_name=model)
    suggestions = simple_suggestions(full, user_message=text)
    yield _sse({'type': 'end', 'content': full, 'full_response': full, 'session_id': session.id, 'model_name': model, 'stream_mode': stream_mode, 'suggestions': suggestions})

def _sse(payload: dict[str, Any]) -> str:
    return f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
