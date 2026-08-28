"""AUD-2026-12：chatFabPosition 纯函数契约（不跑 Vite）。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTIL = (
    ROOT
    / "autopilot_platform"
    / "frontend"
    / "src"
    / "utils"
    / "chatFabPosition.ts"
)
PANEL = (
    ROOT
    / "autopilot_platform"
    / "frontend"
    / "src"
    / "components"
    / "design"
    / "DesignChatPanel.vue"
)
FAB_COMP = (
    ROOT
    / "autopilot_platform"
    / "frontend"
    / "src"
    / "composables"
    / "useDesignChatFab.ts"
)
SESS_COMP = (
    ROOT
    / "autopilot_platform"
    / "frontend"
    / "src"
    / "composables"
    / "useDesignChatSessions.ts"
)


def test_chat_fab_util_and_composables_exist():
    assert UTIL.is_file()
    text = UTIL.read_text(encoding="utf-8")
    assert "CHAT_FAB_POS_KEY" in text
    assert "function clampChatFab" in text
    assert "function parseChatFabPos" in text
    assert FAB_COMP.is_file()
    assert "useDesignChatFab" in FAB_COMP.read_text(encoding="utf-8")
    assert SESS_COMP.is_file()
    assert "useDesignChatSessions" in SESS_COMP.read_text(encoding="utf-8")


def test_design_chat_panel_uses_composables_not_inline_fab_math():
    src = PANEL.read_text(encoding="utf-8")
    assert "useDesignChatFab" in src
    assert "useDesignChatSessions" in src
    assert "DesignChatMessages" in src
    assert "DesignChatComposer" in src
    assert "DesignChatSessionList" in src
    assert "from ../../utils/chatFabPosition" not in src  # 经 composable 间接用
    # 不再内联 clampFab / POS_KEY
    assert not re.search(r"\bfunction clampFab\b", src)
    assert "ap-mc-chat-fab-pos-v2" not in src


def test_design_chat_message_sfc_and_display_util():
    msg = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "components"
        / "design"
        / "DesignChatMessages.vue"
    )
    comp = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "components"
        / "design"
        / "DesignChatComposer.vue"
    )
    sess = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "components"
        / "design"
        / "DesignChatSessionList.vue"
    )
    util = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "utils"
        / "chatMessageDisplay.ts"
    )
    assert msg.is_file() and comp.is_file() and sess.is_file() and util.is_file()
    assert "renderChatBody" in util.read_text(encoding="utf-8")
    assert "defineExpose" in msg.read_text(encoding="utf-8")
    assert "CHAT_STARTER_QUESTIONS" in msg.read_text(encoding="utf-8")
    assert "测试助手" in msg.read_text(encoding="utf-8")
    assert "不落设计域" not in msg.read_text(encoding="utf-8")
    assert "DataPager" in sess.read_text(encoding="utf-8")
    assert "提问模板" in comp.read_text(encoding="utf-8")
    assert "keydown.enter.exact" in comp.read_text(encoding="utf-8")
    assert "Enter 发送，Shift+Enter 换行" in comp.read_text(encoding="utf-8")
    starters = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "utils"
        / "chatStarters.ts"
    )
    assert starters.is_file()
    assert "如何开展测试用例设计和评审工作？" in starters.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")
    assert ':show-templates="!generalMode"' not in panel
    assert "function onTemplatePick" in panel
    assert "|| generalMode.value) return" not in panel
    banner = (
        ROOT
        / "autopilot_platform"
        / "frontend"
        / "src"
        / "components"
        / "design"
        / "ProjectContextBanner.vue"
    ).read_text(encoding="utf-8")
    assert "也可以先问测试问题" in banner
    assert "不注入知识库" not in banner
