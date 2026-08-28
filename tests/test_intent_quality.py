"""Platform 意图质量与规范化。"""

from __future__ import annotations

from autopilot_platform.platform.artifacts.quality_check import assess_intent_steps, assess_logical_case


def test_assess_intent_steps_ok():
    q = assess_intent_steps(
        [
            {
                "id": "s1",
                "action": "click",
                "target": "登录",
                "value": "",
                "text": "点击登录",
            },
            {
                "id": "s2",
                "action": "type",
                "target": "用户名",
                "value": "admin",
                "text": "输入用户名",
            },
        ]
    )
    assert q["risk"] in ("low", "medium")
    assert q["intent_count"] == 2


def test_assess_intent_steps_missing_target():
    q = assess_intent_steps(
        [{"id": "s1", "action": "click", "target": "", "value": "", "text": ""}]
    )
    assert q["issues"]
    assert q["risk"] in ("medium", "high")


def test_assess_logical_merges_intent():
    q = assess_logical_case(
        title="登录",
        logical_steps=["点击登录"],
        expected_results=["进入首页"],
        intent_steps=[
            {
                "id": "s1",
                "action": "click",
                "target": "登录",
                "value": "",
                "text": "点击登录",
            }
        ],
    )
    assert "intent_quality" in q
    assert isinstance(q["score"], float)
    assert q.get("review_bucket") in (
        "auto_approvable",
        "needs_review",
        "reject_suggest",
    )


def test_review_bucket_auto_approvable():
    from autopilot_platform.platform.artifacts.quality_check import review_bucket_for_quality

    assert (
        review_bucket_for_quality({"score": 0.9, "risk": "low", "flags": []})
        == "auto_approvable"
    )
    assert (
        review_bucket_for_quality({"score": 0.3, "risk": "high", "flags": []})
        == "reject_suggest"
    )
