"""Streamlit 앱이 사용하는 정적 데이터 로더.

scripts/refresh_data.py 가 저장한 CSV 파일을 읽어 DataFrame으로 반환한다.
Playwright 등 무거운 의존성이 전혀 없다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"

PLATFORMS = ["쿠팡플레이", "티빙", "왓챠", "웨이브"]


@st.cache_data(ttl=600, show_spinner=False)
def load_movies() -> pd.DataFrame:
    """OTT 영화들의 네이버 메타 (제목·연도·개봉일·관객수)."""
    path = DATA / "movies.csv"
    if not path.exists():
        return pd.DataFrame(columns=["title", "year", "openDt", "audiCnt"])
    df = pd.read_csv(path)
    if "year" in df.columns:
        df["year"] = df["year"].astype(str)
    if "openDt" in df.columns:
        df["openDt"] = df["openDt"].astype("string")
    return df


@st.cache_data(ttl=600, show_spinner=False)
def load_ott() -> pd.DataFrame:
    path = DATA / "ott.csv"
    if not path.exists():
        return pd.DataFrame(
            columns=["platform", "rank", "title", "content_type", "kind", "year", "href", "platform_rank"]
        )
    df = pd.read_csv(path)
    if "year" in df.columns:
        df["year"] = df["year"].astype(str)
    return df


def load_meta() -> dict:
    path = DATA / "meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
