from __future__ import annotations

import hashlib
import json

from app.domain.enums import EvidenceType
from app.domain.models import DraftReceipt
from app.repositories.publications import PublicationRepository
from app.services.wechat.client import WeChatClient


class DraftService:
    def __init__(
        self,
        client: WeChatClient,
        repository: PublicationRepository | None = None,
    ):
        self.client = client
        self.repository = repository

    async def create(self, token: str, article: dict) -> str:
        payload = await self.client.request_json(
            "POST",
            "/cgi-bin/draft/add",
            params={"access_token": token},
            json={"articles": [article]},
            timeout=60.0,
        )
        return str(payload["media_id"])

    async def create_idempotent(
        self,
        token: str,
        *,
        account_id: str,
        task_id: str,
        article: dict,
        evidence_type: EvidenceType,
    ) -> DraftReceipt:
        if self.repository is None:
            raise RuntimeError("publication repository is required for idempotent draft creation")
        encoded = json.dumps(article, ensure_ascii=False, sort_keys=True).encode("utf-8")
        content_hash = hashlib.sha256(encoded).hexdigest()
        key = f"{account_id}:{task_id}:{content_hash}"
        try:
            existing = self.repository.get_draft_receipt(key)
            return existing
        except KeyError:
            pass
        media_id = await self.create(token, article)
        return self.repository.save_draft_receipt(
            DraftReceipt(
                idempotency_key=key,
                task_id=task_id,
                media_id=media_id,
                content_hash=content_hash,
                evidence_type=evidence_type,
            )
        )
