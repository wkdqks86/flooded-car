from __future__ import annotations

import csv
import datetime as dt
import io
import re

import streamlit as st

from flood_api import (
    ACCIDENT_KIND_HELP,
    ACCIDENT_KIND_OPTIONS,
    PLATE_LETTERS_BY_USAGE,
    PLATE_REGIONS,
    FloodApiError,
    FloodSearchResult,
    get_service_key,
    search_flood_history,
    years_ago,
)

st.set_page_config(
    page_title="침수차 진위확인",
    page_icon=":material/directions_car:",
    layout="centered",
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


def _init_state() -> None:
    defaults = {
        "search_error": None,
        "lookups": None,
        "searched_vehicles": [],
        "searched_kind": "전체",
        "searched_period": "전체 기간",
        "add_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _digits_only(value: str, size: int) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:size]


def assemble_vehicle_no(
    plate_format: str,
    region: str,
    prefix: str,
    letter: str,
    serial: str,
) -> str:
    prefix = _digits_only(prefix, PREFIX_LENGTH[plate_format])
    serial = _digits_only(serial, 4)
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


def normalize_date_range(value: object) -> tuple[dt.date, dt.date] | None:
    if value in (None, (), []):
        return None
    if isinstance(value, dt.date):
        return (value, value)
    if isinstance(value, (list, tuple)):
        dates = [item for item in value if isinstance(item, dt.date)]
        if not dates:
            return None
        if len(dates) == 1:
            return (dates[0], dates[0])
        start, end = dates[0], dates[1]
        if start > end:
            start, end = end, start
        return (start, end)
    return None


def resolve_period(
    period_mode: str,
    custom_range: tuple[dt.date, dt.date] | None,
) -> tuple[dt.date | None, dt.date | None, str]:
    today = dt.date.today()
    if period_mode == "최근 10년":
        start = years_ago(10, today)
        return start, today, f"{start.isoformat()} ~ {today.isoformat()}"
    if period_mode == "직접 지정" and custom_range is not None:
        start, end = custom_range
        return start, end, f"{start.isoformat()} ~ {end.isoformat()}"
    return None, None, "전체 기간"


@st.cache_data(ttl=300)
def _search(
    vehicle_no: str,
    start_date: dt.date | None,
    end_date: dt.date | None,
    accident_kind: str,
) -> FloodSearchResult:
    return search_flood_history(
        vehicle_no,
        start_date=start_date,
        end_date=end_date,
        accident_kind=accident_kind,
    )


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
            row = record.as_row()
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


def render_plate_composer() -> str:
    input_mode = st.segmented_control(
        "차량번호 입력 방식",
        options=["번호판 구성 선택", "직접 입력"],
        default="번호판 구성 선택",
        required=True,
        width="stretch",
        key="plate_input_mode",
    )
    if input_mode == "직접 입력":
        return st.text_input(
            "현재 차량번호",
            placeholder="예: 12가1234",
            help="공백 없이 현재 등록된 차량번호를 입력하세요.",
            key="direct_vehicle_no",
        ).replace(" ", "")

    plate_format = st.selectbox("번호판 형식", PLATE_FORMATS, key="plate_format")
    region = ""
    if plate_format == "지역번호판":
        region = st.selectbox("등록 지역", PLATE_REGIONS, key="plate_region")

    usage = st.segmented_control(
        "용도",
        options=list(PLATE_LETTERS_BY_USAGE),
        default="자가용",
        required=True,
        width="stretch",
        key="plate_usage",
    )
    letters = PLATE_LETTERS_BY_USAGE[usage]
    prefix_len = PREFIX_LENGTH[plate_format]

    prefix_col, letter_col, serial_col = st.columns([1.1, 1, 1.1])
    with prefix_col:
        prefix = st.text_input(
            "앞번호",
            max_chars=prefix_len,
            placeholder="1" * prefix_len,
            help=f"{prefix_len}자리 숫자",
            key=f"prefix_{plate_format}",
        )
    with letter_col:
        letter = st.selectbox("한글", letters, key=f"letter_{usage}")
    with serial_col:
        serial = st.text_input(
            "일련번호",
            max_chars=4,
            placeholder="1234",
            help="4자리 숫자",
            key="serial",
        )
    vehicle_no = assemble_vehicle_no(plate_format, region, prefix, letter, serial)
    st.caption(f"선택 번호: `{vehicle_no or '미완성'}`")
    return vehicle_no


def add_composed_vehicle() -> None:
    vehicle_no = st.session_state.get("pending_vehicle_no", "")
    error = validate_vehicle_no(vehicle_no)
    st.session_state.add_error = error
    if error:
        return
    current = parse_vehicle_nos(st.session_state.get("bulk_input", ""))
    if vehicle_no not in current:
        current.append(vehicle_no)
    st.session_state.bulk_input = "\n".join(current)


_init_state()

st.title("침수차 진위확인")
st.caption(
    "금융위원회·보험개발원 공공데이터로 자동차보험에 접수된 침수 이력을 조회합니다."
)

try:
    get_service_key()
except FloodApiError as exc:
    st.error(str(exc))
    st.info(
        "`.env.example`을 복사해 `.env`를 만들고, 폴더에 있는 인증키를 "
        "`DATA_GO_KR_SERVICE_KEY` 값으로 넣어 주세요."
    )
    st.code("DATA_GO_KR_SERVICE_KEY=발급받은_인증키", language="bash")
    st.stop()

st.subheader("조회 조건")

target_mode = st.segmented_control(
    "조회 대상",
    options=["한 대", "여러 대"],
    default="한 대",
    required=True,
    width="stretch",
)

composed_vehicle = render_plate_composer()
st.session_state.pending_vehicle_no = composed_vehicle

if target_mode == "여러 대":
    if st.button("목록에 추가", icon=":material/playlist_add:"):
        add_composed_vehicle()
    if st.session_state.add_error:
        st.warning(st.session_state.add_error)
    st.text_area(
        "차량번호 목록",
        placeholder="한 줄에 하나씩, 또는 쉼표로 구분해 입력하세요.\n12가1234\n34나5678",
        help=f"최대 {BATCH_LIMIT}대까지 조회할 수 있습니다.",
        key="bulk_input",
    )
    vehicle_nos = parse_vehicle_nos(st.session_state.get("bulk_input", ""))
    if not vehicle_nos and composed_vehicle:
        vehicle_nos = [composed_vehicle]
    invalid = [number for number in vehicle_nos if validate_vehicle_no(number)]
    st.caption(
        f"목록 {len(vehicle_nos)}대"
        + (f" · 형식 오류 {len(invalid)}대" if invalid else "")
        + " · 번호판을 고른 뒤 목록에 추가하거나, 아래에 붙여넣으세요."
    )
else:
    vehicle_nos = [composed_vehicle] if composed_vehicle else []

kind_label = st.segmented_control(
    "사고 종류명",
    options=list(ACCIDENT_KIND_OPTIONS),
    default="전체",
    required=True,
    width="stretch",
    help="보험개발원 침수사고 분류입니다. 전체를 고르면 종류 없이 조회합니다.",
)
if kind_label != "전체":
    st.caption(ACCIDENT_KIND_HELP[kind_label])

period_mode = st.segmented_control(
    "조회 기간",
    options=["전체 기간", "최근 10년", "직접 지정"],
    default="전체 기간",
    required=True,
    width="stretch",
    help="기간은 필수 아닙니다. 비우거나 전체를 고르면 해당 차량의 모든 침수 이력을 조회합니다.",
)
st.caption(
    "추천은 **전체 기간**입니다. 침수는 10년이 지나도 차량 상태와 가치에 남고, "
    "차량번호별 조회라 건수가 적어 전체 이력을 보는 편이 안전합니다. "
    "최근 매물만 빠르게 보려면 최근 10년을 고르세요."
)

custom_range = None
if period_mode == "직접 지정":
    custom_range = normalize_date_range(
        st.date_input(
            "사고 발생 기간",
            value=(),
            min_value=MIN_DATE,
            max_value=dt.date.today(),
            format="YYYY-MM-DD",
            help="시작일과 종료일을 캘린더에서 고르세요. 비우면 전체 기간으로 조회합니다.",
        )
    )
    if custom_range is None:
        st.caption("기간을 고르지 않으면 전체 기간으로 조회합니다.")

start_date, end_date, period_label = resolve_period(period_mode, custom_range)

with st.container(horizontal=True):
    search_clicked = st.button("침수 이력 조회", type="primary", icon=":material/search:")
    clear_clicked = st.button("조건 초기화", icon=":material/restart_alt:")

if clear_clicked:
    st.session_state.search_error = None
    st.session_state.lookups = None
    st.session_state.searched_vehicles = []
    st.session_state.add_error = None
    st.rerun()

if search_clicked:
    if not vehicle_nos:
        st.session_state.search_error = "조회할 차량번호를 입력해 주세요."
        st.session_state.lookups = None
    elif len(vehicle_nos) > BATCH_LIMIT:
        st.session_state.search_error = f"한 번에 {BATCH_LIMIT}대까지 조회할 수 있습니다."
        st.session_state.lookups = None
    else:
        invalid = [number for number in vehicle_nos if validate_vehicle_no(number)]
        if invalid:
            st.session_state.search_error = (
                "차량번호 형식이 올바르지 않습니다: " + ", ".join(invalid[:5])
            )
            st.session_state.lookups = None
        else:
            lookups: list[dict] = []
            errors: list[str] = []
            progress = st.progress(0, text="침수 이력을 조회하는 중...")
            for index, vehicle_no in enumerate(vehicle_nos, start=1):
                progress.progress(
                    index / len(vehicle_nos),
                    text=f"{vehicle_no} 조회 중 ({index}/{len(vehicle_nos)})",
                )
                try:
                    result = _search(
                        vehicle_no,
                        start_date,
                        end_date,
                        ACCIDENT_KIND_OPTIONS[kind_label],
                    )
                    lookups.append(
                        {
                            "vehicle_no": vehicle_no,
                            "error": "",
                            "total_count": result.total_count,
                            "records": result.records,
                        }
                    )
                except FloodApiError as exc:
                    message = str(exc)
                    errors.append(f"{vehicle_no}: {message}")
                    lookups.append(
                        {
                            "vehicle_no": vehicle_no,
                            "error": message,
                            "total_count": 0,
                            "records": [],
                        }
                    )
            progress.empty()
            if errors and len(errors) == len(lookups):
                st.session_state.search_error = (
                    "조회에 실패했습니다.\n" + "\n".join(errors[:3])
                )
            elif errors:
                st.session_state.search_error = "일부 차량 조회에 실패했습니다."
            else:
                st.session_state.search_error = None
            st.session_state.lookups = lookups
            st.session_state.searched_vehicles = vehicle_nos
            st.session_state.searched_kind = kind_label
            st.session_state.searched_period = period_label

if st.session_state.search_error:
    st.error(st.session_state.search_error)

lookups = st.session_state.lookups
if lookups is not None:
    st.divider()
    st.subheader("조회 결과")
    st.caption(
        f"{len(st.session_state.searched_vehicles)}대 · "
        f"{st.session_state.searched_kind} · {st.session_state.searched_period}"
    )

    history_count = sum(1 for item in lookups if item["records"])
    empty_count = sum(1 for item in lookups if not item["records"] and not item["error"])
    fail_count = sum(1 for item in lookups if item["error"])
    record_count = sum(len(item["records"]) for item in lookups)

    metric_cols = st.columns(4)
    metric_cols[0].metric("조회 대수", f"{len(lookups)}대")
    metric_cols[1].metric("침수 이력 있음", f"{history_count}대")
    metric_cols[2].metric("이력 없음", f"{empty_count}대")
    metric_cols[3].metric("조회 실패", f"{fail_count}대")

    if history_count:
        st.badge("침수 이력 있음", icon=":material/warning:", color="red")
    elif fail_count == len(lookups):
        st.badge("조회 실패", icon=":material/error:", color="red")
    else:
        st.badge("등록된 침수 이력 없음", icon=":material/check_circle:", color="green")
        st.info(
            "자동차보험에 접수된 침수 이력이 조회되지 않았습니다. "
            "보험 미처리 사고는 결과에 나타나지 않습니다."
        )

    status_rows = [
        {
            "차량번호": item["vehicle_no"],
            "결과": (
                "조회 실패"
                if item["error"]
                else ("침수 이력 있음" if item["records"] else "이력 없음")
            ),
            "건수": len(item["records"]),
        }
        for item in lookups
    ]
    st.dataframe(status_rows, hide_index=True)

    if record_count:
        history_rows = []
        for item in lookups:
            for record in item["records"]:
                history_rows.append(record.as_row())
        st.dataframe(history_rows, hide_index=True)

    csv_rows = lookup_rows(
        lookups,
        st.session_state.searched_period,
        st.session_state.searched_kind,
    )
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    st.download_button(
        "CSV로 저장",
        data=rows_to_csv(csv_rows),
        file_name=f"침수차조회_{stamp}.csv",
        mime="text/csv",
        icon=":material/download:",
        on_click="ignore",
    )

with st.expander("조회 시 유의사항"):
    st.markdown(
        """
- 결과가 없다고 해서 침수와 무관한 차량이라고 단정할 수 없습니다.
- 보험사에 신고되지 않았거나 자동차보험으로 처리되지 않은 침수는 확인되지 않습니다.
- 같은 번호로 재조회 시 이력이 사라지면 말소 등록 여부를 따로 확인해야 합니다.
- 정밀 확인이 필요하면 차량 진단 전문업체 또는 카히스토리를 함께 이용하세요.
        """
    )
