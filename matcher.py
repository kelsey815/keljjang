"""영화 제목 정규화 + KOBIS·OTT DataFrame 조인."""
from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import fuzz, process

_PUNCT_RE = re.compile(r"[\s:\-\(\)\[\]【】·,.!?~「」『』\"']+")


def normalize(title: str) -> str:
    if not isinstance(title, str):
        return ""
    t = title.lower()
    t = _PUNCT_RE.sub("", t)
    return t


def match_ott_to_kobis(
    ott_df: pd.DataFrame, kobis_df: pd.DataFrame, score_cutoff: int = 88
) -> pd.DataFrame:
    """OTT 랭킹 각 행에 대응하는 KOBIS 영화 정보를 붙여 반환.

    매칭되지 않은 OTT 영화는 KOBIS 컬럼이 NaN 상태로 남는다.
    """
    if kobis_df.empty or ott_df.empty:
        return ott_df.assign(
            movieCd=pd.NA, openDt=pd.NA, audiAcc=pd.NA, salesAcc=pd.NA, genre=pd.NA, directors=pd.NA
        )

    kobis_norm_map: dict[str, int] = {}
    for idx, name in enumerate(kobis_df["movieNm"].tolist()):
        key = normalize(name)
        if key and key not in kobis_norm_map:
            kobis_norm_map[key] = idx
    kobis_keys = list(kobis_norm_map.keys())

    matched_idx: list[int | None] = []
    match_scores: list[int | None] = []
    for title in ott_df["title"]:
        key = normalize(title)
        if not key:
            matched_idx.append(None)
            match_scores.append(None)
            continue
        if key in kobis_norm_map:
            matched_idx.append(kobis_norm_map[key])
            match_scores.append(100)
            continue
        result = process.extractOne(
            key, kobis_keys, scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )
        if result is None:
            matched_idx.append(None)
            match_scores.append(None)
        else:
            best_key, score, _ = result
            matched_idx.append(kobis_norm_map[best_key])
            match_scores.append(int(score))

    kobis_cols = ["movieCd", "movieNm", "openDt", "audiAcc", "salesAcc", "genre", "directors", "nationNm"]
    existing_cols = [c for c in kobis_cols if c in kobis_df.columns]
    attach = pd.DataFrame(
        [kobis_df.iloc[i][existing_cols].to_dict() if i is not None else {c: None for c in existing_cols}
         for i in matched_idx]
    )
    attach["match_score"] = match_scores
    merged = pd.concat([ott_df.reset_index(drop=True), attach.reset_index(drop=True)], axis=1)
    return merged
