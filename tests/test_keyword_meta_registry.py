"""keyword_meta / registry 对齐 — apply_risk_levels 与 Platform ap 拷贝一致。"""

from __future__ import annotations

from autopilot_platform.ap.keywords.registry import (
    REGISTRY,
    apply_risk_levels,
    keyword,
)


def test_apply_risk_levels_merges_from_metadata():
    kid = "test.risk.merge.kw"
    REGISTRY.pop(kid, None)

    @keyword(kid, name="t")
    def _stub(_ctx):  # noqa: ANN001
        return None

    apply_risk_levels({kid: "write", "missing.kw": "read", kid + ".bad": "nope"})
    assert REGISTRY[kid].risk_level == "write"


def test_apply_risk_levels_does_not_override_decorator():
    kid = "test.risk.keep.kw"
    REGISTRY.pop(kid, None)

    @keyword(kid, risk_level="irreversible")
    def _stub2(_ctx):  # noqa: ANN001
        return None

    apply_risk_levels({kid: "read"})
    assert REGISTRY[kid].risk_level == "irreversible"


def test_load_catalog_imports_ap_keywords():
    from autopilot_platform.ap.metadata.keyword_meta import load_catalog

    catalog = load_catalog()
    assert len(catalog.by_id) > 20
    # 至少一个已注册关键字可合并 risk（不抛 ImportError）
    registered = [m for m in catalog.by_id.values() if m.keyword_id in REGISTRY]
    assert registered, "expected some XML keywords registered in REGISTRY"
