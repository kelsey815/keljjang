"""OTT 랭킹 DataFrame에 네이버 메타(개봉일·관객수·감독·장르)를 붙인다.

매칭 로직:
1. 정규화된 title + year가 완전 일치하면 그 행.
2. 같은 title의 후보가 여러 개(동명작)이고 year가 비어 있거나 안 맞으면
   감독 정보로 대조해서 가장 가까운 걸 고른다.
3. 그래도 애매하면 title 단독 매칭(가장 최근 연도 우선).
"""
from __future__ import annotations

import re

import pandas as pd

_PUNCT_RE = re.compile(r"[\s:\-\(\)\[\]【】·,.!?~「」『』\"']+")


def normalize(title: str) -> str:
    if not isinstance(title, str):
        return ""
    return _PUNCT_RE.sub("", title.lower())


def attach_movie_meta(ott_df: pd.DataFrame, movies_df: pd.DataFrame) -> pd.DataFrame:
    out = ott_df.copy()
    for col in ("openDt", "audiCnt", "director", "genres"):
        out[col] = pd.NA if col in ("openDt", "audiCnt") else ""

    if movies_df.empty or ott_df.empty:
        return out

    mv = movies_df.copy()
    mv["_t"] = mv["title"].map(normalize)
    mv["_y"] = mv["year"].astype(str).fillna("")

    # title → 후보 인덱스들
    by_title: dict[str, list[int]] = {}
    for i, t in enumerate(mv["_t"]):
        by_title.setdefault(t, []).append(i)

    for i, row in out.iterrows():
        if row.get("kind") != "영화":
            continue
        t = normalize(row.get("title", ""))
        if not t:
            continue
        candidates = by_title.get(t, [])
        if not candidates:
            continue

        y = str(row.get("year") or "")
        chosen = None

        # 1. title + year 완전 일치
        for ci in candidates:
            if mv.at[ci, "_y"] == y and y:
                chosen = ci
                break

        # 2. 후보 여러 개 + year 안 맞음 → 가장 최근 연도 선호
        if chosen is None and len(candidates) > 1:
            years_avail = [(ci, mv.at[ci, "_y"]) for ci in candidates if mv.at[ci, "_y"].isdigit()]
            years_avail.sort(key=lambda x: int(x[1]), reverse=True)
            if years_avail:
                chosen = years_avail[0][0]

        # 3. fallback → 단일 후보
        if chosen is None:
            chosen = candidates[0]

        for col in ("openDt", "audiCnt", "director", "genres"):
            if col in mv.columns:
                v = mv.at[chosen, col]
                if pd.notna(v) and str(v).strip() not in ("", "nan"):
                    out.at[i, col] = v
    return out
