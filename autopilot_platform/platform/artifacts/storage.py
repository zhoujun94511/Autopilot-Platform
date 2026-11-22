"""制品存储抽象：本地默认；MC_STORAGE=s3 时走 S3（需 boto3）。"""

from __future__ import annotations

from ..core import api_messages as msg

import shutil
import zipfile
from pathlib import Path
from typing import Protocol

from autopilot_platform.core.safe_zip import safe_extractall

from ..core.settings import artifacts_root, storage_backend, s3_bucket, s3_prefix
from ..core.storage_paths import resolve_file_under_root


class ArtifactStore(Protocol):
    def put_zip(self, artifact_id: str, data: bytes) -> tuple[str, str]:
        """返回 (stored_uri, extract_path)。extract_path 为本机可执行工程根。"""

    def put_zip_path(self, artifact_id: str, source: Path) -> tuple[str, str]:
        """从临时文件存储，避免将整个 zip 载入内存。"""

    def resolve_zip_path(self, stored_uri: str) -> Path:
        """供 FileResponse / 下载：保证返回本地 zip 路径（S3 会拉到缓存）。"""

    def delete(self, artifact_id: str, stored_uri: str) -> None:
        """删除本地/远端制品文件（忽略缺失）。"""


class LocalArtifactStore:
    @staticmethod
    def put_zip(artifact_id: str, data: bytes) -> tuple[str, str]:
        root = artifacts_root() / artifact_id
        root.mkdir(parents=True, exist_ok=True)
        zip_path = root / "project.zip"
        zip_path.write_bytes(data)
        extract_dir = root / "project"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, extract_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(root, ignore_errors=True)
            raise ValueError(msg.UPLOAD_MUST_ZIP) from None
        except ValueError:
            shutil.rmtree(root, ignore_errors=True)
            raise
        project_root = _detect_project_root(extract_dir)
        return str(zip_path.resolve()), str(project_root.resolve())

    @staticmethod
    def put_zip_path(artifact_id: str, source: Path) -> tuple[str, str]:
        root = artifacts_root() / artifact_id
        root.mkdir(parents=True, exist_ok=True)
        zip_path = root / "project.zip"
        shutil.copyfile(source, zip_path)
        extract_dir = root / "project"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, extract_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(root, ignore_errors=True)
            raise ValueError(msg.UPLOAD_MUST_ZIP) from None
        except ValueError:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return str(zip_path.resolve()), str(_detect_project_root(extract_dir).resolve())

    @staticmethod
    def resolve_zip_path(stored_uri: str) -> Path:
        root = artifacts_root()
        return resolve_file_under_root(stored_uri, root)

    @staticmethod
    def delete(artifact_id: str, stored_uri: str) -> None:
        root = artifacts_root() / artifact_id
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
        else:
            try:
                p = resolve_file_under_root(stored_uri, artifacts_root())
            except (FileNotFoundError, PermissionError):
                return
            p.unlink(missing_ok=True)


class S3ArtifactStore:
    def __init__(self) -> None:
        try:
            # noinspection PyPackageRequirements
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "S3 storage requires boto3: pip install boto3"
            ) from exc
        bucket = s3_bucket()
        if not bucket:
            raise RuntimeError(msg.S3_BUCKET_REQUIRED)
        self._bucket = bucket
        self._prefix = s3_prefix()
        self._s3 = boto3.client("s3")
        self._cache = artifacts_root() / "_s3_cache"
        self._cache.mkdir(parents=True, exist_ok=True)

    def _key(self, artifact_id: str) -> str:
        return f"{self._prefix}{artifact_id}/project.zip"

    def put_zip(self, artifact_id: str, data: bytes) -> tuple[str, str]:
        key = self._key(artifact_id)
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType="application/zip")
        # 本地解压缓存供同机 Runner / 索引
        local_root = self._cache / artifact_id
        local_root.mkdir(parents=True, exist_ok=True)
        zip_path = local_root / "project.zip"
        zip_path.write_bytes(data)
        extract_dir = local_root / "project"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, extract_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(local_root, ignore_errors=True)
            raise ValueError(msg.UPLOAD_MUST_ZIP) from None
        except ValueError:
            shutil.rmtree(local_root, ignore_errors=True)
            raise
        project_root = _detect_project_root(extract_dir)
        uri = f"s3://{self._bucket}/{key}"
        return uri, str(project_root.resolve())

    def put_zip_path(self, artifact_id: str, source: Path) -> tuple[str, str]:
        key = self._key(artifact_id)
        self._s3.upload_file(
            str(source),
            self._bucket,
            key,
            ExtraArgs={"ContentType": "application/zip"},
        )
        local_root = self._cache / artifact_id
        local_root.mkdir(parents=True, exist_ok=True)
        zip_path = local_root / "project.zip"
        shutil.copyfile(source, zip_path)
        extract_dir = local_root / "project"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, extract_dir)
        except (zipfile.BadZipFile, ValueError):
            shutil.rmtree(local_root, ignore_errors=True)
            raise ValueError(msg.UPLOAD_MUST_ZIP) from None
        return f"s3://{self._bucket}/{key}", str(_detect_project_root(extract_dir).resolve())

    def resolve_zip_path(self, stored_uri: str) -> Path:
        root = artifacts_root()
        if not stored_uri.startswith("s3://"):
            return resolve_file_under_root(stored_uri, root)
        # s3://bucket/key
        rest = stored_uri[5:]
        bucket, _, key = rest.partition("/")
        aid = key.split("/")[0] if "/" in key else "obj"
        # try cache by artifact id segment
        parts = key.split("/")
        artifact_id = parts[-2] if len(parts) >= 2 else aid
        cached = self._cache / artifact_id / "project.zip"
        if cached.is_file():
            return resolve_file_under_root(str(cached), root)
        cached.parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(bucket, key, str(cached))
        return resolve_file_under_root(str(cached), root)

    def delete(self, artifact_id: str, stored_uri: str) -> None:
        """删除远端对象与本地缓存；对象不存在时忽略。"""
        bucket, key = self._bucket, self._key(artifact_id)
        if (stored_uri or "").startswith("s3://"):
            rest = stored_uri[5:]
            b, _, k = rest.partition("/")
            if b and k:
                bucket, key = b, k
        try:
            self._s3.delete_object(Bucket=bucket, Key=key)
        except (OSError, RuntimeError, AttributeError):
            pass
        except Exception as exc:  # noqa: BLE001 — botocore 无分析桩时用模块名识别
            if not type(exc).__module__.startswith("botocore"):
                raise
        local_root = self._cache / artifact_id
        if local_root.is_dir():
            shutil.rmtree(local_root, ignore_errors=True)


def _detect_project_root(extract_dir: Path) -> Path:
    children = [p for p in extract_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


_store: ArtifactStore | None = None


def get_artifact_store() -> ArtifactStore:
    global _store
    if _store is not None:
        return _store
    if storage_backend() == "s3":
        _store = S3ArtifactStore()
    else:
        _store = LocalArtifactStore()
    return _store


def reset_artifact_store() -> None:
    global _store
    _store = None
