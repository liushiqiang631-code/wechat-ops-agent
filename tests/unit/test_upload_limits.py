from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from app.api.uploads import UploadTooLargeError, read_upload_limited, validate_xlsx_archive


class FakeUpload:
    def __init__(self, body: bytes):
        self.body = body
        self.offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_read_upload_limited_rejects_before_buffering_unbounded_body() -> None:
    upload = FakeUpload(b"x" * 32)

    with pytest.raises(UploadTooLargeError):
        await read_upload_limited(upload, max_bytes=16, chunk_size=8)


@pytest.mark.asyncio
async def test_read_upload_limited_returns_small_body() -> None:
    upload = FakeUpload(b"metrics")

    assert await read_upload_limited(upload, max_bytes=16, chunk_size=4) == b"metrics"


def test_xlsx_archive_rejects_excessive_uncompressed_size() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"12345")

    with pytest.raises(ValueError, match="解压后体积"):
        validate_xlsx_archive(buffer.getvalue(), max_uncompressed_bytes=4)
