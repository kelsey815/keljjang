"""OTT 랭킹에 네이버 메타(영화: 개봉일·관객수·감독·장르, 시리즈: 연출·장르)를 붙인다.

매칭 로직:
1. 정규화된 title + year 완전 일치 우선
2. 후보 여럿이면 최근 연도 선호
3. 단일 후보 fallback
"""
from __future__ import annotations

import re

import pandas as pd

_PUNCT_RE = re.compile(r"[\s:\-\(\)\[\]【】·,.!?~「」『』\"']+")


def normalize(title: str) -> str:
    if not isinstance(title, str):
        return ""
    return _PUNCT_RE.sub("", title.lower())


def _pick_candidate(by_title: dict, t: str, y: str, mv: pd.DataFrame) -> int | None:
    candidates = by_title.get(t, [])
    if not candidates:
        return None
    for ci in candidates:
        if str(mv.at[ci, "year"]) == y and y:
            return ci
    if len(candidates) > 1:
        ys = [(ci, str(mv.at[ci, "year"])) for ci in candidates if str(mv.at[ci, "year"]).isdigit()]
        ys.sort(key=lambda x: int(x[1]), reverse=True)
        if ys:
            return ys[0][0]
    return candidates[0]


def attach_movie_meta(
    ott_df: pd.DataFrame,
    movies_df: pd.DataFrame,
    series_df: pd.DataFrame,
) -> pd.DataFrame:
    out = ott_df.copy()
    out["openDt"] = pd.NA
    out["audiCnt"] = pd.NA
    out["director"] = ""
    out["genres"] = ""

    if ott_df.empty:
        return out

    # 영화 매칭
    if not movies_df.empty:
        mv = movies_df.reset_index(drop=True).copy()
        mv["_t"] = mv["title"].map(normalize)
        by_t_mv: dict[str, list[int]] = {}
        for i, t in enumerate(mv["_t"]):
            by_t_mv.setdefault(t, []).append(i)
        for i, row in out.iterrows():
            if row.get("kind") != "영화":
                continue
            t = normalize(row.get("title", ""))
            if not t:
                continue
            ci = _pick_candidate(by_t_mv, t, str(row.get("year") or ""), mv)
            if ci is None:
                continue
            for col in ("openDt", "audiCnt", "director", "genres"):
                if col in mv.columns:
                    v = mv.at[ci, col]
                    if pd.notna(v) and str(v).strip() not in ("", "nan"):
                        out.at[i, col] = v

    # 시리즈 매칭 (장르·연출만)
    if not series_df.empty:
        sr = series_df.reset_index(drop=True).copy()
        sr["_t"] = sr["title"].map(normalize)
        by_t_sr: dict[str, list[int]] = {}
        for i, t in enumerate(sr["_t"]):
            by_t_sr.setdefault(t, []).append(i)
        for i, row in out.iterrows():
            if row.get("kind") != "시리즈":
                continue
            t = normalize(row.get("title", ""))
            if not t:
                continue
            ci = _pick_candidate(by_t_sr, t, str(row.get("year") or ""), sr)
            if ci is None:
                continue
            for col in ("director", "genres"):
                if col in sr.columns:
                    v = sr.at[ci, col]
                    if pd.notna(v) and str(v).strip() not in ("", "nan"):
                        out.at[i, col] = v

    return out
