"""OTT 랭킹 DataFrame에 네이버 메타(개봉일·관객수)를 제목+연도 기준으로 붙임."""
from __future__ import annotations

import re

import pandas as pd

_PUNCT_RE = re.compile(r"[\s:\-\(\)\[\]【】·,.!?~「」『』\"']+")


def normalize(title: str) -> str:
    if not isinstance(title, str):
        return ""
    return _PUNCT_RE.sub("", title.lower())


def attach_movie_meta(ott_df: pd.DataFrame, movies_df: pd.DataFrame) -> pd.DataFrame:
    """ott_df (영화+시리즈) 각 행에 openDt, audiCnt 컬럼을 붙인다.

    매칭 키: 정규화된 title + year (문자열). year 충돌시 title만으로 fallback.
    시리즈(kind != 영화)는 매칭 대상이 아니므로 NaN.
    """
    out = ott_df.copy()
    out["openDt"] = pd.NA
    out["audiCnt"] = pd.NA

    if movies_df.empty or ott_df.empty:
        return out

    mv = movies_df.copy()
    mv["_key_ty"] = mv["title"].map(normalize) + "|" + mv["year"].astype(str).fillna("")
    mv["_key_t"] = mv["title"].map(normalize)
    key_ty_map = dict(zip(mv["_key_ty"], mv.index))
    key_t_map = dict(zip(mv["_key_t"], mv.index))

    for i, row in out.iterrows():
        if row.get("kind") != "영화":
            continue
        t = normalize(row.get("title", ""))
        y = str(row.get("year") or "")
        idx = key_ty_map.get(f"{t}|{y}")
        if idx is None:
            idx = key_t_map.get(t)
        if idx is None:
            continue
        out.at[i, "openDt"] = mv.at[idx, "openDt"] if pd.notna(mv.at[idx, "openDt"]) else pd.NA
        out.at[i, "audiCnt"] = mv.at[idx, "audiCnt"] if pd.notna(mv.at[idx, "audiCnt"]) else pd.NA

    return out
