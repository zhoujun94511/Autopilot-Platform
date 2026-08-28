"""Audit actor helpers."""
from __future__ import annotations
from autopilot_platform.platform.auth import AuthContext
def actor(auth: AuthContext) -> str:
    return (auth.username or auth.user_id or "").strip() or "system"
