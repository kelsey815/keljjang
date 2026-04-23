# 박스오피스 × OTT 랭킹 비교 대시보드

KOBIS 박스오피스 데이터(2025년 이후 극장 개봉작)와 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 상위 랭킹을 매칭하여 비교하는 Streamlit 대시보드.

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# KOBIS 키 설정
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# .streamlit/secrets.toml 열어 발급받은 키 붙여넣기

streamlit run app.py
```

## OTT 랭킹 데이터 입력

`data/ott_rankings.csv` 파일을 엑셀/구글시트로 열어 각 플랫폼의 현재 Top N을 채워넣으면 대시보드에 바로 반영됩니다.

| 컬럼 | 설명 | 값 |
|---|---|---|
| platform | 플랫폼 이름 | 쿠팡플레이 / 티빙 / 왓챠 / 웨이브 |
| rank | 순위 | 1, 2, 3, ... |
| title | 플랫폼에 표시된 영화 제목 | 텍스트 |
| content_type | 콘텐츠 유형 | `영화` 만 집계됨 |
| note | 메모 (선택) | 자유 |

## Streamlit Cloud 배포

1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. "New app" → 이 레포 선택, main 브랜치, `app.py` 지정
3. "Advanced settings" → Secrets에 다음 한 줄 입력:

   ```
   KOBIS_API_KEY = "발급받은_키"
   ```

4. Deploy

## 확장 아이디어
- GitHub Actions로 OTT 랭킹 일일 자동 수집 (Playwright)
- 과거 스냅샷 축적 → "X일 연속 Top N" 지표
- 극장 흥행 대비 OTT 체류 순위 변화 추적
