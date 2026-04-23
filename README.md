# 박스오피스 × OTT 랭킹 비교 대시보드

KOBIS 연도별 박스오피스(2025년 이후 극장 개봉작)와 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 상위 랭킹을 비교하는 Streamlit 대시보드.

**공개 URL**: https://keljjang.streamlit.app

## 구조 (2단 분리)

| 역할 | 파일 | 환경 |
|---|---|---|
| 데이터 수집 (무겁다: Playwright) | `scripts/refresh_data.py` | **로컬에서만** 실행 |
| 대시보드 (가볍다: parquet만 읽음) | `app.py`, `data_loader.py`, `matcher.py` | Streamlit Cloud |

Streamlit Cloud 무료 플랜은 Chromium을 안정적으로 못 돌려서, 수집은 로컬에서 돌리고 결과 parquet만 Git에 커밋해 배포에 태우는 방식.

## 최초 세팅 (로컬, 1회)

```bash
cd ~/Projects/keljjang
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install playwright==1.48.0
python -m playwright install chromium
```

## 데이터 갱신 (로컬)

```bash
source .venv/bin/activate
python scripts/refresh_data.py
git add data/
git commit -m "refresh data"
git push
```

Push 후 Streamlit Cloud가 자동으로 다시 빌드·배포합니다 (30초~1분).

## 대시보드 로컬 실행

```bash
streamlit run app.py
```

`http://localhost:8501` 에서 확인.

## 파일

```
keljjang/
├── app.py                 # Streamlit UI
├── data_loader.py         # data/*.parquet 읽기
├── matcher.py             # 제목 정규화 + 유사도 매칭
├── scripts/
│   └── refresh_data.py    # KOBIS + 키노라이츠 스크래핑 → parquet 저장
├── data/                  # kobis.parquet, ott.parquet, meta.json (git에 커밋됨)
└── requirements.txt       # 런타임은 pandas / streamlit / rapidfuzz / pyarrow 만
```

## 이후 확장
- GitHub Actions로 매일 자동 `refresh_data.py` → auto-commit → 자동 배포
- KOBIS 영화상세(movieInfo) 장르 보강
- 플랫폼별 장르 분포 차트
- 스냅샷 축적으로 "N일 연속 Top X" 지표
