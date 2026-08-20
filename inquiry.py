"""침수차 조회 공통 로직."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re

from flood_api import (
    ACCIDENT_KIND_OPTIONS,
    PLATE_REGIONS,
    FloodApiError,
    search_flood_history,
    years_ago,
)

PLATE_FORMATS = ("신형 3자리", "신형 4자리", "구형 2자리", "지역번호판")
PREFIX_LENGTH = {
    "신형 3자리": 3,
    "신형 4자리": 4,
    "구형 2자리": 2,
    "지역번호판": 2,
}
PLATE_PATTERN = re.compile(
    rf"^(?:{'|'.join(PLATE_REGIONS)})?\d{{2,4}}[가-힣]\d{{4}}$"
)
CSV_COLUMNS = [
    "현재 차량번호",
    "조회 결과",
    "사고 발생일시",
    "사고 종류",
    "자료 작성일자",
    "조회 기간",
    "사고 종류 필터",
]
BATCH_LIMIT = 50
MIN_DATE = dt.date(1990, 1, 1)
PERIOD_OPTIONS = ("전체 기간", "최근 10년", "직접 지정")


def digits_only(value: str, size: int) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:size]


def assemble_vehicle_no(
    plate_format: str,
    region: str,
    prefix: str,
    letter: str,
    serial: str,
) -> str:
    prefix = digits_only(prefix, PREFIX_LENGTH[plate_format])
    serial = digits_only(serial, 4)
    region_part = region if plate_format == "지역번호판" else ""
    return f"{region_part}{prefix}{letter}{serial}"


def validate_vehicle_no(vehicle_no: str) -> str | None:
    if not vehicle_no:
        return "차량번호를 입력해 주세요."
    if not PLATE_PATTERN.fullmatch(vehicle_no):
        return "차량번호 형식이 올바르지 않습니다. 예: 12가1234, 123가1234, 서울12가1234"
    return None


def parse_vehicle_nos(text: str) -> list[str]:
    parts = re.split(r"[\s,;]+", text.strip()) if text.strip() else []
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        number = part.replace(" ", "")
        if number and number not in seen:
            seen.add(number)
            unique.append(number)
    return unique


def resolve_period(
    period_mode: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> tuple[dt.date | None, dt.date | None, str]:
    today = dt.date.today()
    if period_mode == "최근 10년":
        start = years_ago(10, today)
        return start, today, f"{start.isoformat()} ~ {today.isoformat()}"
    if period_mode == "직접 지정" and (start_date or end_date):
        start = start_date or MIN_DATE
        end = end_date or today
        if start > end:
            start, end = end, start
        return start, end, f"{start.isoformat()} ~ {end.isoformat()}"
    return None, None, "전체 기간"


def lookup_rows(
    lookups: list[dict],
    period_label: str,
    kind_label: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in lookups:
        records = item.get("records") or []
        if item.get("error"):
            rows.append(
                {
                    "현재 차량번호": item["vehicle_no"],
                    "조회 결과": f"조회 실패 ({item['error']})",
                    "사고 발생일시": "",
                    "사고 종류": "",
                    "자료 작성일자": "",
                    "조회 기간": period_label,
                    "사고 종류 필터": kind_label,
                }
            )
            continue
        if not records:
            rows.append(
                {
                    "현재 차량번호": item["vehicle_no"],
                    "조회 결과": "등록된 침수 이력 없음",
                    "사고 발생일시": "",
                    "사고 종류": "",
                    "자료 작성일자": "",
                    "조회 기간": period_label,
                    "사고 종류 필터": kind_label,
                }
            )
            continue
        for record in records:
            row = record.as_row() if hasattr(record, "as_row") else dict(record)
            row["조회 결과"] = "침수 이력 있음"
            row["조회 기간"] = period_label
            row["사고 종류 필터"] = kind_label
            rows.append(row)
    return rows


def rows_to_csv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def search_vehicles(
    vehicle_nos: list[str],
    *,
    kind_label: str,
    period_mode: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> tuple[list[dict], str | None, str]:
    if not vehicle_nos:
        return [], "조회할 차량번호를 입력해 주세요.", "전체 기간"
    if len(vehicle_nos) > BATCH_LIMIT:
        return [], f"한 번에 {BATCH_LIMIT}대까지 조회할 수 있습니다.", "전체 기간"

    invalid = [number for number in vehicle_nos if validate_vehicle_no(number)]
    if invalid:
        return [], "차량번호 형식이 올바르지 않습니다: " + ", ".join(invalid[:5]), "전체 기간"

    start, end, period_label = resolve_period(period_mode, start_date, end_date)
    kind = ACCIDENT_KIND_OPTIONS.get(kind_label, "")
    lookups: list[dict] = []
    errors: list[str] = []
    for vehicle_no in vehicle_nos:
        try:
            result = search_flood_history(
                vehicle_no,
                start_date=start,
                end_date=end,
                accident_kind=kind,
            )
            lookups.append(
                {
                    "vehicle_no": vehicle_no,
                    "error": "",
                    "total_count": result.total_count,
                    "records": [record.as_row() for record in result.records],
                    "has_history": bool(result.records),
                }
            )
        except FloodApiError as exc:
            message = str(exc)
            errors.append(message)
            lookups.append(
                {
                    "vehicle_no": vehicle_no,
                    "error": message,
                    "total_count": 0,
                    "records": [],
                    "has_history": False,
                }
            )

    if errors and len(errors) == len(lookups):
        return lookups, "조회에 실패했습니다. " + errors[0], period_label
    if errors:
        return lookups, "일부 차량 조회에 실패했습니다.", period_label
    return lookups, None, period_label
