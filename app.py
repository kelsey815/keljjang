"""박스오피스 × OTT 랭킹 비교 대시보드.

KOBIS 박스오피스(2025년 이후 극장 개봉작) 데이터와 네 개 OTT 플랫폼 상위 랭킹을
매칭하여 표·차트로 보여준다.
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from kobis import collect_2025_boxoffice
from matcher import match_ott_to_kobis
from ott_rankings import PLATFORMS, load_ott_rankings

st.set_page_config(page_title="박스오피스 × OTT 랭킹", page_icon="🎬", layout="wide")

st.title("🎬 박스오피스 × OTT 랭킹 비교 대시보드")
st.caption(
    f"KOBIS 2025년 이후 극장 개봉작 · 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 상위 랭킹 · "
    f"데이터 갱신: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
)

# ---- API 키 체크 ----
api_key = st.secrets.get("KOBIS_API_KEY") if hasattr(st, "secrets") else None
if not api_key:
    st.error(
        "KOBIS API 키가 설정되지 않았습니다.\n\n"
        "로컬 실행: `.streamlit/secrets.toml` 파일에 `KOBIS_API_KEY = \"...\"` 추가.\n"
        "Streamlit Cloud 배포: 앱 Settings → Secrets 메뉴에 동일하게 입력."
    )
    st.stop()

# ---- 데이터 로드 ----
try:
    kobis_df = collect_2025_boxoffice(api_key)
except Exception as e:  # noqa: BLE001
    st.error(f"KOBIS 데이터 수집 실패: {e}")
    st.stop()

ott_df = load_ott_rankings()

if ott_df.empty:
    st.warning(
        "OTT 랭킹 CSV가 비어 있습니다. `data/ott_rankings.csv` 파일에 "
        "각 플랫폼 상위 랭킹을 입력하면 즉시 반영됩니다."
    )

merged = match_ott_to_kobis(ott_df, kobis_df)

# ---- 사이드바 필터 ----
st.sidebar.header("🔎 필터")
selected_platforms = st.sidebar.multiselect(
    "플랫폼", PLATFORMS, default=PLATFORMS
)

all_genres = sorted(
    {g.strip() for genres in merged["genre"].dropna() for g in str(genres).split(",") if g.strip()}
)
selected_genres = st.sidebar.multiselect("장르(KOBIS 기준)", all_genres, default=all_genres)

min_rank = st.sidebar.slider("순위 상한 (Top N)", 5, 50, 20)

# ---- 필터 적용 ----
view = merged[merged["platform"].isin(selected_platforms)].copy()
view = view[view["rank"].astype("Int64") <= min_rank]
if selected_genres:
    view = view[
        view["genre"].fillna("").apply(
            lambda g: any(sel in g for sel in selected_genres)
        )
    ]

# ---- KPI ----
col1, col2, col3, col4 = st.columns(4)
col1.metric("KOBIS 2025+ 영화 수", f"{len(kobis_df):,}")
col2.metric("OTT 랭킹 영화 수", f"{len(ott_df):,}")
matched = view["movieCd"].notna().sum()
col3.metric("KOBIS 매칭 성공", f"{matched:,}")
col4.metric("선택 플랫폼", f"{len(selected_platforms)}개")

st.divider()

# ---- 섹션 1: 플랫폼별 상위 영화 표 ----
st.subheader("📊 플랫폼별 상위 영화 × 박스오피스 성과")

display_cols_map = {
    "rank": "순위",
    "title": "OTT 제목",
    "movieNm": "KOBIS 공식명",
    "genre": "장르",
    "openDt": "개봉일",
    "audiAcc": "누적관객수",
    "salesAcc": "누적매출액(원)",
    "directors": "감독",
    "match_score": "매칭점수",
}

for plat in selected_platforms:
    plat_df = view[view["platform"] == plat].sort_values("rank")
    if plat_df.empty:
        continue
    st.markdown(f"#### {plat}")
    show = plat_df[list(display_cols_map.keys())].rename(columns=display_cols_map)
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "누적관객수": st.column_config.NumberColumn(format="%d"),
            "누적매출액(원)": st.column_config.NumberColumn(format="%d"),
            "매칭점수": st.column_config.NumberColumn(help="100=완전일치, 낮을수록 제목이 다름"),
        },
    )

st.divider()

# ---- 섹션 2: 장르 분포 ----
st.subheader("🎭 플랫폼별 장르 분포")

genre_rows = []
for _, row in view.iterrows():
    genres = str(row.get("genre") or "").split(",")
    for g in genres:
        g = g.strip()
        if g:
            genre_rows.append({"platform": row["platform"], "genre": g})

if genre_rows:
    genre_df = pd.DataFrame(genre_rows)
    pivot = (
        genre_df.groupby(["genre", "platform"]).size().unstack(fill_value=0)
    )
    st.bar_chart(pivot, use_container_width=True)
else:
    st.info("장르 정보가 있는 매칭 결과가 없습니다. KOBIS 매칭 성공 건이 필요합니다.")

st.divider()

# ---- 섹션 3: 플랫폼 교차 영화 ----
st.subheader("🔀 두 개 이상 플랫폼 상위권 공통 영화")

xref = (
    view.dropna(subset=["movieCd"])
    .groupby("movieCd")
    .agg(
        영화명=("movieNm", "first"),
        장르=("genre", "first"),
        개봉일=("openDt", "first"),
        누적관객수=("audiAcc", "first"),
        누적매출액=("salesAcc", "first"),
        플랫폼수=("platform", "nunique"),
        플랫폼=("platform", lambda x: ", ".join(sorted(set(x)))),
    )
    .query("플랫폼수 >= 2")
    .sort_values(["플랫폼수", "누적관객수"], ascending=[False, False])
    .reset_index(drop=True)
)

if xref.empty:
    st.info("현재 필터에서 2개 이상 플랫폼에 동시에 오른 영화가 없습니다.")
else:
    st.dataframe(xref, use_container_width=True, hide_index=True)

st.divider()

# ---- 다운로드 ----
st.subheader("💾 데이터 내려받기")
csv_bytes = view.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "현재 뷰 CSV 다운로드", csv_bytes, file_name="boxoffice_ott_view.csv", mime="text/csv"
)

with st.expander("🛠 데이터 상태 상세 보기"):
    st.write("**KOBIS 수집 (상위 20개 미리보기)**")
    st.dataframe(kobis_df.head(20), hide_index=True)
    st.write("**OTT 랭킹 원본**")
    st.dataframe(ott_df, hide_index=True)
    st.write("**매칭 실패 항목 (제목이 KOBIS에 없거나 2025년 이전 개봉)**")
    st.dataframe(merged[merged["movieCd"].isna()], hide_index=True)
