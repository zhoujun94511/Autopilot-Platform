"""Design chat services."""
from __future__ import annotations
import logging
log = logging.getLogger('autopilot_platform.platform.design_chat')
EPHEMERAL_PROJECT_BUCKET = '__ephemeral__'
PLATFORM_ORG_BUCKET = '__platform__'
_CHAT_TEMPLATES: dict[str, dict[str, str]] = {'test_strategy': {'name': '测试策略咨询', 'content': '我需要制定一个测试策略，项目类型是[请描述项目类型]，主要功能包括[请列出主要功能]，请帮我分析应该采用什么测试策略？'}, 'case_review': {'name': '用例评审建议', 'content': '我有一些测试用例需要评审，用例内容如下：\n[请粘贴测试用例]\n\n请帮我分析这些用例是否完整，有什么改进建议？'}, 'bug_analysis': {'name': '缺陷分析指导', 'content': '我遇到了一个缺陷，现象是[请描述缺陷现象]，出现的步骤是[请描述重现步骤]，请帮我分析可能的原因和解决方案。'}, 'automation_advice': {'name': '自动化建议', 'content': '我想对[请描述功能模块]进行自动化测试，目前的技术栈是[请描述技术栈]，请推荐合适的自动化测试方案。'}, 'performance_test': {'name': '性能测试指导', 'content': '我需要对[请描述系统]进行性能测试，预期的用户并发量是[请填写数字]，请帮我制定性能测试方案。'}}


def simple_suggestions(ai_response: str, *, user_message: str='') -> list[str]:
    """基于回复关键词的快捷追问（对齐 TestPilot 快速回复风格：短、可点、可续聊）。"""
    text = f'{user_message}\n{ai_response}'.lower()
    suggestions: list[str] = []
    if any((k in text for k in ('用例', '测试场景', 'case', 'test case'))):
        suggestions.extend(['帮我补充边界用例', '按优先级给这些用例排序', '标出可自动化的步骤'])
    if any((k in text for k in ('缺陷', 'bug', '故障', '错误', 'error'))):
        suggestions.extend(['列出可能根因', '给出复现清单', '建议验证步骤'])
    if any((k in text for k in ('策略', '测试计划', 'strategy', '计划', 'plan'))):
        suggestions.extend(['拆成测试阶段', '给出风险清单', '推荐回归范围'])
    if any((k in text for k in ('自动化', '脚本', 'ci/cd', 'framework'))):
        suggestions.extend(['推荐自动化工具', '估算投入产出', '说明脚本维护要点'])
    if any((k in text for k in ('性能', 'performance', '并发', '压测', '负载'))):
        suggestions.extend(['给出压测场景', '建议监控指标', '说明通过标准'])
    if any((k in text for k in ('需求', 'requirement', '验收'))):
        suggestions.extend(['提炼测试点', '列出高风险场景', '起草验收标准'])
    if not suggestions:
        suggestions = ['能否详细说明一下？', '有具体的例子吗？', '还有其他相关问题吗？']
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:3]

def starter_suggestions(*, context: str='') -> list[str]:
    """开场建议（对齐 TestPilot get_chat_suggestions）。"""
    ctx = (context or '').strip()
    ctx_l = ctx.lower()
    if '缺陷' in ctx or 'bug' in ctx_l:
        return ['如何有效地报告缺陷？', '缺陷的生命周期是怎样的？', '如何预防缺陷的发生？']
    if '性能' in ctx or 'performance' in ctx_l:
        return ['性能测试的关键指标有哪些？', '如何进行负载测试？', '性能优化的常见方法？']
    if '需求' in ctx or 'requirement' in ctx_l:
        return ['根据当前需求提炼测试点', '帮我写验收标准', '列出高风险场景']
    if '测试' in ctx:
        return ['如何设计有效的测试用例？', '测试策略应该包含哪些要素？', '如何进行自动化测试？']
    return ['如何开展测试用例设计和评审工作？', '如何开展测试策略制定工作？', '如何进行缺陷分析和定位工作？', '如何开展自动化测试？', '如何开展性能测试？']
