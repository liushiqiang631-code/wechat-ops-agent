from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from app.services.analytics.importers import import_metrics, wechat_day_to_metrics


def test_csv_import_maps_chinese_headers_and_sets_source(tmp_path: Path):
    path = tmp_path / "metrics.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["日期", "文章ID", "标题", "阅读人数", "分享人数", "收藏人数", "新增关注"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "日期": "2026-07-17",
                "文章ID": "a-1",
                "标题": "LangGraph 检查点",
                "阅读人数": "100",
                "分享人数": "8",
                "收藏人数": "12",
                "新增关注": "3",
            }
        )

    result = import_metrics(path)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.metric_date.utcoffset().total_seconds() == 8 * 3600
    assert record.reads == 100
    assert record.source_type == "csv"
    assert result.field_mapping["阅读人数"] == "reads"


def test_xlsx_import_uses_same_normalized_schema(tmp_path: Path):
    path = tmp_path / "metrics.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "date",
            "article_id",
            "title",
            "reads",
            "shares",
            "favorites",
            "followers_gained",
        ]
    )
    sheet.append(["2026-07-17", "a-2", "MCP 边界", 80, 4, 7, 2])
    workbook.save(path)

    result = import_metrics(path)

    assert result.records[0].article_title == "MCP 边界"
    assert result.records[0].source_type == "xlsx"


def test_csv_import_falls_back_to_gbk_encoding(tmp_path: Path):
    path = tmp_path / "metrics.csv"
    path.write_bytes(
        "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
        "2026-07-17,a-1,GBK测试,50,3,4,1\n".encode("gbk")
    )

    result = import_metrics(path)

    assert result.records[0].article_title == "GBK测试"
    assert result.records[0].reads == 50
    assert result.records[0].shares == 3


def test_wechat_day_to_metrics_maps_datacube_rows():
    records = wechat_day_to_metrics(
        [
            {"ref_date": "2026-07-17", "user_source": 0, "new_user": 3, "cancel_user": 1},
            {"ref_date": "2026-07-17", "user_source": 1, "new_user": 2, "cancel_user": 0},
        ],
        [
            {
                "ref_date": "2026-07-17",
                "msgid": 10001,
                "title": "LangGraph 检查点",
                "int_page_read_user": 120,
                "share_user": 9,
                "add_to_fav_user": 14,
            },
            {"ref_date": "2026-07-17", "msgid": 10002, "title": "无阅读数据"},
        ],
    )

    assert len(records) == 2
    first = records[0]
    assert first.source_type == "api"
    assert first.reads == 120
    assert first.shares == 9
    assert first.favorites == 14
    assert first.followers_gained == 5
    assert first.source_record_id == "wechat:2026-07-17:10001"
