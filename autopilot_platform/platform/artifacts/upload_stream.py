"""UploadFile 分块落临时文件，统一实施请求体大小上限。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class UploadTooLarge(ValueError):
    pass


async def spool_upload(file, *, max_bytes: int, chunk_size: int = 1024 * 1024) -> tuple[Path, int]:
    fd, raw_path = tempfile.mkstemp(prefix="mc-upload-", suffix=".tmp")
    path = Path(raw_path)
    size = 0
    try:
        with os.fdopen(fd, "wb") as output:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if 0 < max_bytes < size:
                    raise UploadTooLarge(f"文件过大：上限 {max_bytes // (1024 * 1024)} MB")
                output.write(chunk)
        if size <= 0:
            raise ValueError("上传文件为空。")
        return path, size
    except BaseException:
        path.unlink(missing_ok=True)
        raise
