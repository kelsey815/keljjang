"""박스오피스 × OTT 랭킹 비교 대시보드.

로컬에서 `python scripts/refresh_data.py` 로 수집된 data/*.csv 파일을 읽어
OTT 플랫폼 상위 랭킹 + 네이버 영화 메타(개봉일·관객수)를 보여준다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import PLATFORMS, load_meta, load_movies, load_ott, load_series
from matcher import attach_movie_meta

st.set_page_config(page_title="박스오피스 × OTT 랭킹", page_icon="🎬", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        min-width: 200px !important;
        max-width: 200px !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎬 박스오피스 × OTT 랭킹 비교 대시보드")
meta = load_meta()
refreshed = meta.get("refreshed_at", "—")
st.caption(
    "쿠팡플레이 / 티빙 / 왓챠 / 웨이브 OTT 상위 랭킹 · 네이버 영화 메타 · "
    f"데이터 갱신: {refreshed}"
)

movies_df = load_movies()
series_df = load_series()
ott_df = load_ott()

if ott_df.empty:
    st.error(
        "OTT 데이터 파일이 비어 있습니다. 로컬에서 `python scripts/refresh_data.py`를 "
        "실행해 data/*.csv 파일을 생성·커밋해 주세요."
    )
    st.stop()

merged = attach_movie_meta(ott_df, movies_df, series_df)

# ---- 사이드바 필터 ----
st.sidebar.header("🔎 필터")
st.sidebar.markdown("**플랫폼**")
selected_platforms = [
    plat for plat in PLATFORMS
    if st.sidebar.checkbox(plat, value=True, key=f"plat_{plat}")
]
st.sidebar.markdown("")
rank_limit = st.sidebar.slider("플랫폼별 Top N", 5, 30, 20)
only_movies = st.sidebar.checkbox(
    "영화만 표시",
    value=False,
    help="체크하면 시리즈(드라마·예능 등)를 숨깁니다.",
)

view = merged[merged["platform"].isin(selected_platforms)].copy()
view = view[view["platform_rank"] <= rank_limit]
if only_movies:
    view = view[view["kind"] == "영화"]


def _format_audi(n) -> str:
    if pd.isna(n):
        return ""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return ""
    if n >= 100_000_000:
        v = n / 100_000_000
        return f"{v:.1f}억" if v < 10 else f"{int(v)}억"
    if n >= 10_000:
        v = n / 10_000
        return f"{int(round(v))}만"
    return f"{n:,}"


def _format_opendt(row) -> str:
    od = row.get("openDt")
    if pd.isna(od) or str(od).strip() in ("", "nan", "NaT", "<NA>"):
        return "미개봉" if row.get("kind") == "영화" else "—"
    return str(od)


# ---- KPI ----
c1, c2, c3 = st.columns(3)
c1.metric("OTT 랭킹 콘텐츠", f"{len(ott_df):,}")
movie_view = view[view["kind"] == "영화"]
c2.metric("영화 수 (현재 뷰)", f"{len(movie_view):,}")
c3.metric("선택 플랫폼", f"{len(selected_platforms)}개")

st.divider()

# ---- 섹션 1: 플랫폼별 상위 ----
st.subheader("📊 플랫폼별 상위 랭킹")

display_map = {
    "platform_rank": "순위",
    "title": "OTT 표기명",
    "kind": "유형",
    "genres": "장르",
    "openDt": "개봉일",
    "audiCnt_display": "관객수",
    "year": "연도",
}
for plat in selected_platforms:
    plat_df = view[view["platform"] == plat].sort_values("platform_rank").copy()
    if plat_df.empty:
        continue
    with st.expander(f"▶ {plat} ({len(plat_df)}편)", expanded=True):
        plat_df["openDt"] = plat_df.apply(_format_opendt, axis=1)
        plat_df["audiCnt_display"] = plat_df["audiCnt"].map(_format_audi)
        show = plat_df[list(display_map.keys())].rename(columns=display_map)
        st.dataframe(show, use_container_width=True, hide_index=True)

st.divider()

# ---- 섹션 2: 플랫폼 교차 영화 ----
st.subheader("🔀 두 개 이상 플랫폼 상위권에 동시 진입한 영화")
xref_base = view[view["kind"] == "영화"].copy()
if xref_base.empty:
    st.info("현재 필터에서 영화가 없습니다.")
else:
    xref = (
        xref_base.groupby("title")
        .agg(
            개봉일=("openDt", "first"),
            관객수_raw=("audiCnt", "first"),
            플랫폼수=("platform", "nunique"),
            플랫폼=("platform", lambda x: ", ".join(sorted(set(x)))),
            최고순위=("platform_rank", "min"),
        )
        .query("플랫폼수 >= 2")
        .sort_values(["플랫폼수", "관객수_raw"], ascending=[False, False], na_position="last")
        .reset_index()
        .rename(columns={"title": "영화명"})
    )
    if xref.empty:
        st.info("두 개 이상 플랫폼 상위권에 동시 진입한 영화가 없습니다.")
    else:
        xref["관객수"] = xref["관객수_raw"].map(_format_audi)
        xref["개봉일"] = xref.apply(
            lambda r: r["개봉일"] if pd.notna(r["개봉일"]) and str(r["개봉일"]).strip() not in ("", "nan", "NaT", "<NA>") else "미개봉",
            axis=1,
        )
        xref = xref[["영화명", "플랫폼수", "플랫폼", "최고순위", "개봉일", "관객수"]]
        st.dataframe(xref, use_container_width=True, hide_index=True)

st.divider()

csv = view.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "💾 현재 뷰 CSV 내려받기", csv, file_name="ott_ranking.csv", mime="text/csv"
)

with st.expander("🛠 수집 원본 데이터 보기"):
    st.write("**OTT 랭킹 (영화+시리즈, 플랫폼별)**")
    st.dataframe(ott_df, hide_index=True)
    st.write("**네이버 영화 메타**")
    st.dataframe(movies_df, hide_index=True)
    st.write("**개봉일 미확인 영화 (네이버 매칭 실패)**")
    miss = merged[(merged["kind"] == "영화") & (merged["openDt"].isna())]
    st.dataframe(miss[["platform", "platform_rank", "title", "year"]], hide_index=True)
