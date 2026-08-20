from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from flood_api import (
    ACCIDENT_KIND_HELP,
    ACCIDENT_KIND_OPTIONS,
    PLATE_LETTERS_BY_USAGE,
    PLATE_REGIONS,
    FloodApiError,
    get_service_key,
)
from inquiry import (
    BATCH_LIMIT,
    MIN_DATE,
    PERIOD_OPTIONS,
    PLATE_FORMATS,
    PREFIX_LENGTH,
    lookup_rows,
    parse_vehicle_nos,
    rows_to_csv,
    search_vehicles,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="침수차 진위확인")


def _parse_date(value: str) -> dt.date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _page_context(**extra):
    today = dt.date.today()
    context = {
        "kinds": list(ACCIDENT_KIND_OPTIONS),
        "kind_help": ACCIDENT_KIND_HELP,
        "periods": PERIOD_OPTIONS,
        "plate_formats": PLATE_FORMATS,
        "prefix_length": PREFIX_LENGTH,
        "regions": PLATE_REGIONS,
        "letters_by_usage": PLATE_LETTERS_BY_USAGE,
        "batch_limit": BATCH_LIMIT,
        "min_date": MIN_DATE.isoformat(),
        "today": today.isoformat(),
        "key_ready": True,
        "key_error": "",
        "error": None,
        "lookups": None,
        "period_label": "전체 기간",
        "kind_label": "전체",
        "vehicle_text": "",
        "period_mode": "전체 기간",
        "start_date": "",
        "end_date": "",
        "history_count": 0,
        "empty_count": 0,
        "fail_count": 0,
        "history_rows": [],
    }
    try:
        get_service_key()
    except FloodApiError as exc:
        context["key_ready"] = False
        context["key_error"] = str(exc)
    context.update(extra)
    return context


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_page_context(request=request),
    )


@app.post("/", response_class=HTMLResponse)
def search(
    request: Request,
    vehicle_text: str = Form(""),
    kind_label: str = Form("전체"),
    period_mode: str = Form("전체 기간"),
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    vehicle_nos = parse_vehicle_nos(vehicle_text)
    lookups, error, period_label = search_vehicles(
        vehicle_nos,
        kind_label=kind_label,
        period_mode=period_mode,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
    )
    history_rows = []
    for item in lookups:
        history_rows.extend(item["records"])
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=_page_context(
            request=request,
            error=error,
            lookups=lookups,
            period_label=period_label,
            kind_label=kind_label,
            vehicle_text=vehicle_text,
            period_mode=period_mode,
            start_date=start_date,
            end_date=end_date,
            history_count=sum(1 for item in lookups if item["has_history"]),
            empty_count=sum(
                1 for item in lookups if not item["has_history"] and not item["error"]
            ),
            fail_count=sum(1 for item in lookups if item["error"]),
            history_rows=history_rows,
        ),
    )


@app.post("/csv")
def download_csv(
    vehicle_text: str = Form(""),
    kind_label: str = Form("전체"),
    period_mode: str = Form("전체 기간"),
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    vehicle_nos = parse_vehicle_nos(vehicle_text)
    lookups, error, period_label = search_vehicles(
        vehicle_nos,
        kind_label=kind_label,
        period_mode=period_mode,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
    )
    if error and not lookups:
        return HTMLResponse(error, status_code=400)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = rows_to_csv(lookup_rows(lookups, period_label, kind_label))
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="침수차조회_{stamp}.csv"'},
    )
