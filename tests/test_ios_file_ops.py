"""iOS fsync 文件变更操作单元测试。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autopilot_platform.runner.remote.ios import file_ops
from autopilot_platform.runner.remote.ios.command_dispatch import dispatch


def test_mkdir_invokes_fsync(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        calls.append(_args)
        return ""

    monkeypatch.setattr(file_ops, "_run", fake_run)
    out = file_ops.mkdir("udid1", "Documents/New", "com.example.app")
    assert out["ok"] is True
    assert calls == [
        [
            "fsync",
            "--app=com.example.app",
            "mkdir",
            "--path=Documents/New",
        ]
    ]


def test_delete_recursive_invokes_fsync_rm(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        calls.append(_args)
        return ""

    monkeypatch.setattr(file_ops, "_run", fake_run)
    file_ops.delete("udid1", "Documents/Old", recursive=True, app="com.example.app")
    assert calls[0] == [
        "fsync",
        "--app=com.example.app",
        "rm",
        "--r",
        "--path=Documents/Old",
    ]


def test_rename_pull_push_rm(monkeypatch):
    sequence: list[str] = []

    def fake_pull(_udid: str, path: str, app: str = "") -> list[str]:
        assert path == "Documents/a.txt"
        assert app == "com.example.app"
        import base64

        return [base64.b64encode(b"hello").decode("ascii")]

    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        sequence.append(" ".join(_args))
        return ""

    monkeypatch.setattr(file_ops, "pull", fake_pull)
    monkeypatch.setattr(file_ops, "_run", fake_run)
    out = file_ops.rename(
        "udid1",
        "Documents/a.txt",
        "Documents/b.txt",
        "com.example.app",
    )
    assert out["path"] == "Documents/b.txt"
    assert any("push" in step for step in sequence)
    assert any("rm" in step and "Documents/a.txt" in step for step in sequence)


def test_tree_retries_slash_on_afc_8(monkeypatch):
    calls: list[str] = []

    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        path = next(item.split("=", 1)[1] for item in _args if item.startswith("--path="))
        calls.append(path)
        if path != "/DCIM":
            raise RuntimeError('{"err":"error getting file info: afc error code: 8"}')
        return "|-100APPLE/\n|  |-IMG_0001.JPG\n"

    monkeypatch.setattr(file_ops, "_run", fake_run)
    out = file_ops.tree("udid1", "DCIM")
    assert out["ok"] is True
    assert "IMG_0001.JPG" in out["tree"]
    assert calls == ["DCIM", "/DCIM"]


def test_pull_retries_slash_then_reads(monkeypatch):
    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        src = next(item.split("=", 1)[1] for item in _args if item.startswith("--srcPath="))
        dst = next(item.split("=", 1)[1] for item in _args if item.startswith("--dstPath="))
        if src != "/DCIM/a.jpg":
            raise RuntimeError('{"err":"error getting file info: afc error code: 8"}')
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "a.jpg").write_bytes(b"jpeg-bytes")
        return ""

    monkeypatch.setattr(file_ops, "_run", fake_run)
    chunks = file_ops.pull("udid1", "DCIM/a.jpg")
    assert base64.b64decode(chunks[0]) == b"jpeg-bytes"


def test_pull_falls_back_to_pmd3_after_goios_miss(monkeypatch):
    def fake_run(_udid: str, _args: list[str], _timeout: int = 300) -> str:
        raise RuntimeError('{"err":"error getting file info: afc error code: 8"}')

    monkeypatch.setattr(file_ops, "_run", fake_run)
    monkeypatch.setattr(file_ops, "_pull_via_pmd3", lambda *_a, **_k: b"from-pmd3")
    chunks = file_ops.pull("udid1", "DCIM/a.jpg")
    assert base64.b64decode(chunks[0]) == b"from-pmd3"


def test_mkdir_rejects_root():
    with pytest.raises(ValueError):
        file_ops.mkdir("udid1", ".", "")


def test_pulled_file_uses_unique_rglob(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "IMG_0001.JPG"
    target.write_bytes(b"photo")
    found = file_ops._pulled_file(str(tmp_path), "/DCIM/IMG_0001.JPG")
    assert found == target


def test_chunk_bytes_splits_and_empty():
    assert file_ops._chunk_bytes(b"") == [""]
    blob = b"x" * (48 * 1024 + 3)
    chunks = file_ops._chunk_bytes(blob)
    assert len(chunks) == 2
    assert base64.b64decode(chunks[0] + chunks[1]) == blob


def test_to_afc_bytes_rejects_coroutine():
    async def _give():
        return b"nope"

    coro = _give()
    try:
        with pytest.raises(TypeError, match="AFC 内容类型无法读取"):
            file_ops._to_afc_bytes(coro)
    finally:
        coro.close()


def test_afc_read_retries_slash_then_returns_bytes():
    class FakeAfc:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_file_contents(self, name: str) -> bytes:
            self.calls.append(name)
            if name != "/DCIM/a.jpg":
                raise RuntimeError("afc error code: 8")
            return b"jpeg-bytes"

        @staticmethod
        def close() -> None:
            return None

    fake = FakeAfc()
    with patch.object(file_ops, "_open_afc_service", return_value=fake):
        data = asyncio.run(file_ops._afc_read_from_lockdown(object(), "DCIM/a.jpg", ""))
    assert data == b"jpeg-bytes"
    assert fake.calls == ["DCIM/a.jpg", "/DCIM/a.jpg"]


def test_afc_read_awaits_coroutine_payload():
    async def _give() -> bytes:
        return b"async-bytes"

    class FakeAfc:
        @staticmethod
        def get_file_contents(_name: str) -> object:
            return _give()

        @staticmethod
        def close() -> None:
            return None

    with patch.object(file_ops, "_open_afc_service", return_value=FakeAfc()):
        data = asyncio.run(file_ops._afc_read_from_lockdown(object(), "DCIM/a.jpg", ""))
    assert data == b"async-bytes"


def test_open_afc_service_house_arrest_then_afc(monkeypatch):
    house = MagicMock()
    afc = MagicMock()
    monkeypatch.setattr(
        "pymobiledevice3.services.house_arrest.HouseArrestService", house
    )
    monkeypatch.setattr("pymobiledevice3.services.afc.AfcService", afc)
    lockdown = object()
    file_ops._open_afc_service(lockdown, "com.example.app")
    house.assert_called_once()
    assert house.call_args.args[1] == "com.example.app"
    file_ops._open_afc_service(lockdown, "")
    afc.assert_called_once_with(lockdown)


def test_dispatch_file_pull_chunks_keep_request_id(monkeypatch):
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.ios.command_dispatch.file_ops.pull",
        lambda _udid, path, app="": [
            base64.b64encode(b"ab").decode("ascii"),
            base64.b64encode(b"c").decode("ascii"),
        ],
    )
    replies: list[dict] = []
    dispatch(
        MagicMock(),
        "UDID-FILE",
        {
            "t": "file.pull",
            "path": "DCIM/a.jpg",
            "id": "p1",
            "request_id": "p1",
        },
        replies.append,
    )
    assert replies[0]["t"] == "file.pull.ready"
    assert replies[0]["chunks"] == 2
    assert replies[0]["request_id"] == "p1"
    assert replies[1]["t"] == "file.pull.chunk"
    assert replies[1]["seq"] == 0
    assert replies[-1]["t"] == "file.pull.done"
    assert replies[-1]["id"] == "p1"
