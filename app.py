"""박스오피스 × OTT 랭킹 비교 대시보드.

로컬에서 `python scripts/refresh_data.py` 로 수집된 data/*.csv 파일을 읽어
KOBIS 박스오피스와 OTT 플랫폼 상위 랭킹을 매칭해 표·차트로 보여준다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import PLATFORMS, load_kobis, load_meta, load_ott
from matcher import match_ott_to_kobis

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
    "KOBIS 2025년 이후 극장 개봉작 · 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 · "
    f"데이터 갱신: {refreshed}"
)

kobis_df = load_kobis()
ott_df = load_ott()

if kobis_df.empty or ott_df.empty:
    st.error(
        "데이터 파일이 비어 있습니다. 로컬에서 `python scripts/refresh_data.py`를 "
        "실행해 data/*.csv 파일을 생성·커밋해 주세요."
    )
    st.stop()

merged = match_ott_to_kobis(ott_df, kobis_df)

# ---- 사이드바 필터 ----
st.sidebar.header("🔎 필터")
st.sidebar.markdown("**플랫폼**")
selected_platforms = [
    plat for plat in PLATFORMS
    if st.sidebar.checkbox(plat, value=True, key=f"plat_{plat}")
]
st.sidebar.markdown("")
rank_limit = st.sidebar.slider("플랫폼별 Top N", 5, 30, 20)
only_matched = st.sidebar.checkbox(
    "KOBIS 매칭된 영화만",
    value=False,
    help="체크하면 2025년 이후 극장 개봉이 확인된 영화만 남깁니다.",
)

view = merged[merged["platform"].isin(selected_platforms)].copy()
view = view[view["platform_rank"] <= rank_limit]
if only_matched:
    view = view[view["movieNm"].notna()]


def _format_opendt(row) -> str:
    od = row.get("openDt")
    if pd.isna(od) or str(od).strip() in ("", "nan", "NaT"):
        return "미개봉" if row.get("kind") == "영화" else "—"
    return str(od)

# ---- KPI ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("KOBIS 2025+ 영화 수", f"{len(kobis_df):,}")
c2.metric("OTT 랭킹 콘텐츠 수", f"{len(ott_df):,}")
matched = int(view["movieNm"].notna().sum()) if not view.empty else 0
c3.metric("현재 뷰 매칭 성공", f"{matched:,}")
c4.metric("선택 플랫폼", f"{len(selected_platforms)}개")

st.divider()

# ---- 섹션 1: 플랫폼별 상위 영화 ----
st.subheader("📊 플랫폼별 상위 영화 × 박스오피스 성과")

display_map = {
    "platform_rank": "순위",
    "title": "OTT 표기명",
    "kind": "유형",
    "openDt": "개봉일",
    "audiCnt": "누적관객수",
    "salesAmt": "누적매출액(원)",
    "year": "OTT표기연도",
}
for plat in selected_platforms:
    plat_df = view[view["platform"] == plat].sort_values("platform_rank").copy()
    if plat_df.empty:
        continue
    with st.expander(f"▶ {plat} ({len(plat_df)}편)", expanded=True):
        plat_df["openDt"] = plat_df.apply(_format_opendt, axis=1)
        show = plat_df[list(display_map.keys())].rename(columns=display_map)
        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "누적관객수": st.column_config.NumberColumn(format="localized"),
                "누적매출액(원)": st.column_config.NumberColumn(format="localized"),
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
            최고순위=("platform_rank", "min"),
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
                "누적관객수": st.column_config.NumberColumn(format="localized"),
                "누적매출액": st.column_config.NumberColumn(format="localized"),
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
            "누적관객수합": st.column_config.NumberColumn(format="localized"),
            "누적매출액합": st.column_config.NumberColumn(format="localized"),
        },
    )

st.divider()

csv = view.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "💾 현재 뷰 CSV 내려받기", csv, file_name="boxoffice_ott.csv", mime="text/csv"
)

with st.expander("🛠 수집 원본 데이터 보기"):
    st.write("**KOBIS 2025+ 박스오피스**")
    st.dataframe(kobis_df, hide_index=True)
    st.write("**OTT 랭킹 (영화+시리즈, 플랫폼별)**")
    st.dataframe(ott_df, hide_index=True)
    st.write("**매칭 실패 항목 — KOBIS 상위에 없는 영화·시리즈 (OTT 오리지널 등)**")
    st.dataframe(merged[merged["movieNm"].isna()], hide_index=True)
