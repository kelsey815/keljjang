# 2026-04-24 · MVP 구축부터 네이버 메타 정확도 확보까지

> 최초 스캐폴드부터 공개 배포, 데이터 소스 전환, 정확도 보강까지 하루 동안의 작업 기록.
> 다음 작업자가 맥락을 이어받아 작업할 수 있도록 "무엇을 / 왜 / 어떻게 / 남은 과제" 순서로 정리.

## 프로젝트 한 줄 요약

**쿠팡플레이 / 티빙 / 왓챠 / 웨이브** 네 OTT의 상위 랭킹 콘텐츠에 **네이버 영화 메타(개봉일·관객수·장르·감독)** 를 붙여 보여주는 Streamlit 대시보드.

- 공개 URL: https://keljjang.streamlit.app
- 사용자: 콘텐츠 수급 담당자(watcha kelsey@watcha.com) — **비개발자**. 자동화 전제.
- 사용자의 핵심 니즈: OTT 상위권에 오른 콘텐츠의 **개봉시기·관객수 규모**로 인지도 판단 → "신작이 잘 올라왔구나" vs "10만짜리 구작이 갑자기 왜?" 분석.

---

## 아키텍처 (중요: 2단 분리)

Streamlit Cloud 무료 플랜이 Chromium·Akamai bypass 같은 무거운 스크래핑을 안정적으로 못 돌려서 **수집과 렌더링을 물리적으로 분리**했다.

```
┌─────────────── 로컬 (개발 머신) ───────────────┐
│ scripts/refresh_data.py                         │
│   - Playwright / requests 로 각 소스 스크래핑    │
│   - data/*.csv 로 저장                          │
│   - 주기적으로 수동 실행 후 git commit          │
└─────────────────────┬───────────────────────────┘
                      │ git push
┌─────────────────────▼───────────────────────────┐
│ Streamlit Cloud                                  │
│   app.py + data_loader.py + matcher.py          │
│   - data/*.csv 만 읽음 (Playwright 없음)         │
│   - pandas / streamlit / rapidfuzz 만 런타임    │
└──────────────────────────────────────────────────┘
```

런타임 의존성 (`requirements.txt`):
```
streamlit>=1.40,<2.0
pandas>=2.2,<3.0
rapidfuzz>=3.10,<4.0
```

Playwright, pyarrow, requests 등은 **수집 스크립트에만** 쓰이고 런타임에 안 들어간다. **절대 requirements.txt에 Playwright 넣지 말 것** (Streamlit Cloud에서 Chromium 못 띄움).

---

## 데이터 소스 현황 (이게 핵심)

네 플랫폼의 랭킹을 어디서 긁어오는지는 **플랫폼마다 다르다**. 한 번에 하나의 중립 출처(키노라이츠)로 통일하려 했으나 사용자가 "진짜 플랫폼 자체 랭킹" 을 요구해서 하이브리드가 됐다.

| 플랫폼 | 현재 출처 | 비고 |
|---|---|---|
| **웨이브** | 공식 API `apis.wavve.com/v1/catalog?broadcastid=MN503` (영화 TOP 20) + `CN2`(통합 TOP 20에서 시리즈만) | API 키가 URL에 노출돼 있어 request 로 바로 호출 가능. refer_id 접두어 `GMV_`=영화, 그 외=시리즈 |
| **왓챠** | 홈 `https://watcha.com/` 에서 Playwright로 "왓챠 TOP 20" 섹션 긁기 | **세션·시간별로 0~20편 가변**. retry 4회로 최선. `/contents/m...`=영화, `/t...`=시리즈. 현재 평균 14편 수집 |
| **쿠팡플레이** | `data/coupang_manual.csv` (수동 입력) | Akamai Bot Manager 차단 — 어떤 우회로도 뚫리지 않음. 사용자가 앱 "지금 인기있는 콘텐츠" 20편을 수동으로 업데이트 |
| **티빙** | 키노라이츠 `m.kinolights.com/ranking/tving` | 비로그인 홈이 `/onboarding` 으로 강제 리디렉션돼서 자체 랭킹 긁을 길이 없음 |

### 각 소스의 한계

