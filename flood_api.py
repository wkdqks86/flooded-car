"""금융위원회 침수차량진위확인 OpenAPI 클라이언트."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

API_URL = (
    "https://apis.data.go.kr/1160100/service/GetASLundService/getAutomobileLundinfo"
)
ENV_KEY_NAMES = ("DATA_GO_KR_SERVICE_KEY", "SERVICE_KEY")
REQUEST_TIMEOUT = 20

# 보험개발원/자동차보험에서 쓰는 침수 사고 종류 (API 응답 예시와 동일)
ACCIDENT_KIND_OPTIONS = {
    "전체": "",
    "침수분손": "침수분손",
    "침수전손": "침수전손",
}

ACCIDENT_KIND_HELP = {
    "침수분손": (
        "침수로 손상된 자동차의 수리비용이 보험회사가 인정한 자동차 가치를 "
        "초과하지 않은 경우입니다."
    ),
    "침수전손": (
        "수리비용이 자동차 가치를 초과하거나(추정전손), 수리가 불가능하거나 "
        "수리해도 자동차 기능을 다할 수 없는 경우(절대전손)입니다."
    ),
}

PLATE_REGIONS = [
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
]

# 자동차 등록번호 용도 기호 (국토교통부 자동차등록번호판 기준)
PLATE_LETTERS_BY_USAGE = {
    "자가용": list("가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주"),
    "영업용": list("바사아자"),
    "대여용": list("하허호"),
    "택배": ["배"],
}

PROJECT_DIR = Path(__file__).resolve().parent


class FloodApiError(Exception):
    """API 호출 또는 응답 처리 실패."""


@dataclass
class FloodRecord:
    vehicle_no: str
    accident_at: str
    accident_kind: str
    written_on: str

    def as_row(self) -> dict[str, str]:
        return {
            "현재 차량번호": self.vehicle_no,
            "사고 발생일시": self.accident_at,
            "사고 종류": self.accident_kind,
            "자료 작성일자": _format_written_date(self.written_on),
        }


@dataclass
class FloodSearchResult:
    result_code: str
    result_msg: str
    total_count: int
    page_no: int
    num_of_rows: int
    records: list[FloodRecord]


def get_service_key() -> str:
    load_dotenv(PROJECT_DIR / ".env", encoding="utf-8-sig", interpolate=False)
    for name in ENV_KEY_NAMES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    local_key = _key_from_local_file()
    if local_key:
        os.environ["DATA_GO_KR_SERVICE_KEY"] = local_key
        return local_key
    raise FloodApiError(
        "환경변수 DATA_GO_KR_SERVICE_KEY 가 없습니다. "
        "프로젝트 폴더의 .env 파일에 공공데이터포털 인증키를 넣어 주세요."
    )


def _key_from_local_file() -> str:
    for path in sorted(PROJECT_DIR.glob("*.txt")):
        name = path.name.lower()
        if path.name.startswith(("~", ".")):
            continue
        if "key" not in name and "api" not in name:
            continue
        try:
            first_line = path.read_text(encoding="utf-8-sig").strip().splitlines()[0].strip()
        except (OSError, IndexError, UnicodeError):
            continue
        if first_line and " " not in first_line and "=" not in first_line and len(first_line) >= 20:
            return first_line
    return ""


def years_ago(years: int, today: date | None = None) -> date:
    today = today or date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, month=2, day=28)


def search_flood_history(
    vehicle_no: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    accident_kind: str = "",
    page_no: int = 1,
    num_of_rows: int = 100,
    service_key: str | None = None,
) -> FloodSearchResult:
    queried_no = vehicle_no.strip()
    params: dict[str, Any] = {
        "serviceKey": service_key or get_service_key(),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "resultType": "json",
        "nowVhclNo": queried_no,
    }
    if accident_kind:
        params["acdnKindNm"] = accident_kind
    if start_date is not None or end_date is not None:
        start = start_date or date(1990, 1, 1)
        end = end_date or date.today()
        if start > end:
            start, end = end, start
        params["beginAcdnOccrDtm"] = f"{start:%Y-%m-%d} 00:00:00"
        params["endAcdnOccrDtm"] = f"{end + timedelta(days=1):%Y-%m-%d} 00:00:00"

    try:
        response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FloodApiError(f"공공데이터 API 요청에 실패했습니다. ({exc})") from exc

    payload = _parse_payload(response)
    header = _as_dict(payload.get("header"))
    body = _as_dict(payload.get("body"))
    result_code = str(header.get("resultCode", "")).strip()
    result_msg = str(header.get("resultMsg", "")).strip() or "응답 메시지가 없습니다."

    if result_code not in {"00", "0", "0000"}:
        raise FloodApiError(_describe_api_error(result_code, result_msg))

    records = [
        _to_record(item, fallback_vehicle=queried_no)
        for item in _iter_items(body.get("items"))
    ]
    return FloodSearchResult(
        result_code=result_code,
        result_msg=result_msg,
        total_count=_to_int(body.get("totalCount")),
        page_no=_to_int(body.get("pageNo"), default=page_no),
        num_of_rows=_to_int(body.get("numOfRows"), default=num_of_rows),
        records=records,
    )


def _parse_payload(response: requests.Response) -> dict[str, Any]:
    text = response.text.lstrip()
    if text.startswith("<"):
        return _parse_xml(text)
    try:
        data = response.json()
    except ValueError as exc:
        raise FloodApiError("API 응답을 JSON으로 해석하지 못했습니다.") from exc
    if not isinstance(data, dict):
        raise FloodApiError("API 응답 형식이 올바르지 않습니다.")
    return _as_dict(data.get("response", data))


def _parse_xml(text: str) -> dict[str, Any]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise FloodApiError("API 응답을 XML으로 해석하지 못했습니다.") from exc

    header_el = root.find("header")
    body_el = root.find("body")
    items: list[dict[str, str]] = []
    if body_el is not None:
        for item_el in body_el.findall("items/item"):
            items.append({child.tag: (child.text or "").strip() for child in item_el})

    def child_text(parent: ElementTree.Element | None, tag: str) -> str:
        if parent is None:
            return ""
        child = parent.find(tag)
        return "" if child is None or child.text is None else child.text.strip()

    return {
        "header": {
            "resultCode": child_text(header_el, "resultCode"),
            "resultMsg": child_text(header_el, "resultMsg"),
        },
        "body": {
            "numOfRows": child_text(body_el, "numOfRows"),
            "pageNo": child_text(body_el, "pageNo"),
            "totalCount": child_text(body_el, "totalCount"),
            "items": {"item": items},
        },
    }


def _iter_items(items: Any) -> list[dict[str, Any]]:
    if not items:
        return []
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if not isinstance(items, dict):
        return []
    item = items.get("item", items)
    if item in (None, "", []):
        return []
    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def _to_record(item: dict[str, Any], fallback_vehicle: str = "") -> FloodRecord:
    vehicle_no = str(item.get("nowVhclNo") or item.get("vhrno") or "").strip()
    return FloodRecord(
        vehicle_no=vehicle_no or fallback_vehicle,
        accident_at=str(item.get("acdnOccrDtm") or "").strip(),
        accident_kind=str(item.get("acdnKindNm") or "").strip(),
        written_on=str(item.get("dtaWrtDt") or "").strip(),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _format_written_date(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return value


def _describe_api_error(code: str, message: str) -> str:
    known = {
        "1": "어플리케이션 에러가 발생했습니다.",
        "10": "요청 파라미터가 올바르지 않습니다. 차량번호를 확인해 주세요.",
        "12": "해당 오픈API 서비스가 없거나 폐기되었습니다.",
        "20": "서비스 접근이 거부되었습니다.",
        "22": "일일 요청 횟수를 초과했습니다.",
        "30": "등록되지 않은 서비스키입니다. 환경변수 인증키를 확인해 주세요.",
        "31": "기한이 만료된 서비스키입니다.",
        "32": "등록되지 않은 IP입니다.",
        "99": "알 수 없는 오류가 발생했습니다.",
    }
    detail = known.get(code, message)
    return f"API 오류 ({code}): {detail}"
