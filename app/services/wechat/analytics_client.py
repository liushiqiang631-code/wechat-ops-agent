from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.wechat.client import WeChatClient


class WeChatAnalyticsClient:
    def __init__(self, client: WeChatClient, timezone: str = "Asia/Shanghai"):
        self.client = client
        self.timezone = ZoneInfo(timezone)

    def _probe_window(self) -> dict[str, str]:
        day = (datetime.now(self.timezone) - timedelta(days=1)).date().isoformat()
        return {"begin_date": day, "end_date": day}

    async def probe_user(self, token: str) -> dict:
        return await self.client.request_json(
            "POST",
            "/datacube/getusersummary",
            params={"access_token": token},
            json=self._probe_window(),
        )

    async def probe_article(self, token: str) -> dict:
        return await self.client.request_json(
            "POST",
            "/datacube/getarticlesummary",
            params={"access_token": token},
            json=self._probe_window(),
        )

    async def fetch_user_range(self, token: str, begin_date: str, end_date: str) -> dict:
        return await self.client.request_json(
            "POST",
            "/datacube/getusersummary",
            params={"access_token": token},
            json={"begin_date": begin_date, "end_date": end_date},
        )

    async def fetch_article_day(self, token: str, day: str) -> dict:
        return await self.client.request_json(
            "POST",
            "/datacube/getarticlesummary",
            params={"access_token": token},
            json={"begin_date": day, "end_date": day},
        )
