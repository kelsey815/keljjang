"""KOBIS 오픈 API 호출 모듈.

weeklyBoxOffice로 2025-01-01부터 오늘까지 박스오피스 진입 영화를 수집하고,
movieInfo로 장르 등 메타데이터를 보강한다.
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

import pandas as pd
import requests
import streamlit as st

_WEEKLY_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json"
_MOVIE_INFO_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json"

_START_DATE = _dt.date(2025, 1, 1)


def _mondays(start: _dt.date, end: _dt.date) -> Iterable[_dt.date]:
    days_since_monday = start.weekday()
    cur = start - _dt.timedelta(days=days_since_monday)
    while cur <= end:
        yield cur
        cur += _dt.timedelta(days=7)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weekly_boxoffice(api_key: str, target_dt: str) -> list[dict]:
    """target_dt 형식 YYYYMMDD. 주간 박스오피스 상위 10개 반환."""
    params = {
        "key": api_key,
        "targetDt": target_dt,
        "weekGb": "0",
    }
    resp = requests.get(_WEEKLY_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("boxOfficeResult", {}).get("weeklyBoxOfficeList", [])


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_movie_info(api_key: str, movie_cd: str) -> dict:
    params = {"key": api_key, "movieCd": movie_cd}
    resp = requests.get(_MOVIE_INFO_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("movieInfoResult", {}).get("movieInfo", {})


@st.cache_data(ttl=3600, show_spinner="KOBIS에서 2025년 이후 박스오피스 데이터 수집 중...")
def collect_2025_boxoffice(api_key: str) -> pd.DataFrame:
    """2025-01-01부터 오늘까지 주간 박스오피스에 올라온 영화들을 모아 DataFrame으로 반환."""
    today = _dt.date.today()
    movies: dict[str, dict] = {}

    for monday in _mondays(_START_DATE, today):
        target = (monday + _dt.timedelta(days=6)).strftime("%Y%m%d")
        try:
            entries = fetch_weekly_boxoffice(api_key, target)
        except requests.HTTPError:
            continue
        for e in entries:
            code = e.get("movieCd")
            if not code:
                continue
            open_dt = e.get("openDt", "").replace("-", "")
            if open_dt and open_dt < "20250101":
                continue
            prev = movies.get(code)
            audi_acc = int(e.get("audiAcc") or 0)
            sales_acc = int(e.get("salesAcc") or 0)
            if prev is None or audi_acc > prev["audiAcc"]:
                movies[code] = {
                    "movieCd": code,
                    "movieNm": e.get("movieNm", ""),
                    "openDt": e.get("openDt", ""),
                    "audiAcc": audi_acc,
                    "salesAcc": sales_acc,
                }

    if not movies:
        return pd.DataFrame(
            columns=["movieCd", "movieNm", "openDt", "audiAcc", "salesAcc", "genre", "directors", "nationNm"]
        )

    df = pd.DataFrame(list(movies.values()))
    genres, directors, nations = [], [], []
    for code in df["movieCd"]:
        try:
            info = fetch_movie_info(api_key, code)
        except requests.HTTPError:
            info = {}
        genre_list = info.get("genres") or []
        directors_list = info.get("directors") or []
        nation_list = info.get("nations") or []
        genres.append(", ".join(g.get("genreNm", "") for g in genre_list) or "미상")
        directors.append(", ".join(d.get("peopleNm", "") for d in directors_list))
        nations.append(", ".join(n.get("nationNm", "") for n in nation_list))
    df["genre"] = genres
    df["directors"] = directors
    df["nationNm"] = nations
    df = df.sort_values("audiAcc", ascending=False).reset_index(drop=True)
    return df
