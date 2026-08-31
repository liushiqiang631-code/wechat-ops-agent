from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile


class UploadTooLargeError(ValueError):
    pass


async def read_upload_limited(
    upload: object,
    *,
    max_bytes: int,
    chunk_size: int = 64 * 1024,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(f"上传文件不能超过 {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_xlsx_archive(
    body: bytes,
    *,
    max_uncompressed_bytes: int = 100 * 1024 * 1024,
    max_entries: int = 2_000,
) -> None:
    try:
        with ZipFile(BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise ValueError("XLSX 包含过多文件条目")
            if sum(entry.file_size for entry in entries) > max_uncompressed_bytes:
                raise ValueError("XLSX 解压后体积超过限制")
    except BadZipFile as exc:
        raise ValueError("XLSX 文件结构无效") from exc
