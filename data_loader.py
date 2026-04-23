"""Streamlit 앱이 사용하는 정적 데이터 로더.

scripts/refresh_data.py가 저장한 parquet 파일을 읽어 DataFrame으로 반환한다.
Playwright·requests 등 수집 도구에 대한 의존성이 전혀 없다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"

PLATFORMS = ["쿠팡플레이", "티빙", "왓챠", "웨이브"]


@st.cache_data(ttl=600, show_spinner=False)
def load_kobis() -> pd.DataFrame:
    path = DATA / "kobis.parquet"
    if not path.exists():
        return pd.DataFrame(
            columns=["movieNm", "openDt", "salesAmt", "audiCnt", "screenCnt", "showCnt"]
        )
    return pd.read_parquet(path)


@st.cache_data(ttl=600, show_spinner=False)
def load_ott() -> pd.DataFrame:
    path = DATA / "ott.parquet"
    if not path.exists():
        return pd.DataFrame(
            columns=["platform", "rank", "title", "content_type", "year", "href", "platform_movie_rank"]
        )
    return pd.read_parquet(path)


def load_meta() -> dict:
    path = DATA / "meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
