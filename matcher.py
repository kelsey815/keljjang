"""KOBIS 박스오피스 DataFrame과 OTT 랭킹 DataFrame을 제목 기준으로 매칭."""
from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import fuzz, process

_PUNCT_RE = re.compile(r"[\s:\-\(\)\[\]【】·,.!?~「」『』\"']+")


def normalize(title: str) -> str:
    if not isinstance(title, str):
        return ""
    return _PUNCT_RE.sub("", title.lower())


def match_ott_to_kobis(
    ott_df: pd.DataFrame, kobis_df: pd.DataFrame, score_cutoff: int = 88
) -> pd.DataFrame:
    """OTT 랭킹 각 행에 KOBIS 박스오피스 컬럼을 붙여 반환. 매칭 실패 시 NaN."""
    kobis_cols = ["movieNm", "openDt", "audiCnt", "salesAmt", "screenCnt", "showCnt"]
    existing_cols = [c for c in kobis_cols if c in kobis_df.columns]

    if ott_df.empty:
        return ott_df.assign(**{c: pd.NA for c in existing_cols}, match_score=pd.NA)

    if kobis_df.empty:
        return ott_df.assign(**{c: pd.NA for c in existing_cols}, match_score=pd.NA)

    kobis_norm_map: dict[str, int] = {}
    for idx, name in enumerate(kobis_df["movieNm"].tolist()):
        key = normalize(name)
        if key and key not in kobis_norm_map:
            kobis_norm_map[key] = idx
    kobis_keys = list(kobis_norm_map.keys())

    matched_idx: list[int | None] = []
    scores: list[int | None] = []
    for title in ott_df["title"]:
        key = normalize(title)
        if not key:
            matched_idx.append(None)
            scores.append(None)
            continue
        if key in kobis_norm_map:
            matched_idx.append(kobis_norm_map[key])
            scores.append(100)
            continue
        result = process.extractOne(
            key, kobis_keys, scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )
        if result is None:
            matched_idx.append(None)
            scores.append(None)
        else:
            best_key, score, _ = result
            matched_idx.append(kobis_norm_map[best_key])
            scores.append(int(score))

    attach = pd.DataFrame(
        [
            kobis_df.iloc[i][existing_cols].to_dict()
            if i is not None
            else {c: None for c in existing_cols}
            for i in matched_idx
        ]
    )
    attach["match_score"] = scores
    merged = pd.concat(
        [ott_df.reset_index(drop=True), attach.reset_index(drop=True)], axis=1
    )
    return merged