- **웨이브**: CN2는 전부 시리즈, MN503은 전부 영화로 깔끔하게 나뉘지만 **영화 20 + 시리즈 20 = 40편**이 최대.
- **왓챠**: 가로 carousel 방식인데 `display:none` 대신 DOM에 다 있음에도 세션마다 상위 6개 아이템의 `img[alt]`·`innerText`가 lazy로 채워져 0~6개 skip 되는 현상. `_collect_watcha_once` 를 4번 반복해서 최대값 채택하지만 14편이 고정 패턴. 이전 탐색 세션에선 20편 다 나온 적 있어서 완전 불가능은 아님.
- **쿠팡플레이**: 사용자 의존. `data/coupang_manual.csv` 에 `rank,title,kind,note` 형식. 주 1회 갱신 필요.
- **티빙**: 키노라이츠 랭킹은 "OTT 통합 Top 100 중 티빙에서 볼 수 있는 작품" 필터된 뷰. **플랫폼 내부 순위 아님**. rank 값은 통합 기준이라 티빙 1위가 실제 티빙 인기 1위가 아님. UI에서는 `platform_rank` 로 재매겨서 1,2,3…로 보여줌.

### 키노라이츠 URL slug 주의

`https://m.kinolights.com/ranking/<slug>` 의 slug — 쿠팡플레이는 `coupang` 이다 (이전에 `coupangplay`로 써서 존재하지 않는 slug → 키노라이츠가 기본 통합 Top 100으로 조용히 fallback → 오염된 데이터 저장). 지금은 쿠팡 수동 전환해서 이 slug 안 씀. 티빙만 키노라이츠 유지.

---

## 네이버 메타 추출 (영화 카드 파싱의 정수)

영화 한 편에 대해 네이버 검색하면 페이지 위쪽에 **영화 지식 카드**가 뜬다. 거기서 개봉일·관객수·감독·장르를 긁는데, **본문 전체를 정규식으로 훑으면 뉴스 스니펫에 섞인 다른 영화 수치가 오염**된다 (예: "해리 포터" 검색 결과의 뉴스에 "'왕과 사는 남자' 누적 관객수 1,660만 명" 이 섞여서 그걸 해리포터 관객수로 잘못 저장).

정답 파싱 방식 (`scripts/refresh_data.py`):

### 감독·장르·개봉일 — `_extract_infolist()`

네이버 영화 카드의 **`.fds-infolist`** 클래스가 키-값 테이블(`감독 | 김지훈 | 언어 | 한국어 | 제작 | ... | 개봉일 | 2012년 12월 25일`). 이 블록의 inner_text를 줄 단위로 쪼개면 짝수 인덱스=키, 홀수 인덱스=값. 배우 섞임 문제가 여기서 해결됐다.

예전 문제: "타워" → 설경구(배우), "형" → 조정석(배우), "젠틀맨" → 주지훈(배우) ← 감독으로 잘못 들어감  
지금: 타워 → 김지훈 ✓, 형 → 권수경 ✓, 젠틀맨 → 가이 리치 ✓

### 관객수 — `_find_audi_movie_card()` + `_find_audi_with_title_context()`

네이버 영화 카드 본체의 또 다른 포맷: **"개봉 | 2015.03.05. | 평점 | 6.39 | 관객수 | 47만명"** 파이프 구분 키-값. 정규식 `_NAVER_CARD_AUDI_RE = r"관객수\s*[\|｜\n]+\s*([\d,\.]+)\s*(만|억)?\s*명"`.

**중요한 트릭**: 이 블록은 lazy render라 `page.goto` 후 `wait_for_timeout(2500)` + `scrollBy(0, 400)` + `wait_for_timeout(800)` 해야 DOM에 들어온다. 짧게 기다리면 body 텍스트에 "관객" 자체가 없다.

### variant(인터내셔널 컷, 감독판 등) 필터

영화 카드가 원작이 아니라 variant 페이지일 수 있다. 예: "파과" 검색하면 "**파과 인터내셔널 컷**" 카드가 먼저 뜸. 원작 파과(한국 2025, 55만 관객)가 아니라 인터내셔널 컷(4,561명)이 카드에 찍힘.

대응:
1. `_is_variant_result()`: body 상단 400자에 variant 키워드(`인터내셔널 / 감독판 / 확장판 / 리마스터링 / 재편집 / 무삭제`)가 있는데 검색 제목엔 없으면 → variant로 판정 → 카드값 버림
2. pkid 상세 링크 fallback: `_follow_pkid_detail_for_audi()` — 검색 결과의 `a[href*="pkid=68"]` (네이버 영화 상세 URL) 따라가서 재시도
3. 여전히 실패 시 `data/naver_url_overrides.csv` 수동 URL override. 현재 파과 하나 등록돼 있음: `os=36386323`

### 관객수 포맷 (app.py `_format_audi`)

