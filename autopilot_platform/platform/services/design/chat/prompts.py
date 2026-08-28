"""Design chat services."""
from __future__ import annotations
import logging
import re
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_models import DesignChatSessionRow
from autopilot_platform.platform.design.design_schemas import ChatMessageOut
from autopilot_platform.platform.services.shared.errors import BEST_EFFORT_ERRS as _BEST_EFFORT_ERRS
from autopilot_platform.platform.ai import ai_config
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}

def _available_models_by_provider() -> dict[str, list[str]]:
    """与 ai_config.AI_PROVIDERS 对齐的推荐模型目录。"""
    return {p['id']: list(p.get('models') or []) for p in ai_config.list_ai_providers()}

def _infer_language_instruction(text: str) -> str:
    content = (text or '').strip()
    if not content:
        return '默认使用中文输出。'
    sanitized = re.sub('```[\\s\\S]*?```', ' ', content)
    sanitized = re.sub('`[^`]*`', ' ', sanitized)
    sanitized = re.sub('https?://\\S+', ' ', sanitized)
    non_code_lines: list[str] = []
    for line in sanitized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        symbol_count = len(re.findall('[{}();=<>\\[\\]#:_/\\\\]', stripped))
        zh_in_line = len(re.findall('[\\u4e00-\\u9fff]', stripped))
        if symbol_count >= 2 and zh_in_line == 0:
            continue
        non_code_lines.append(stripped)
    sample = ' '.join(non_code_lines) if non_code_lines else sanitized
    zh_count = len(re.findall('[\\u4e00-\\u9fff]', sample))
    en_count = len(re.findall('[A-Za-z]', sample))
    if zh_count > en_count:
        return '请使用简体中文回答；除专有名词、代码、接口名外，不要夹杂英文句子。'
    if en_count > zh_count:
        return 'Please answer in English; avoid mixing Chinese sentences except for fixed proper nouns.'
    return '请跟随用户输入的主体语言作答，避免中英混杂。'

def _build_system_prompt(user_text: str, *, knowledge_ctx: str='', general: bool=False) -> str:
    language_instruction = _infer_language_instruction(user_text)
    if general:
        prompt = f'你是 Autopilot 测试小助手（专业的软件测试助手）。\n\n身份：专业的测试助手\n职责：帮助用户分析需求、设计测试用例、评审要点、测试策略，以及解答测试/自动化相关问题\n\n重要规则：\n1. 在任何情况下，你都必须以「测试小助手」身份回答；不要自称「通用助手」或写作助手\n2. 不要介绍自己是某个 AI 模型（如 GPT、Gemini、DeepSeek、Qwen 等）\n3. 当前为「无项目闲聊」：没有绑定项目，也不使用设计域知识库；可围绕测试话题自由讨论\n4. 优先给出与软件测试、质量保障、用例设计、自动化相关的专业建议；若用户偏离测试话题，可简短回应并引导回测试场景\n5. 输出语言必须遵循：{language_instruction}\n\n请严格遵守以上规则。'
        return prompt
    prompt = f'你是 Autopilot 测试设计助手（专业的软件测试助手）。你的身份和职责如下：\n\n身份：专业的测试设计助手\n职责：帮助用户分析需求、设计测试用例、评审要点与测试策略\n\n重要规则：\n1. 在任何情况下，你都必须以「专业的测试助手」身份回答\n2. 不要介绍自己是某个 AI 模型（如 GPT、Gemini、DeepSeek、Qwen 等）\n3. 始终专注于软件测试与测试设计相关话题\n4. 提供准确、专业、可执行的建议\n5. 输出语言必须遵循：{language_instruction}\n\n请严格遵守以上规则。'
    if knowledge_ctx.strip():
        prompt += f'\n\n参考知识库：\n{knowledge_ctx.strip()[:4000]}'
    return prompt

def _pair_history(history: list[ChatMessageOut], *, current_user: str) -> list[dict[str, str]]:
    """去重 + user/assistant 成对过滤（对齐 TP）。"""
    filtered: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    last_role: str | None = None
    source = (current_user or '').strip()
    for m in history[-20:]:
        role = (m.role or '').lower()
        content = (m.content or '').strip()
        if role == 'system' or not content:
            continue
        if role == 'user' and content == source:
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        if last_role is not None:
            if last_role == 'user' and role != 'assistant':
                continue
            if last_role == 'assistant' and role != 'user':
                continue
        filtered.append({'role': role, 'content': content})
        last_role = role
    return filtered

def _build_messages(db: Session, session: DesignChatSessionRow, user_text: str, *, use_knowledge: bool) -> list[dict[str, str]]:
    # 延迟：messages 顶栏已 import prompts，顶栏互引会成环
    from autopilot_platform.platform.services.design.chat.messages import list_messages
    history = list_messages(db, session.id)
    knowledge_ctx = ''
    if use_knowledge and session.project_id:
        try:
            # 延迟：RAG 为可选 extra，检索失败不阻断对话
            from autopilot_platform.platform.rag.service import retrieve_for_generation
            rag = retrieve_for_generation(db, project_id=session.project_id, query=user_text, confirmed_only=False)
            knowledge_ctx = (rag.get('context_text') or '').strip()
        except _BEST_EFFORT_ERRS as exc:
            log.info('chat knowledge retrieve skipped: %s', exc)
    out: list[dict[str, str]] = [{'role': 'system', 'content': _build_system_prompt(user_text, knowledge_ctx=knowledge_ctx, general=not bool(session.project_id))}]
    out.extend(_pair_history(history, current_user=user_text))
    out.append({'role': 'user', 'content': user_text})
    return out

def _resolve_call_kwargs(body: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if body.model and str(body.model).strip():
        kwargs['model'] = str(body.model).strip()
    if body.temperature is not None:
        kwargs['temperature'] = float(body.temperature)
    if body.max_tokens is not None:
        kwargs['max_tokens'] = int(body.max_tokens)
    return kwargs

def _resolve_model_name(body: Any) -> str:
    if body.model and str(body.model).strip():
        return str(body.model).strip()
    return ai_config.ai_model()

def chat_options() -> dict[str, Any]:
    """只读对话选项：复用 ai_config / runtime_config，不另存密钥。"""
    provider = ai_config.ai_provider()
    current_model = ai_config.ai_model()
    models = list(_available_models_by_provider().get(provider, []))
    if current_model and current_model not in models:
        models = [current_model, *models]
    return {'provider': provider, 'default_model': current_model, 'available_models': models, 'default_temperature': ai_config.ai_temperature(), 'default_max_tokens': ai_config.ai_max_tokens(), 'key_configured': ai_config.ai_enabled(), 'base_url': ai_config.ai_base_url(), 'templates': [{'id': k, 'name': v['name'], 'content': v['content']} for k, v in _CHAT_TEMPLATES.items()]}

def chat_templates() -> dict[str, Any]:
    return {'success': True, 'templates': {k: {'name': v['name'], 'content': v['content']} for k, v in _CHAT_TEMPLATES.items()}}
