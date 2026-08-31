from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.config.settings import Settings
from app.container import build_container
from app.services.analytics.importers import import_metrics
from app.services.analytics.metrics import calculate_windows
from app.services.analytics.quality import build_quality_report


def main() -> int:
    parser = argparse.ArgumentParser(description="导入微信公众号 CSV/XLSX 指标")
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    settings = Settings()
    container = build_container(settings)
    result = import_metrics(args.file, settings.business_timezone)
    inserted = container.metrics.insert(result.records)
    records = container.metrics.list()
    reference = datetime.now(settings.timezone)
    payload = {
        "inserted": inserted,
        "quality": build_quality_report(records, now=reference).model_dump(mode="json"),
        "windows": {
            key: value.model_dump(mode="json")
            for key, value in calculate_windows(records, as_of=reference).items()
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