- 1억 이상: `"1.2억"`, `"5억"`
- 1만 이상 10만 미만: `"4.5만"` (소수점 한 자리)
- 10만 이상 1000만 미만: `"47만"`, `"518만"` (정수)
- 1000만 이상: `"1,010만"` (천 단위 콤마)
- 1만 미만: `"0.4만"`, `"0.1만"` (사용자 요청 — "대략적인 규모감만")

---

## 주요 파일 구조

```
keljjang/
├── app.py                        # Streamlit UI
├── data_loader.py                # CSV → DataFrame (캐시 ttl=60s)
├── matcher.py                    # ott_df 에 movies_df·series_df 붙이기
├── scripts/
│   └── refresh_data.py           # 수집 진입점 (main)
├── data/
│   ├── ott.csv                   # 플랫폼 랭킹 (각 row: platform, rank, title, kind, platform_rank, source…)
│   ├── movies.csv                # 영화별 네이버 메타 (title, year, openDt, audiCnt, director, genres)
│   ├── series.csv                # 시리즈 메타 (title, year, director, genres) — 관객수 없음
│   ├── coupang_manual.csv        # 사용자 수동 쿠팡플레이 TOP 20
│   ├── naver_url_overrides.csv   # 제목→네이버 상세 URL 예외 매핑
│   └── meta.json                 # {"refreshed_at": "ISO timestamp"}
├── docs/worklogs/                # ← 여기 (이 문서)
├── requirements.txt              # streamlit / pandas / rapidfuzz 만
├── runtime.txt / packages.txt    # Streamlit Cloud Python/apt 설정
└── README.md
```

### `scripts/refresh_data.py` 흐름

```python
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ott_df = collect_ott(browser)              # ← 4 플랫폼 합쳐서 한 DF
        movies_df = collect_movies_from_naver(browser, ott_df)
        series_df = collect_series_from_naver(browser, ott_df)
    ott_df.to_csv("data/ott.csv")
    movies_df.to_csv("data/movies.csv")
    series_df.to_csv("data/series.csv")
```

`collect_ott` 내부:
- `collect_from_kinolights(browser)` — 티빙
- `collect_wavve_native()` — 웨이브 API (requests 사용, Playwright 불필요)
- `collect_watcha_native(browser)` — 왓챠 (retry wrapper → `_collect_watcha_once`)
- `collect_coupang_manual()` — CSV 로드

네이버 메타 수집:
- 영화: `_search_naver_movie(page, title, year, override_url=None)` — override 있으면 먼저 시도, 없으면 쿼리 4종(`"{t} {y} 영화"`, `"영화 {t} {y}"`, `"{t} 영화"`, `"영화 {t}"`) 순회
- 시리즈: `_search_naver_series(page, title, year)` — "제목 드라마" / "제목 예능" / 제목만. 관객수·개봉일은 수집 안 함(드라마엔 해당 없음). 장르·연출만.

### `matcher.py`

`attach_movie_meta(ott_df, movies_df, series_df) → DataFrame` — 각 OTT 행에 meta 컬럼 붙임.

매칭 로직: 제목 정규화(공백·괄호·문장부호 제거) + year로 1차 완전일치, 같은 title 후보 여럿이면 **최근 연도 우선**, 없으면 단일 후보 fallback.

시리즈 행은 `director`·`genres` 만 붙이고 `openDt`·`audiCnt` 는 NaN 유지.

---

## UI 요지 (app.py)

- 제목: 🏆 **플랫폼별 랭킹 비교 대시보드** (처음엔 "박스오피스 × OTT 랭킹 비교 대시보드" 였는데 박스오피스 의존 빠지면서 변경)
- 사이드바: 200px 고정 너비(CSS), 플랫폼 체크박스(세로), Top N 슬라이더(5~30), "영화만 표시" 체크박스
- 테이블 컬럼: **순위 / OTT 표기명 / 유형 / 장르 / 개봉일 / 관객수**
  - 과거에 있었다가 제거한 것: KOBIS 공식명, 매칭점수, 누적매출액, 감독, 연도
  - 감독은 `director` 컬럼으로 **내부엔 남아있음** (동명작 구분용). 표시만 안 함
- 개봉일 포맷팅 (`_format_opendt`):
  - 영화 + openDt 있으면 → 그대로
  - 영화 + openDt 없으면 → `"미개봉"`
  - 시리즈 → `"—"`
- 섹션:
  1. 플랫폼별 상위 랭킹 expander (플랫폼당 하나)
  2. 두 개 이상 플랫폼 동시 진입 영화
  3. CSV 다운로드
  4. "수집 원본 데이터 보기" expander

