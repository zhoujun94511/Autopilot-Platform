"""应用安装包（apk/ipa）独立存储：与工程制品目录隔离。"""

from __future__ import annotations

from ..core import api_messages as msg

import hashlib
import shutil
from pathlib import Path

from ..core.settings import app_builds_root, s3_bucket, s3_prefix, storage_backend
from ..core.storage_paths import resolve_file_under_root

_APP_STORE = None


class LocalAppBuildStore:
    @staticmethod
    def put_file(build_id: str, filename: str, data: bytes) -> str:
        root = app_builds_root() / build_id
        root.mkdir(parents=True, exist_ok=True)
        safe = Path(filename or "app.bin").name or "app.bin"
        path = root / safe
        path.write_bytes(data)
        return str(path.resolve())

    @staticmethod
    def put_file_path(build_id: str, filename: str, source: Path) -> str:
        root = app_builds_root() / build_id
        root.mkdir(parents=True, exist_ok=True)
        safe = Path(filename or "app.bin").name or "app.bin"
        path = root / safe
        shutil.copyfile(source, path)
        return str(path.resolve())

    @staticmethod
    def resolve_path(stored_uri: str) -> Path:
        return resolve_file_under_root(stored_uri, app_builds_root())

    @staticmethod
    def delete(build_id: str, stored_uri: str) -> None:
        root = app_builds_root() / build_id
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
        else:
            try:
                p = resolve_file_under_root(stored_uri, app_builds_root())
            except (FileNotFoundError, PermissionError):
                return
            p.unlink(missing_ok=True)


class S3AppBuildStore:
    def __init__(self) -> None:
        try:
            # noinspection PyPackageRequirements
            import boto3
        except ImportError as exc:
            raise RuntimeError(msg.S3_BOTO3_REQUIRED) from exc
        bucket = s3_bucket()
        if not bucket:
            raise RuntimeError(msg.S3_BUCKET_REQUIRED)
        self._bucket = bucket
        self._prefix = (s3_prefix() or "mc-artifacts/").replace("mc-artifacts/", "mc-app-builds/")
        if "app-builds" not in self._prefix:
            self._prefix = "mc-app-builds/"
        self._s3 = boto3.client("s3")
        self._cache = app_builds_root() / "_s3_cache"
        self._cache.mkdir(parents=True, exist_ok=True)

    def _key(self, build_id: str, filename: str) -> str:
        safe = Path(filename or "app.bin").name or "app.bin"
        return f"{self._prefix}{build_id}/{safe}"

    def put_file(self, build_id: str, filename: str, data: bytes) -> str:
        key = self._key(build_id, filename)
        ctype = "application/octet-stream"
        low = (filename or "").lower()
        if low.endswith(".apk"):
            ctype = "application/vnd.android.package-archive"
        elif low.endswith(".ipa"):
            ctype = "application/octet-stream"
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=ctype)
        local = self._cache / build_id
        local.mkdir(parents=True, exist_ok=True)
        safe = Path(filename or "app.bin").name or "app.bin"
        path = local / safe
        path.write_bytes(data)
        return f"s3://{self._bucket}/{key}"

    def put_file_path(self, build_id: str, filename: str, source: Path) -> str:
        key = self._key(build_id, filename)
        self._s3.upload_file(str(source), self._bucket, key)
        local = self._cache / build_id
        local.mkdir(parents=True, exist_ok=True)
        path = local / (Path(filename or "app.bin").name or "app.bin")
        shutil.copyfile(source, path)
        return f"s3://{self._bucket}/{key}"

    def resolve_path(self, stored_uri: str) -> Path:
        root = app_builds_root()
        if not stored_uri.startswith("s3://"):
            return resolve_file_under_root(stored_uri, root)
        rest = stored_uri[5:]
        bucket, _, key = rest.partition("/")
        parts = key.split("/")
        build_id = parts[-2] if len(parts) >= 2 else "obj"
        name = parts[-1] if parts else "app.bin"
        cached = self._cache / build_id / name
        if cached.is_file():
            return resolve_file_under_root(str(cached), root)
        cached.parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(bucket, key, str(cached))
        return resolve_file_under_root(str(cached), root)

    def delete(self, build_id: str, stored_uri: str) -> None:
        local = self._cache / build_id
        if local.is_dir():
            shutil.rmtree(local, ignore_errors=True)
        root = app_builds_root() / build_id
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
        if stored_uri.startswith("s3://"):
            rest = stored_uri[5:]
            bucket, _, key = rest.partition("/")
            try:
                self._s3.delete_object(Bucket=bucket, Key=key)
            except OSError:
                pass
            except Exception as exc:  # noqa: BLE001 — botocore ClientError 等
                if type(exc).__module__.startswith("botocore"):
                    return
                raise


def get_app_build_store() -> LocalAppBuildStore | S3AppBuildStore:
    global _APP_STORE
    if _APP_STORE is None:
        if storage_backend() == "s3":
            _APP_STORE = S3AppBuildStore()
        else:
            _APP_STORE = LocalAppBuildStore()
    return _APP_STORE


def reset_app_build_store() -> None:
    global _APP_STORE
    _APP_STORE = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def infer_platform(filename: str) -> str:
    low = (filename or "").lower()
    if low.endswith(".ipa"):
        return "ios"
    if low.endswith((".apk", ".apex", ".xapk")):
        return "android"
    return ""
