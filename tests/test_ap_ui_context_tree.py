"""Platform ui_context 可加载 ap.inspector.tree。"""

from __future__ import annotations


def test_platform_ui_context_loads_tree_parsers():
    from autopilot_platform.ap.intent import ui_context

    parse_android, parse_ios = ui_context._load_mobile_tree_parsers()
    assert parse_android is not None and parse_ios is not None
    root = parse_android(
        '<?xml version="1.0"?><hierarchy><node class="android.widget.Button" '
        'text="OK" clickable="true" bounds="[0,0][10,10]" /></hierarchy>'
    )
    nodes = list(root.iter_all())
    assert nodes