### 캐시 ttl

`@st.cache_data(ttl=60)` — 이전 10분 → 1분으로 축소. 재배포 시 캐시 즉시 만료되도록. Streamlit Cloud 재시작 시 어차피 캐시 날아가지만 보수적으로.

---

## 작업 타임라인 (커밋 기준, 오래된 → 최근)

1. `30d91bf` initial MVP — KOBIS yearly 박스오피스 + 키노라이츠, 통계청·BS4 조합
2. `97e4d98` Playwright 전환 — KOBIS·키노라이츠 둘 다 Playwright 로
3. `24ea642` Streamlit Cloud 초기 배포 시도 — `packages.txt` + runtime chromium install. 실패.
4. `00d9868` **2단 분리 결정** — 로컬 수집 / 클라우드 렌더. Playwright 클라우드에서 뺐다.
5. `643e39d` pyarrow 제거 — Python 3.14 wheel 없어서 빌드 실패. parquet → CSV.
6. `24ea…` UI 초안 — 좁은 사이드바, 숫자 콤마, 유형 컬럼
7. `16ee59f` **kinolights coupangplay → coupang slug 수정** (이전 한 달치 쿠팡 데이터가 통합 Top 100에 오염돼 있었음)
8. `66eced0` **데이터 소스 KOBIS → 네이버** 로 전환. 매출액 컬럼 제거. 관객수 "N만" 표기.
9. `db8e387` 웨이브 공식 API + 네이버 감독·장르 확장
10. `9ed6b30` 왓챠 TOP 20 자체 스크래핑 + 쿠팡 수동 + infolist 파싱 도입 (감독 정확도 급상승)
11. `c8eb59e` 감독 컬럼 UI 제거 (사용자 요청)
12. `fa22b6f` 연도 `2025.0 → 2025` 포맷 수정
13. `a6f47c7` **관객수를 네이버 카드 "관객수 \| XX만명" 필드에서만** 추출 — 과매칭 문제 근본 해결
14. `1b94fa8` cache ttl 10분 → 1분, timestamp 강조 표시
15. `3afbb0b` variant 필터 + `naver_url_overrides.csv` + 왓챠 retry + 숫자 포맷
16. `653b341` 제목 → 🏆 **플랫폼별 랭킹 비교 대시보드**, 연도 컬럼 제거

---

## 현재 커버율 (2026-04-24T21:34:55 수집 기준)

- OTT 영화 34편 (유니크)
  - 개봉일 27 (79%)
  - 관객수 24 (71%)
  - 감독 31 (91%)
  - 장르 31 (91%)
- OTT 시리즈 68편
  - 연출 19 (28%)
  - 장르 39 (57%)

관객수가 안 잡히는 영화 케이스:
- 외국 구작(`해리 포터와 마법사의 돌`) — 네이버 카드 자체가 없음. 공란 유지가 맞음.
- 최신 한국 영화(`사마귀`) — 카드는 있는데 "관객수" 필드가 실시간 미집계. 몇 주 지나면 채워짐.
- variant 문제(`파과`) — override CSV 로 개별 해결

시리즈 장르 부진 케이스:
- 중국 드라마(`영안여몽`·`백월범성`·`춘화염` 등 한자 음차 제목) — 네이버 카드 없음

---

## 작업하다 막혔던/배운 것 (다음 작업자가 놓치지 말 것)

### 절대 하지 말 것

- **Playwright 를 requirements.txt에 넣지 말 것** — Streamlit Cloud에서 Chromium 못 띄워서 무한 로딩.
- **pyarrow 넣지 말 것** — Python 3.14에 wheel 없어서 cmake 빌드 실패. CSV로도 충분.
- **KOBIS 공식 API 키 발급받자고 사용자에게 말하지 말 것** — 명시적으로 거부한 적 있음. 수동 개입 요구하는 건 원칙적으로 피할 것.
- **수치를 본문 전체 정규식으로 긁지 말 것** — 다른 영화 뉴스가 섞임. `.fds-infolist` 블록이나 "관객수 \|" 파이프 포맷처럼 **카드 고유 포맷**만 파싱.
- **왓챠 TOP 20에 대해 "확실히 20편 수집됨"이라고 장담하지 말 것** — 세션 불안정. 14편도 정상.
- **쿠팡플레이 우회에 시간 낭비하지 말 것** — Akamai Bot Manager는 playwright-stealth / 시스템 Chrome / 다양한 UA 다 뚫어봤는데 안 뚫림.

