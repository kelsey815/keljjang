"""KOBIS 영화관 입장권 통합전산망(kobis.or.kr) 연도별 박스오피스 스크래핑.

API 키 없이 공개 통계 페이지(findYearlyBoxOfficeList.do)를 Playwright로 열어
2025 / 2026년 박스오피스 상위권 영화를 수집한다.
"""
from __future__ import annotations

import datetime as _dt
import re

import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright

_YEARLY_URL = "https://www.kobis.or.kr/kobis/business/stat/boxs/findYearlyBoxOfficeList.do"
_NUM_RE = re.compile(r"[^0-9]")


def _to_int(text: str) -> int:
    cleaned = _NUM_RE.sub("", text or "")
    return int(cleaned) if cleaned else 0


def _scrape_year(page, year: int) -> list[dict]:
    page.goto(_YEARLY_URL, timeout=30000)
    page.wait_for_selector("#sSearchYearFrom", timeout=15000)
    page.select_option("#sSearchYearFrom", str(year))
    page.evaluate("chkform('search')")
    try:
        page.wait_for_function(
            "document.querySelectorAll('table.tbl_comm tbody tr').length > 0 "
            "&& !document.querySelector('table.tbl_comm tbody tr td[colspan]')",
            timeout=20000,
        )
    except Exception:  # noqa: BLE001
        return []
    rows = page.query_selector_all("table.tbl_comm tbody tr")
    out = []
    for tr in rows:
        tds = [td.inner_text().strip() for td in tr.query_selector_all("td")]
        if len(tds) < 7:
            continue
        try:
            out.append(
                {
                    "year": year,
                    "rank": int(tds[0]),
                    "movieNm": tds[1],
                    "openDt": tds[2],
                    "salesAmt": _to_int(tds[3]),
                    "salesShare": tds[4],
                    "audiCnt": _to_int(tds[5]),
                    "screenCnt": _to_int(tds[6]),
                    "showCnt": _to_int(tds[7]) if len(tds) > 7 else 0,
                }
            )
        except ValueError:
            continue
    return out


@st.cache_data(ttl=3600, show_spinner="KOBIS에서 2025~2026년 박스오피스 수집 중 (약 10초)...")
def collect_boxoffice_2025_plus() -> pd.DataFrame:
    current_year = _dt.date.today().year
    years = [y for y in (2025, 2026) if y <= current_year]
    all_rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="Mozilla/5.0")
        page = ctx.new_page()
        for y in years:
            all_rows.extend(_scrape_year(page, y))
        browser.close()

    if not all_rows:
        return pd.DataFrame(
            columns=["movieNm", "openDt", "salesAmt", "audiCnt", "screenCnt", "showCnt", "rank_year"]
        )

    df = pd.DataFrame(all_rows)
    df["openDt"] = df["openDt"].fillna("")
    df = df[df["openDt"] >= "2025-01-01"].copy()
    df = (
        df.sort_values("audiCnt", ascending=False)
        .drop_duplicates(subset=["movieNm", "openDt"], keep="first")
        .reset_index(drop=True)
    )
    df["rank_year"] = df.groupby("year")["rank"].transform("min")
    return df
