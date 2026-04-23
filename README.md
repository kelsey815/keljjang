# 박스오피스 × OTT 랭킹 비교 대시보드

KOBIS 연도별 박스오피스(2025년 이후 극장 개봉작)와 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 상위 랭킹을 **자동 수집**하여 한 화면에서 비교합니다. API 키 없이 공개 웹 페이지에서 Playwright로 수집.

## 실행 방법 (최초 1회)

아래 내용을 **터미널(맥에선 "터미널" 앱)** 에 그대로 복사해 붙여넣고 엔터를 누르세요.

```bash
cd ~/Projects/keljjang
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

마지막 줄(Chromium 다운로드)은 크롬 비슷한 브라우저를 프로그램이 조종할 수 있게 설치하는 단계입니다. 약 200MB 정도, 2~3분 소요.

## 대시보드 열기

터미널에서 프로젝트 폴더에 있는 상태로:

```bash
source .venv/bin/activate
streamlit run app.py
```

자동으로 브라우저가 열리면서 `http://localhost:8501` 주소가 표시됩니다. 첫 로딩 시 KOBIS + 4개 OTT 플랫폼 데이터를 수집하느라 **약 30초** 기다리면 됩니다. 이후엔 캐시로 즉시 표시됩니다.

### 데이터 갱신
대시보드 상단 **🔄 데이터 갱신** 버튼을 누르면 캐시를 비우고 새로 수집합니다.

### 같은 와이파이 다른 사람에게 보여주고 싶다면
`streamlit run app.py` 실행 후 표시되는 **Network URL**(예: `http://192.168.0.x:8501`)을 공유하면 같은 공유기 아래 누구나 접속 가능.

### 인터넷으로 외부에 공유하고 싶다면 (선택)
```bash
# 별도 터미널에서
ngrok http 8501
```
[ngrok](https://ngrok.com/download) 설치 후 무료 계정으로 로그인하면 `https://xxxx.ngrok-free.app` 임시 URL을 발급해줍니다. 컴퓨터를 켜둔 동안만 유효.

## 구조

```
keljjang/
├── app.py             # Streamlit 대시보드 (UI + 조립)
├── kobis.py           # KOBIS 연도별 박스오피스 Playwright 수집
├── ott_rankings.py    # 키노라이츠 4개 플랫폼 랭킹 Playwright 수집
├── matcher.py         # 제목 정규화 + 유사도 매칭
└── requirements.txt
```

## 내부 동작 요약
1. KOBIS `findYearlyBoxOfficeList.do`에서 2025·2026년 상위 박스오피스 목록 스크래핑
2. `m.kinolights.com/ranking/{platform}`에서 플랫폼별 랭킹 스크래핑 → 영화만 필터
3. 영화명 정규화 후 완전일치 → rapidfuzz 유사도 매칭(컷오프 88)
4. Streamlit UI에서 플랫폼별 표·교차영화·플랫폼별 박스오피스 합계 표시

## 이후 확장 아이디어
- 일일 자동 수집으로 스냅샷 축적 → "N일 연속 Top X" 지표
- KOBIS 영화상세(movieInfo)로 장르 보강
- 플랫폼별 장르 분포 차트
- 매칭 실패 영화 수동 매핑 테이블