### 함정이었던 것

- **네이버 영화 카드는 lazy render** — `wait_for_timeout(2500)` + 스크롤 필요. 짧게 기다리면 body에 "관객" 단어 자체가 없음.
- **같은 쿼리도 세션별로 결과 다름** — 네이버도 왓챠도 A/B 노출 있음. 1회 실패를 실패로 단정하지 말고 retry 도입.
- **pandas가 빈 값 섞인 year를 float으로 읽음** — `"2025.0"` 같은 부작용. `_clean_year()` 에서 trailing `.0` 제거 처리.
- **variant 필터 window 폭** — 180자는 넓어서 주변 뉴스가 걸려옴. 60~80자가 적당.

### 사용자 소통 원칙 (auto-memory에 이미 저장됨)

- 한국어로 응답
- 기술 선택지 설명 시 비개발자 관점 (비유 우선, 장점·단점·추천안 명시)
- 원천 데이터 **수동 수집 요청 금지** — 쿠팡플레이만 예외적으로 사용자가 먼저 "내가 줄게" 제안
- 콘텐츠 수급 담당자 관점에서 결과 설명 (개봉시기·관객수로 인지도 판단하는 흐름)

---

## 남은 과제 (우선순위순)

### 높음

1. **왓챠 TOP 20 완주** — 현재 14편 고정. 시도해볼 것:
   - `_collect_watcha_once` 내에서 섹션 찾은 뒤 `img[alt]` 가 20개 모두 채워질 때까지 polling
   - 또는 왓챠도 쿠팡처럼 `data/watcha_manual.csv` 수동 fallback 지원
2. **시리즈 장르 커버율 개선 (현재 57%)** — 중국 드라마 제목은 네이버 카드 없으므로 근본 해결 어려움. `data/naver_url_overrides.csv` 를 시리즈까지 확장해서 개별 URL 수동 등록 가능하게.

### 중간

3. **GitHub Actions 자동 refresh** — 매일 자정에 `refresh_data.py` 실행 + auto-commit. 로컬 실행 부담 제거. Playwright 이미지는 GitHub Runner에서 돌릴 수 있음.
4. **관객수 정확도 검증 페이지** — "네이버에서 본 값과 다른 것들" 쉽게 체크할 수 있는 expander. 지금은 사용자가 직접 보고 알려줘야 발견.
5. **platform_rank 의미 툴팁** — 티빙 rank는 키노라이츠 통합 기준 재매김 / 웨이브는 웨이브 시청시간 / 왓챠·쿠팡은 플랫폼 자체 — 섞여있으니 사용자가 혼동할 수 있음. 각 플랫폼별 `source` 컬럼은 이미 ott.csv에 있으니 UI에 간단히 표시.

### 낮음

6. 스냅샷 축적 (`data/history/<date>/ott.csv`) — "N일 연속 Top X" 지표
7. 플랫폼별 장르 분포 차트
8. 배우 정보 → 동명작 구분 추가 (현재는 감독만)

---

## 핵심 커맨드 참고

```bash
# 로컬 데이터 갱신
cd ~/Projects/keljjang
source .venv/bin/activate
python scripts/refresh_data.py   # 네이버 영화 35편 × 3쿼리 + 시리즈 ~70편 + 왓챠 retry 4번 → 15~25분 소요
git add data/
git commit -m "refresh data"
git push

# 로컬 앱 실행
streamlit run app.py

# 최소 의존성 재설치 (런타임용)
pip install -r requirements.txt

# 스크래핑까지 포함 전체 (로컬 개발용)
pip install -r requirements.txt
pip install playwright==1.48.0 requests
python -m playwright install chromium
```

환경: Python 3.9 (로컬 venv) · Python 3.14.4 (Streamlit Cloud).

---

## 메모리 시스템 관련

`~/.claude/projects/-Users-kelsey-Projects-keljjang/memory/` 에 저장된 것:
- `user_role.md` — 사용자는 콘텐츠 수급 담당자, 비개발자, 자동화 전제
- `feedback_no_manual_data_collection.md` — 원천 데이터 수동 수집 요청 금지

**추가로 저장하면 좋을 것**:
- Akamai Bot Manager 차단 우회 시도해봤자 소용없음 (쿠팡플레이)
- 네이버 영화 카드 파싱 정답 패턴 (`.fds-infolist` + `"관객수 \| XX만명"` 파이프 포맷)
- 사용자가 시리즈도 네이버 메타 요청한 적 있음 (영화 + 시리즈 둘 다 메타 필요)
