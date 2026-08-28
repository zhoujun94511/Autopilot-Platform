"""Design chat services."""
from __future__ import annotations
import logging
from typing import Any, Iterator
from autopilot_platform.platform.auth import AuthContext
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}
from autopilot_platform.platform.services.design.chat.prompts import _build_system_prompt, _resolve_call_kwargs, _resolve_model_name
from autopilot_platform.platform.services.design.chat.errors import normalize_chat_error
from autopilot_platform.platform.services.design.chat.suggestions import simple_suggestions
from autopilot_platform.platform.services.design.chat.streaming import _sse
from autopilot_platform.platform.services.shared.billing_scope import fill_scope as _fill_scope
from autopilot_platform.platform.ai import ai_usage
from autopilot_platform.platform.ops.runtime_config import design_chunk_size, streaming_enabled
from autopilot_platform.platform.design.design_schemas import EphemeralChatIn

def _normalize_client_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role') or '').strip().lower()
        content = str(item.get('content') or '').strip()
        if role not in {'user', 'assistant'} or not content:
            continue
        out.append({'role': role, 'content': content[:12000]})
    return out[-20:]

def _build_ephemeral_messages(user_text: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{'role': 'system', 'content': _build_system_prompt(user_text, general=True)}]
    msgs.extend(_normalize_client_history(history))
    msgs.append({'role': 'user', 'content': user_text})
    return msgs

def ephemeral_send(body: Any, auth: AuthContext) -> dict[str, Any]:
    """无项目测试闲聊：不写 DesignChat* 表、不注入知识库（用量入合成计费桶）。"""
    from autopilot_platform.platform.ai import ai_client  # 延迟：HTTP LLM 客户端
    if not isinstance(body, EphemeralChatIn):
        body = EphemeralChatIn.model_validate(body)
    text = (body.message or '').strip()
    if not text:
        raise ValueError('message 不能为空')
    messages = _build_ephemeral_messages(text, body.history)
    call_kwargs = _resolve_call_kwargs(body)
    model = _resolve_model_name(body)
    project_id, org_id = _fill_scope('', getattr(auth, 'org_id', '') or '')
    scope_token = ai_usage.set_ai_billing_scope(project_id=project_id, org_id=org_id)
    try:
        reply = ai_client.chat_completions(messages, **call_kwargs)
    except Exception as exc:
        err = normalize_chat_error(exc)
        raise RuntimeError(err['message']) from exc
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)
    return {'success': True, 'ephemeral': True, 'response': reply, 'model_name': model, 'suggestions': simple_suggestions(reply, user_message=text)}

def iter_ephemeral_sse(body: Any, auth: AuthContext) -> Iterator[str]:
    """无项目闲聊 SSE（外层只负责计费作用域）。"""
    project_id, org_id = _fill_scope('', getattr(auth, 'org_id', '') or '')
    scope_token = ai_usage.set_ai_billing_scope(project_id=project_id, org_id=org_id)
    try:
        yield from _iter_ephemeral_sse_inner(body, auth)
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)

def _iter_ephemeral_sse_inner(body: Any, auth: AuthContext) -> Iterator[str]:
    """无项目闲聊 SSE：不落库。"""
    _ = auth
    from autopilot_platform.platform.ai import ai_client  # 延迟：HTTP LLM 客户端
    if not isinstance(body, EphemeralChatIn):
        body = EphemeralChatIn.model_validate(body)
    text = (body.message or '').strip()
    if not text:
        yield _sse({'type': 'error', **normalize_chat_error(ValueError('message 不能为空'))})
        return
    model = _resolve_model_name(body)
    call_kwargs = _resolve_call_kwargs(body)
    try:
        messages = _build_ephemeral_messages(text, body.history)
    except Exception as exc:
        err = normalize_chat_error(exc)
        yield _sse({'type': 'error', **err, 'content': err['message']})
        return
    full = ''
    buf_step = max(16, min(64, design_chunk_size() // 40 or 24))

    def _yield_buffered(reason: str) -> Iterator[str]:
        nonlocal full
        yield _sse({'type': 'start', 'ephemeral': True, 'model_name': model, 'stream_mode': 'buffered', 'content': reason})
        full = ai_client.chat_completions(messages, **call_kwargs)
        for i in range(0, len(full), buf_step):
            chunk = full[i:i + buf_step]
            yield _sse({'type': 'chunk', 'content': chunk, 'full_response': full[:i + len(chunk)], 'ephemeral': True, 'stream_mode': 'buffered'})
    if not streaming_enabled():
        try:
            yield from _yield_buffered('运维已关闭流式，改用缓冲推送')
        except Exception as exc:
            err = normalize_chat_error(exc)
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
        suggestions = simple_suggestions(full, user_message=text)
        yield _sse({'type': 'end', 'content': full, 'full_response': full, 'ephemeral': True, 'model_name': model, 'stream_mode': 'buffered', 'suggestions': suggestions})
        return
    try:
        stream_iter = ai_client.chat_completions_stream(messages, **call_kwargs)
        first = next(stream_iter)
        yield _sse({'type': 'start', 'ephemeral': True, 'model_name': model, 'stream_mode': 'token'})
        full = first
        yield _sse({'type': 'chunk', 'content': first, 'full_response': full, 'ephemeral': True, 'stream_mode': 'token'})
        for token in stream_iter:
            if not token:
                continue
            full += token
            yield _sse({'type': 'chunk', 'content': token, 'full_response': full, 'ephemeral': True, 'stream_mode': 'token'})
    except Exception as stream_exc:
        log.warning('ephemeral token stream fallback: %s', stream_exc)
        try:
            yield from _yield_buffered('上游流式不可用，已降级缓冲推送')
        except Exception as exc:
            err = normalize_chat_error(exc)
            yield _sse({'type': 'error', **err, 'content': err['message']})
            return
    if not full.strip():
        err = normalize_chat_error(ValueError('模型返回空内容'))
        yield _sse({'type': 'error', **err, 'content': err['message']})
        return
    suggestions = simple_suggestions(full, user_message=text)
    yield _sse({'type': 'end', 'content': full, 'full_response': full, 'ephemeral': True, 'model_name': model, 'suggestions': suggestions})
