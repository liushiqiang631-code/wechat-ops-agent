from __future__ import annotations

import json
from datetime import datetime

from app.config.settings import Settings
from app.container import build_container
from app.services.analytics.metrics import calculate_windows
from app.services.analytics.quality import build_quality_report


def main() -> int:
    settings = Settings()
    container = build_container(settings)
    records = container.metrics.list()
    reference = datetime.now(settings.timezone)
    payload = {
        "quality": build_quality_report(records, now=reference).model_dump(mode="json"),
        "windows": {
            key: value.model_dump(mode="json")
            for key, value in calculate_windows(records, as_of=reference).items()
        },
    }
    container.artifacts.write_json("analytics", "operations_report", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
