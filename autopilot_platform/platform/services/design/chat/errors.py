"""Design chat services."""
from __future__ import annotations
import logging
from typing import Any
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}


def normalize_chat_error(exc: BaseException) -> dict[str, Any]:
    """结构化错误，便于前端展示与重试。"""
    msg = str(exc or '').strip() or '未知错误'
    low = msg.lower()
    if 'api key' in low or '未配置' in msg or 'not configured' in low:
        return {'code': 'missing_api_key', 'message': '未配置 AI API Key。请到「运维」配置中心填写密钥后重试。', 'retryable': False, 'detail': msg}
    if '401' in msg or 'unauthorized' in low or 'invalid api key' in low:
        return {'code': 'auth_failed', 'message': '上游鉴权失败，请检查 API Key 是否有效。', 'retryable': False, 'detail': msg}
    if '429' in msg or 'rate limit' in low or 'too many' in low:
        return {'code': 'rate_limited', 'message': '上游限流，请稍后重试。', 'retryable': True, 'detail': msg}
    if 'timeout' in low or 'timed out' in low:
        return {'code': 'timeout', 'message': '上游请求超时，可重试。', 'retryable': True, 'detail': msg}
    if any((x in low for x in ('connect', 'network', 'name or service', 'connection'))):
        return {'code': 'network_error', 'message': '无法连接上游服务，请检查网络或 Base URL 后重试。', 'retryable': True, 'detail': msg}
    if '5' == msg[:1] or 'server error' in low or '502' in msg or ('503' in msg):
        return {'code': 'upstream_error', 'message': '上游服务暂时不可用，可重试。', 'retryable': True, 'detail': msg}
    return {'code': 'chat_error', 'message': msg, 'retryable': True, 'detail': msg}
