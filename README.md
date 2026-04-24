# 박스오피스 × OTT 랭킹 비교 대시보드

쿠팡플레이 / 티빙 / 왓챠 / 웨이브 상위 랭킹에 오른 영화의 개봉일·누적 관객수(네이버 영화 메타 기준)를 비교하는 Streamlit 대시보드.

**공개 URL**: https://keljjang.streamlit.app

## 구조 (2단 분리)

| 역할 | 파일 | 환경 |
|---|---|---|
| 데이터 수집 (무겁다: Playwright) | `scripts/refresh_data.py` | **로컬에서만** 실행 |
| 대시보드 (가볍다: csv만 읽음) | `app.py`, `data_loader.py`, `matcher.py` | Streamlit Cloud |

Streamlit Cloud 무료 플랜은 Chromium을 안정적으로 못 돌려서, 수집은 로컬에서 돌리고 결과 CSV만 Git에 커밋해 배포에 태우는 방식.

### 데이터 소스
- **OTT 랭킹**: 키노라이츠 (`m.kinolights.com/ranking/<platform>`) — 플랫폼별 상위 순위 + 영화/시리즈 구분
- **영화 메타(개봉일·관객수)**: 네이버 모바일/PC 통합 검색의 영화 카드

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
├── data_loader.py         # data/*.csv 읽기
├── matcher.py             # OTT 랭킹에 영화 메타 붙이기
├── scripts/
│   └── refresh_data.py    # 키노라이츠 + 네이버 스크래핑 → csv 저장
├── data/                  # ott.csv, movies.csv, meta.json (git에 커밋됨)
└── requirements.txt       # 런타임은 pandas / streamlit 만
```

## 이후 확장
- GitHub Actions로 매일 자동 `refresh_data.py` → auto-commit → 자동 배포
- 네이버 "흥행" 상세 페이지까지 들어가서 관객수 커버율 올리기
- 플랫폼별 장르 분포 차트
- 스냅샷 축적으로 "N일 연속 Top X" 지표
