"""박스오피스 × OTT 랭킹 비교 대시보드.

KOBIS 박스오피스(2025년 이후 극장 개봉작)와 네 개 OTT 플랫폼 상위 랭킹을
자동 수집·매칭해 표·차트로 보여준다. Playwright 기반 자동 스크래핑.
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from kobis import collect_boxoffice_2025_plus
from matcher import match_ott_to_kobis
from ott_rankings import PLATFORMS, collect_ott_rankings

st.set_page_config(page_title="박스오피스 × OTT 랭킹", page_icon="🎬", layout="wide")

st.title("🎬 박스오피스 × OTT 랭킹 비교 대시보드")
st.caption(
    "KOBIS 2025년 이후 극장 개봉작 · 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 · "
    f"현재 시각 {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
)

# ---- 수동 갱신 버튼 ----
col_top_a, col_top_b = st.columns([1, 8])
if col_top_a.button("🔄 데이터 갱신", help="캐시를 지우고 최신 데이터를 다시 수집합니다."):
    st.cache_data.clear()
    st.rerun()
col_top_b.info(
    "🕐 첫 실행 또는 갱신 시 브라우저 자동화로 박스오피스·OTT 데이터를 수집합니다 (약 30초). "
    "수집된 데이터는 1시간(박스오피스) / 30분(OTT) 캐시됩니다."
)

# ---- 데이터 수집 ----
try:
    kobis_df = collect_boxoffice_2025_plus()
except Exception as e:  # noqa: BLE001
    st.error(f"KOBIS 수집 실패: {e}")
    st.stop()

try:
    ott_df = collect_ott_rankings(top_n=30)
except Exception as e:  # noqa: BLE001
    st.error(f"OTT 랭킹 수집 실패: {e}")
    st.stop()

merged = match_ott_to_kobis(ott_df, kobis_df)

# ---- 사이드바 필터 ----
st.sidebar.header("🔎 필터")
platform_list = list(PLATFORMS.keys())
selected_platforms = st.sidebar.multiselect(
    "플랫폼", platform_list, default=platform_list
)
rank_limit = st.sidebar.slider("플랫폼별 영화 Top N", 5, 30, 20)
only_matched = st.sidebar.checkbox(
    "KOBIS 매칭된 영화만 표시",
    value=False,
    help="체크하면 2025년 이후 극장 개봉이 확인된 영화만 남깁니다 (추천).",
)

view = merged[merged["platform"].isin(selected_platforms)].copy()
view = view[view["platform_movie_rank"] <= rank_limit]
if only_matched:
    view = view[view["movieNm"].notna()]

# ---- KPI ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("KOBIS 2025+ 영화 수", f"{len(kobis_df):,}")
c2.metric("OTT 랭킹 영화 수(영화만)", f"{len(ott_df):,}")
matched = view["movieNm"].notna().sum() if not view.empty else 0
c3.metric("현재 뷰 매칭 성공", f"{matched:,}")
c4.metric("선택 플랫폼", f"{len(selected_platforms)}개")

st.divider()

# ---- 섹션 1: 플랫폼별 상위 영화 ----
st.subheader("📊 플랫폼별 상위 영화 × 박스오피스 성과")

display_map = {
    "platform_movie_rank": "플랫폼 영화순위",
    "title": "OTT 표기명",
    "movieNm": "KOBIS 공식명",
    "openDt": "개봉일",
    "audiCnt": "누적관객수",
    "salesAmt": "누적매출액(원)",
    "year": "OTT표기연도",
    "match_score": "매칭점수",
}
for plat in selected_platforms:
    plat_df = view[view["platform"] == plat].sort_values("platform_movie_rank")
    if plat_df.empty:
        continue
    with st.expander(f"▶ {plat} ({len(plat_df)}편)", expanded=True):
        show = plat_df[list(display_map.keys())].rename(columns=display_map)
        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "누적관객수": st.column_config.NumberColumn(format="%d"),
                "누적매출액(원)": st.column_config.NumberColumn(format="%d"),
                "매칭점수": st.column_config.NumberColumn(
                    help="100 = KOBIS 영화명과 완전일치. 공란 = KOBIS 2025+ 목록에 없음 (시리즈·OTT 오리지널·2024년 이전 개봉 등)"
                ),
            },
        )

st.divider()

# ---- 섹션 2: 플랫폼 교차 영화 ----
st.subheader("🔀 두 개 이상 플랫폼 상위권에 동시 진입한 영화")
xref_base = view.dropna(subset=["movieNm"]).copy()
if xref_base.empty:
    st.info("현재 필터에서 KOBIS 매칭된 공통 영화가 없습니다.")
else:
    xref = (
        xref_base.groupby("movieNm")
        .agg(
            개봉일=("openDt", "first"),
            누적관객수=("audiCnt", "first"),
            누적매출액=("salesAmt", "first"),
            플랫폼수=("platform", "nunique"),
            플랫폼=("platform", lambda x: ", ".join(sorted(set(x)))),
            최고순위=("platform_movie_rank", "min"),
        )
        .query("플랫폼수 >= 2")
        .sort_values(["플랫폼수", "누적관객수"], ascending=[False, False])
        .reset_index()
        .rename(columns={"movieNm": "영화명"})
    )
    if xref.empty:
        st.info("두 개 이상 플랫폼 상위권에 동시 진입한 영화가 없습니다.")
    else:
        st.dataframe(
            xref,
            use_container_width=True,
            hide_index=True,
            column_config={
                "누적관객수": st.column_config.NumberColumn(format="%d"),
                "누적매출액": st.column_config.NumberColumn(format="%d"),
            },
        )

st.divider()

# ---- 섹션 3: 플랫폼별 관객수 합계 ----
st.subheader("💡 플랫폼별 상위권 영화들의 박스오피스 합계")
agg = (
    view.dropna(subset=["movieNm"])
    .groupby("platform")
    .agg(영화수=("movieNm", "nunique"), 누적관객수합=("audiCnt", "sum"), 누적매출액합=("salesAmt", "sum"))
    .reset_index()
    .rename(columns={"platform": "플랫폼"})
)
if agg.empty:
    st.info("집계할 매칭 데이터가 없습니다.")
else:
    st.dataframe(
        agg,
        use_container_width=True,
        hide_index=True,
        column_config={
            "누적관객수합": st.column_config.NumberColumn(format="%d"),
            "누적매출액합": st.column_config.NumberColumn(format="%d"),
        },
    )

st.divider()

# ---- 데이터 내려받기 + 상세 ----
csv = view.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "💾 현재 뷰 CSV 내려받기", csv, file_name="boxoffice_ott.csv", mime="text/csv"
)

with st.expander("🛠 수집 원본 데이터 보기"):
    st.write("**KOBIS 2025+ 박스오피스 (수집 원본)**")
    st.dataframe(kobis_df, hide_index=True)
    st.write("**OTT 랭킹 (영화만, 플랫폼별)**")
    st.dataframe(ott_df, hide_index=True)
    st.write("**매칭 실패 항목 — KOBIS 상위에 없는 영화 (OTT 오리지널·2024년 이전 개봉 등)**")
    st.dataframe(merged[merged["movieNm"].isna()], hide_index=True)
