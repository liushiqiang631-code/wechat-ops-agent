from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from app.domain.models import MetricImportResult, MetricRecord

ALIASES: dict[str, tuple[str, ...]] = {
    "metric_date": ("date", "metric_date", "日期", "时间"),
    "article_id": ("article_id", "文章ID", "图文ID", "msgid"),
    "article_title": ("title", "article_title", "标题", "文章标题"),
    "reads": ("reads", "read_user", "阅读人数", "阅读量"),
    "shares": ("shares", "share_user", "分享人数", "分享量"),
    "favorites": ("favorites", "add_to_fav_user", "收藏人数", "收藏量"),
    "followers_gained": ("followers_gained", "new_user", "新增关注", "新增用户"),
}


def _map_fields(headers: list[str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias in headers:
                normalized[alias] = target
                break
    required = set(ALIASES) - set(normalized.values())
    if required:
        raise ValueError(f"missing required metric fields: {sorted(required)}")
    return normalized


CSV_ENCODINGS = ("utf-8-sig", "gb18030", "gbk")
MAX_IMPORT_ROWS = 100_000


def _rows(path: Path) -> tuple[list[dict[str, object]], str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_error: UnicodeDecodeError | None = None
        for encoding in CSV_ENCODINGS:
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    return list(csv.DictReader(handle)), "csv"
            except UnicodeDecodeError as error:
                last_error = error
        raise ValueError(
            f"metrics CSV is not decodable as any of {', '.join(CSV_ENCODINGS)}: {last_error}"
        )
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        first = next(values, None)
        if first is None:
            workbook.close()
            return [], "xlsx"
        headers = [str(value or "") for value in first]
        rows: list[dict[str, object]] = []
        for index, row in enumerate(values, 1):
            if index > MAX_IMPORT_ROWS:
                workbook.close()
                raise ValueError(f"metrics file exceeds {MAX_IMPORT_ROWS} rows")
            rows.append(dict(zip(headers, row, strict=False)))
        workbook.close()
        return rows, "xlsx"
    raise ValueError(f"unsupported metrics file: {suffix}")


def _int_cell(value: object) -> int:
    if value is None or value == "":
        return 0
    return int(str(value).replace(",", "").strip())


def _date(value: object, timezone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            raise ValueError("empty metric date")
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def wechat_day_to_metrics(
    user_summary: list[dict[str, object]],
    article_summary: list[dict[str, object]],
    *,
    timezone: str = "Asia/Shanghai",
) -> list[MetricRecord]:
    """Map one WeChat datacube day into MetricRecords (source_type='api').

    `user_summary` comes from /datacube/getusersummary and `article_summary` from
    /datacube/getarticlesummary. Unknown or malformed rows are skipped.

    New followers are a day-level total; they are attached to the first article row
    of the day only, so window sums do not multiply them per article.
    """
    gained = sum(int(item.get("new_user", 0) or 0) for item in user_summary)
    tz = ZoneInfo(timezone)
    records: list[MetricRecord] = []
    followers_assigned = False
    for item in article_summary:
        ref_date = item.get("ref_date")
        msgid = item.get("msgid")
        if not ref_date or msgid is None:
            continue
        day = datetime.strptime(str(ref_date), "%Y-%m-%d").replace(tzinfo=tz)
        followers = gained if not followers_assigned else 0
        followers_assigned = True
        records.append(
            MetricRecord(
                metric_date=day,
                article_id=str(msgid),
                article_title=str(item.get("title") or ""),
                reads=int(item.get("int_page_read_user", 0) or 0),
                shares=int(item.get("share_user", 0) or 0),
                favorites=int(item.get("add_to_fav_user", 0) or 0),
                followers_gained=followers,
                source_type="api",
                source_record_id=f"wechat:{ref_date}:{msgid}",
            )
        )
    return records


def import_metrics(path: Path, timezone: str = "Asia/Shanghai") -> MetricImportResult:
    path = Path(path)
    raw_rows, source_type = _rows(path)
    if not raw_rows:
        return MetricImportResult(records=[], field_mapping={}, source_file=str(path))
    headers = [str(key) for key in raw_rows[0]]
    mapping = _map_fields(headers)
    records: list[MetricRecord] = []
    skipped = 0
    tz = ZoneInfo(timezone)
    for raw in raw_rows:
        try:
            normalized = {target: raw[source] for source, target in mapping.items()}
            article_id = str(normalized["article_id"] or "").strip()
            metric_date = _date(normalized["metric_date"], tz)
            if not article_id:
                raise ValueError("empty article_id")
            # Identity is content-based (not the on-disk filename), so re-uploading
            # the same export is idempotent and MetricsRepository dedup works.
            identity = f"{article_id}:{metric_date.isoformat()}"
            records.append(
                MetricRecord(
                    metric_date=metric_date,
                    article_id=article_id,
                    article_title=str(normalized["article_title"] or ""),
                    reads=_int_cell(normalized["reads"]),
                    shares=_int_cell(normalized["shares"]),
                    favorites=_int_cell(normalized["favorites"]),
                    followers_gained=_int_cell(normalized["followers_gained"]),
                    source_type=source_type,
                    source_record_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
                )
            )
        except (ValueError, TypeError):
            skipped += 1
    return MetricImportResult(
        records=records,
        field_mapping=mapping,
        source_file=str(path),
        skipped_rows=skipped,
    )
