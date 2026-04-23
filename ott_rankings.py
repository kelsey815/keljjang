"""OTT 플랫폼 랭킹 데이터 로더.

키노라이츠/각 플랫폼이 JS 렌더링 기반이라 90분 MVP에서는 수동 CSV를 사용한다.
data/ott_rankings.csv 에 platform, rank, title, content_type 형식으로 기록.
추후 확장: Playwright로 렌더링된 페이지에서 자동 수집.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

_CSV_PATH = Path(__file__).parent / "data" / "ott_rankings.csv"

PLATFORMS = ["쿠팡플레이", "티빙", "왓챠", "웨이브"]


@st.cache_data(ttl=300, show_spinner=False)
def load_ott_rankings() -> pd.DataFrame:
    if not _CSV_PATH.exists():
        return pd.DataFrame(columns=["platform", "rank", "title", "content_type", "note"])
    df = pd.read_csv(_CSV_PATH)
    df.columns = [c.strip() for c in df.columns]
    df = df[df["content_type"].astype(str).str.strip() == "영화"].copy()
    df["title"] = df["title"].astype(str).str.strip()
    df["platform"] = df["platform"].astype(str).str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce").astype("Int64")
    return df.dropna(subset=["rank", "title"]).reset_index(drop=True)
