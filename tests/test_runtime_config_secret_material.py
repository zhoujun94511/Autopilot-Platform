"""AUD-P0-002：运维配置 at-rest 加密不得回退开发默认 JWT。"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("cryptography")

from autopilot_platform.platform.ops import runtime_config as rc


@pytest.fixture()
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.delenv("MC_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!")
    rc.reload_runtime_config()
    yield tmp_path
    rc.reload_runtime_config()


def test_encrypt_rejects_insecure_default_material(isolated_runtime, monkeypatch):
    monkeypatch.delenv("MC_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!")
    assert rc.has_secure_config_secret_material() is False
    with pytest.raises(ValueError, match="缺少安全加密材料"):
        rc.encrypt_secret("sk-should-not-persist")


def test_encrypt_ok_with_config_secret(isolated_runtime, monkeypatch):
    monkeypatch.setenv("MC_CONFIG_SECRET", "unit-test-strong-config-secret!!")
    cipher = rc.encrypt_secret("hook-secret-plain")
    assert cipher.startswith("enc:v1:")
    assert "hook-secret-plain" not in cipher
    assert rc.decrypt_secret(cipher) == "hook-secret-plain"


def test_legacy_ciphertext_decrypt_and_reencrypt(isolated_runtime, monkeypatch):
    # 用 legacy 材料手工生成旧密文（仅测试迁移读路径）
    monkeypatch.delenv("MC_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!")
    legacy = "enc:v1:" + rc._fernet(allow_insecure_legacy=True).encrypt(
        b"old-ai-key"
    ).decode("ascii")

    path = rc.runtime_config_path()
    path.write_text(
        json.dumps({"AP_AI_API_KEY": legacy}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 仍无弱密钥：可读，但不重写为「安全」密文
    rc.reload_runtime_config()
    assert rc.load_runtime_config()["AP_AI_API_KEY"] == "old-ai-key"
    assert legacy in path.read_text(encoding="utf-8")

    # 配置强密钥后再 load → 自动 re-encrypt
    monkeypatch.setenv("MC_CONFIG_SECRET", "unit-test-strong-config-secret!!")
    rc.reload_runtime_config()
    raw = path.read_text(encoding="utf-8")
    assert "old-ai-key" not in raw
    assert "enc:v1:" in raw
    assert rc.load_runtime_config()["AP_AI_API_KEY"] == "old-ai-key"
    # 新密文应可用安全材料解密，且不再依赖 legacy
    disk = json.loads(raw)
    plain, used_legacy = rc._decrypt_secret_with_meta(disk["AP_AI_API_KEY"])
    assert plain == "old-ai-key"
    assert used_legacy is False


def test_save_secret_without_secure_material_fails(isolated_runtime, monkeypatch):
    monkeypatch.delenv("MC_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!")
    with pytest.raises(ValueError, match="缺少安全加密材料"):
        rc.save_runtime_config({"MC_WEBHOOK_SECRET": "hook-secret-plain"})


def test_plaintext_secret_on_disk_upgraded_when_secure_material(isolated_runtime, monkeypatch):
    """AUD-2026-05：历史明文 SECRET_KEYS 在具备安全材料时 load 即升密。"""
    path = rc.runtime_config_path()
    path.write_text(
        json.dumps({"AP_AI_API_KEY": "sk-plain-on-disk-should-upgrade"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    # 无安全材料：可读明文，不强制 rewrite（encrypt 会 fail-closed）
    monkeypatch.delenv("MC_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!")
    rc.reload_runtime_config()
    assert rc.load_runtime_config()["AP_AI_API_KEY"] == "sk-plain-on-disk-should-upgrade"
    assert "sk-plain-on-disk-should-upgrade" in path.read_text(encoding="utf-8")

    monkeypatch.setenv("MC_CONFIG_SECRET", "unit-test-strong-config-secret!!")
    rc.reload_runtime_config()
    raw = path.read_text(encoding="utf-8")
    assert "sk-plain-on-disk-should-upgrade" not in raw
    assert "enc:v1:" in raw
    assert rc.load_runtime_config()["AP_AI_API_KEY"] == "sk-plain-on-disk-should-upgrade"
