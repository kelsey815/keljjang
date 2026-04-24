"""로컬에서 OTT 랭킹 + 네이버 영화/시리즈 메타를 수집해 data/*.csv 저장.

사용: `python scripts/refresh_data.py`

플랫폼별 랭킹 출처:
  - 웨이브  : 웨이브 공식 API (apis.wavve.com)  — 영화 TOP 20 + 시리즈 TOP 20
  - 왓챠    : 왓챠 홈 "왓챠 TOP 20" 섹션 (Playwright 렌더)
  - 쿠팡플레이 / 티빙 : 키노라이츠 m.kinolights.com (공식 웹 크롤링이 차단돼서 중립 집계 사용)

영화/시리즈 메타 (네이버 검색):
  - 영화 카드의 `.fds-infolist` 인포리스트 블록에서 감독·개봉일을 정확히 추출
  - 장르·관객수는 본문 텍스트 정규식으로 보완
  - 시리즈는 "드라마/예능" 쿼리로 검색해서 장르만 추출
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# 키노라이츠 아이템 본문에서 "영화 · 2025" 같은 메타 탐지
_META_RE = re.compile(r"(영화|드라마|예능|애니메이션|키즈|다큐멘터리|다큐)\s*·\s*(\d{4})")

# 네이버 본문 텍스트용 보조 정규식
_NAVER_OPEN_RE = re.compile(r"개봉\s*일?\s*(\d{4})[년\.\s]+(\d{1,2})[월\.\s]+(\d{1,2})")
_NAVER_AUDI_RE = re.compile(r"누적\s*관객수\s*(?:약\s*)?([\d,\.]+)\s*(만|억)?\s*명")
# "장르 : A, B, C" 형태 (시리즈에서 자주 등장)
_NAVER_GENRE_LOOSE_RE = re.compile(r"장르\s*[:·]?\s*([가-힣A-Za-z/·,\s]+?)(?=\s*(?:회차|편성|채널|기획|제작|개봉|러닝|감독|주연|출연|각본|국가|상영|평점|관람|등급|더보기|누적)\b|\n|$)")

# 인포리스트 블록에서 키-값 페어 추출 대상 키
_INFOLIST_KEYS = {"감독", "연출", "출연", "주연", "각본", "장르", "개봉일", "개봉",
                  "채널", "편성", "회차", "제작", "러닝타임", "국가", "기획",
                  "등급", "상영", "언어"}

KINOLIGHTS_PLATFORMS = {
    "티빙": "tving",
}

COUPANG_MANUAL_PATH = DATA / "coupang_manual.csv"
NAVER_URL_OVERRIDES_PATH = DATA / "naver_url_overrides.csv"


def _load_naver_url_overrides() -> dict[str, str]:
    """제목 → 네이버 영화 상세 URL 매핑. 일반 검색으로 원작 카드를 못 찾는 영화 대응용."""
    if not NAVER_URL_OVERRIDES_PATH.exists():
        return {}
    df = pd.read_csv(NAVER_URL_OVERRIDES_PATH)
    out = {}
    for _, r in df.iterrows():
        t = str(r.get("title") or "").strip()
        u = str(r.get("naver_url") or "").strip()
        if t and u:
            out[t] = u
    return out

WAVVE_APIKEY = "E5F3E0D30947AA5440556471321BB6D9"
WAVVE_COMMON = (
    f"apikey={WAVVE_APIKEY}&device=pc&partner=pooq&region=kor"
    f"&targetage=all&pooqzone=none&drm=wm"
)


# ---------- 키노라이츠 (쿠팡플레이 / 티빙) ----------

def collect_from_kinolights(browser) -> list[dict]:
    rows: list[dict] = []
    for plat_name, plat_key in KINOLIGHTS_PLATFORMS.items():
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
        )
        page = ctx.new_page()
        try:
            page.goto(f"https://m.kinolights.com/ranking/{plat_key}", timeout=30000)
            page.wait_for_selector("li.ranking-item", timeout=15000)
            for _ in range(6):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                page.wait_for_timeout(400)
            raw = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('li.ranking-item')).map(li => {
                    const img = li.querySelector('img[alt]');
                    const rank = li.querySelector('p.rank__number span');
                    const link = li.querySelector('a[href]');
                    return {
                        rank: rank ? rank.innerText.trim() : null,
                        title: img ? img.getAttribute('alt') : null,
                        href: link ? link.getAttribute('href') : null,
                        text: (li.innerText||'').replace(/\\s+/g,' ').trim(),
                    };
                })
                """
            )
        except Exception as e:  # noqa: BLE001
            print(f"[키노라이츠 {plat_name}] ERROR: {e}", file=sys.stderr)
            raw = []
        finally:
            ctx.close()
        for it in raw:
            try:
                rk = int(it["rank"])
            except (TypeError, ValueError):
                continue
            title = (it.get("title") or "").strip()
            if not title:
                continue
            m = _META_RE.search(it.get("text") or "")
            rows.append({
                "platform": plat_name,
                "rank": rk,
                "title": title,
                "content_type": m.group(1) if m else "",
                "year": m.group(2) if m else "",
                "href": it.get("href") or "",
                "source": "kinolights",
            })
    return rows


# ---------- 웨이브 자체 API ----------

def collect_wavve_native() -> list[dict]:
    headers = {"Referer": "https://www.wavve.com/", "Accept": "application/json"}
    urls = [
        ("movie", (
            "https://apis.wavve.com/v1/catalog?broadcastid=MN503"
            "&catalogType=ranking&category=movie&data=catalog&genre=svod"
            "&limit=20&mtype=svod&offset=0&orderby=viewtime&rankingType=top"
            f"&uicode=MN503&uiparent=GN51-MN503&uirank=22&uitype=band_98&isBand=true&{WAVVE_COMMON}"
        )),
        ("series", (
            "https://apis.wavve.com/v1/catalog?broadcastid=CN2"
            "&catalogType=ranking&data=catalog&genre=svod"
            "&limit=20&offset=0&orderby=viewtime&rankingType=top"
            f"&uicode=CN2&isBand=true&{WAVVE_COMMON}"
        )),
    ]
    rows: list[dict] = []
    for bucket, u in urls:
        try:
            resp = requests.get(u, headers=headers, timeout=15)
            ctxs = resp.json().get("data", {}).get("context_list", [])
        except Exception as e:  # noqa: BLE001
            print(f"[웨이브 native {bucket}] ERROR: {e}", file=sys.stderr)
            continue
        for c in ctxs:
            s = c.get("series", {}) or {}
            rid = s.get("refer_id") or ""
            title = (s.get("title") or "").strip()
            try:
                rk = int(c.get("additional_information", {}).get("rank") or 0)
            except (TypeError, ValueError):
                continue
            if not title or not rk:
                continue
            is_movie = rid.startswith("GMV_")
            if bucket == "movie" and not is_movie:
                continue
            if bucket == "series" and is_movie:
                continue
            rows.append({
                "platform": "웨이브",
                "rank": rk,
                "title": title,
                "content_type": "영화" if is_movie else "시리즈",
                "year": "",
                "href": (
                    f"https://www.wavve.com/player/movie?contentid={rid}"
                    if is_movie else f"https://www.wavve.com/player/vod?programid={rid}"
                ),
                "source": "wavve_api",
            })
    return rows


# ---------- 왓챠 홈 "왓챠 TOP 20" 섹션 ----------

def collect_watcha_native(browser, max_attempts: int = 4) -> list[dict]:
    """왓챠 홈은 세션·시간별로 TOP 20 섹션 노출이 불안정(0~20개 가변).
    여러 번 시도해서 가장 많이 수집된 결과 채택."""
    best: list[dict] = []
    for attempt in range(max_attempts):
        rows = _collect_watcha_once(browser)
        if len(rows) > len(best):
            best = rows
        if len(best) >= 18:
            break
    return best


def _collect_watcha_once(browser) -> list[dict]:
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="ko-KR",
    )
    page = ctx.new_page()
    rows: list[dict] = []
    try:
        page.goto("https://watcha.com/", timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        # 섹션 제목 등장할 때까지 천천히 스크롤 (lazy load 유도)
        hit = False
        for i in range(35):
            page.evaluate(f"window.scrollTo(0, {i*500})")
            page.wait_for_timeout(600)
            found = page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span'));
                return els.some(e => (e.innerText||'').trim() === '왓챠 TOP 20');
            }""")
            if found:
                hit = True
                break
        if not hit:
            print("[왓챠 native] '왓챠 TOP 20' 섹션 못 찾음", file=sys.stderr)
            return rows
        # 섹션 뷰포트에 맞추고 모든 아이템 alt/innerText 로드될 때까지 충분히 대기
        page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span'));
            const t = els.find(e => (e.innerText||'').trim() === '왓챠 TOP 20');
            if (t) t.scrollIntoView({behavior:'instant', block:'center'});
        }""")
        page.wait_for_timeout(3500)
        items = page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('h1,h2,h3,h4,div,span'));
            const titleEl = els.find(e => (e.innerText||'').trim() === '왓챠 TOP 20');
            if (!titleEl) return [];
            const pick = (c) => Array.from(c.querySelectorAll('a[href*="/contents/"]'))
                .slice(0, 22)
                .map((a, i) => {
                    const img = a.querySelector('img[alt]');
                    const alt = img ? img.getAttribute('alt') : '';
                    const txt = (a.innerText || '').replace(/\\s+/g, ' ').trim();
                    // alt 비어 있어도 innerText로 제목 확보 (lazy load 우회)
                    return { idx: i + 1, href: a.getAttribute('href'), alt: alt || txt };
                });
            let c = titleEl.parentElement;
            for (let d=0; d<15 && c; d++) {
                const links = c.querySelectorAll('a[href*="/contents/"]');
                if (links.length >= 18) return pick(c);
                c = c.parentElement;
            }
            c = titleEl.parentElement;
            for (let d=0; d<15 && c; d++) {
                const links = c.querySelectorAll('a[href*="/contents/"]');
                if (links.length >= 10) return pick(c);
                c = c.parentElement;
            }
            return [];
        }""")
        for it in items[:20]:
            title = (it.get("alt") or "").strip()
            href = it.get("href") or ""
            if not title:
                continue
            # /contents/m... 영화, /contents/t... 시리즈
            is_movie = False
            m = re.match(r"^/contents/([mt])", href)
            if m:
                is_movie = (m.group(1) == "m")
            rows.append({
                "platform": "왓챠",
                "rank": it["idx"],
                "title": title,
                "content_type": "영화" if is_movie else "시리즈",
                "year": "",
                "href": f"https://watcha.com{href}" if href else "",
                "source": "watcha_home",
            })
    except Exception as e:  # noqa: BLE001
        print(f"[왓챠 native] ERROR: {e}", file=sys.stderr)
    finally:
        ctx.close()
    return rows


# ---------- 쿠팡플레이 수동 목록 (Akamai 차단으로 스크래핑 불가) ----------

def collect_coupang_manual() -> list[dict]:
    """data/coupang_manual.csv 에 담긴 수동 TOP 20 목록을 읽어 OTT 행으로 변환."""
    if not COUPANG_MANUAL_PATH.exists():
        return []
    df = pd.read_csv(COUPANG_MANUAL_PATH)
    rows = []
    for _, r in df.iterrows():
        try:
            rk = int(r["rank"])
        except (KeyError, ValueError, TypeError):
            continue
        title = str(r.get("title") or "").strip()
        kind = str(r.get("kind") or "").strip() or "시리즈"
        if not title:
            continue
        rows.append({
            "platform": "쿠팡플레이",
            "rank": rk,
            "title": title,
            "content_type": "영화" if kind == "영화" else "시리즈",
            "year": "",
            "href": "",
            "source": "coupang_manual",
        })
    return rows


# ---------- 통합 ----------

def collect_ott(browser) -> pd.DataFrame:
    all_rows: list[dict] = []
    all_rows.extend(collect_from_kinolights(browser))
    all_rows.extend(collect_wavve_native())
    all_rows.extend(collect_watcha_native(browser))
    all_rows.extend(collect_coupang_manual())
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["kind"] = df["content_type"].apply(lambda x: "영화" if x == "영화" else "시리즈")
    df["platform_rank"] = df.groupby("platform")["rank"].rank(method="min").astype(int)
    return df.sort_values(["platform", "platform_rank"]).reset_index(drop=True)


# ---------- 네이버 메타 ----------

def _parse_audi(match: re.Match) -> int | None:
    try:
        val = float(match.group(1).replace(",", ""))
    except (ValueError, AttributeError):
        return None
    unit = match.group(2)
    if unit == "만":
        return int(val * 10_000)
    if unit == "억":
        return int(val * 100_000_000)
    return int(val)


def _split_genres(raw: str, max_n: int = 2) -> str:
    if not raw:
        return ""
    parts = re.split(r"[,/·]|\s{2,}", raw)
    out = []
    for p in parts:
        p = p.strip()
        if p and 0 < len(p) <= 15 and p not in out:
            out.append(p)
        if len(out) >= max_n:
            break
    return ", ".join(out)


def _extract_infolist(page) -> dict:
    """.fds-infolist 인포리스트 블록에서 키-값 페어 추출.

    네이버 영화/드라마 지식 카드의 인포박스를 정확히 파싱 — 배우 혼선 방지.
    """
    try:
        nodes = page.query_selector_all(".fds-infolist, [class*='infolist']")
    except Exception:  # noqa: BLE001
        return {}
    for n in nodes:
        try:
            text = n.inner_text() or ""
        except Exception:  # noqa: BLE001
            continue
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        pairs: dict = {}
        i = 0
        while i < len(lines) - 1:
            k = lines[i].rstrip(":：")
            v = lines[i + 1]
            if k in _INFOLIST_KEYS and v not in _INFOLIST_KEYS:
                pairs.setdefault(k, v)
                i += 2
            else:
                i += 1
        if pairs:
            return pairs
    return {}


# 네이버 영화 카드 본체의 키-값 페어 포맷
#   예: "개봉 | 2015.03.05. | 평점 | 6.39 | 관객수 | 47만명"
#   이 포맷은 영화 카드 안에만 있어서 뉴스·블로그에 섞이지 않음.
_NAVER_CARD_AUDI_RE = re.compile(r"관객수\s*[\|｜\n]+\s*([\d,\.]+)\s*(만|억)?\s*명")

# variant(버전) 키워드 — 제목엔 없는데 결과 페이지 상단에 나오면 다른 판본
_VARIANT_KW = ["인터내셔널", "감독판", "확장판", "리마스터링", "재편집", "무삭제"]


def _find_audi_movie_card(body: str) -> int | None:
    m = _NAVER_CARD_AUDI_RE.search(body)
    if m:
        return _parse_audi(m)
    return None


def _is_variant_result(body: str, title: str) -> bool:
    title_has = any(kw in title for kw in _VARIANT_KW)
    head = body[:400]  # 상단(페이지 제목 영역)에서 검사
    page_has = any(kw in head for kw in _VARIANT_KW)
    return page_has and not title_has


def _follow_pkid_detail_for_audi(page, search_page_url: str, title: str) -> int | None:
    """검색 결과의 pkid=68 영화 상세 링크로 이동해 관객수 재시도.

    "파과 인터내셔널 컷" 같은 variant 페이지로 빠지지 않도록, 이동 후 상단
    400자에 variant 키워드가 있고 원제목엔 없으면 건너뛰고 다음 후보로.
    """
    try:
        hrefs = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href*="pkid=68"]'))
                .map(a => a.getAttribute('href'))
                .filter((h,i,arr) => arr.indexOf(h) === i)
                .slice(0, 5)"""
        )
    except Exception:  # noqa: BLE001
        hrefs = []
    for href in hrefs:
        detail = urllib.parse.urljoin(search_page_url, href)
        try:
            page.goto(detail, timeout=15000)
            page.wait_for_timeout(2500)
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(700)
            body = page.inner_text("body")
        except Exception:  # noqa: BLE001
            continue
        if _is_variant_result(body, title):
            continue
        v = _find_audi_movie_card(body)
        if v is not None:
            return v
    return None


def _search_naver_movie(page, title: str, year: str, override_url: str | None = None) -> dict:
    best = {"openDt": None, "audiCnt": None, "director": "", "genres": ""}

    # override URL 우선 — 일반 검색으로 원작 카드를 못 찾는 영화 대응
    if override_url:
        try:
            page.goto(override_url, timeout=15000)
            page.wait_for_timeout(2500)
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(700)
            body = page.inner_text("body")
            info_il = _extract_infolist(page)
            d = info_il.get("감독") or info_il.get("연출") or ""
            if d:
                best["director"] = d.strip().split(",")[0].strip()
            od = info_il.get("개봉일") or info_il.get("개봉") or ""
            m = re.search(r"(\d{4})[년\-\.\s]+(\d{1,2})[월\-\.\s]+(\d{1,2})", od)
            if m:
                best["openDt"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                bm = _NAVER_OPEN_RE.search(body)
                if bm:
                    best["openDt"] = f"{bm.group(1)}-{int(bm.group(2)):02d}-{int(bm.group(3)):02d}"
            g = info_il.get("장르") or ""
            if not g:
                gm = _NAVER_GENRE_LOOSE_RE.search(body)
                if gm:
                    g = gm.group(1).strip()
            if g:
                best["genres"] = _split_genres(g, max_n=2)
            best["audiCnt"] = _find_audi_movie_card(body)
        except Exception:  # noqa: BLE001
            pass
        if all([best["openDt"], best["audiCnt"], best["director"], best["genres"]]):
            return best

    queries = []
    if year:
        queries.extend([f"{title} {year} 영화", f"영화 {title} {year}"])
    queries.extend([f"{title} 영화", f"영화 {title}"])
    for q in queries:
        url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(q)}"
        try:
            page.goto(url, timeout=15000)
            # 네이버 영화 카드는 lazy render라 충분히 대기 + 스크롤 필요
            page.wait_for_timeout(2500)
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            continue
        info = _extract_infolist(page)
        try:
            body = page.inner_text("body")
        except Exception:  # noqa: BLE001
            body = ""

        if not best["director"]:
            d = info.get("감독") or info.get("연출") or ""
            if d:
                best["director"] = d.strip().split(",")[0].strip()

        if best["openDt"] is None:
            od = info.get("개봉일") or info.get("개봉") or ""
            m = re.search(r"(\d{4})[년\-\.\s]+(\d{1,2})[월\-\.\s]+(\d{1,2})", od)
            if m:
                best["openDt"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                bm = _NAVER_OPEN_RE.search(body)
                if bm:
                    best["openDt"] = f"{bm.group(1)}-{int(bm.group(2)):02d}-{int(bm.group(3)):02d}"

        if not best["genres"]:
            g = info.get("장르") or ""
            if not g:
                gm = _NAVER_GENRE_LOOSE_RE.search(body)
                if gm:
                    g = gm.group(1).strip()
            if g:
                best["genres"] = _split_genres(g, max_n=2)

        # 관객수: 영화 카드에서 추출하되 variant 페이지(인터내셔널 컷 등)면 버림
        if best["audiCnt"] is None:
            card_audi = _find_audi_movie_card(body)
            if card_audi is not None and not _is_variant_result(body, title):
                best["audiCnt"] = card_audi

        # 카드 매치 실패하거나 variant여서 버린 경우 pkid 상세 링크 fallback
        if best["audiCnt"] is None:
            best["audiCnt"] = _follow_pkid_detail_for_audi(page, url, title)

        if all([best["openDt"], best["audiCnt"], best["director"], best["genres"]]):
            break

    return best


def _search_naver_series(page, title: str, year: str) -> dict:
    """시리즈용 — 장르만 추출 (개봉일·관객수 해당없음, 연출은 동명작 구분용)."""
    queries = []
    if year:
        queries.extend([f"{title} {year} 드라마", f"{title} {year} 예능", f"{title} {year}"])
    queries.extend([f"{title} 드라마", f"{title} 예능", title])
    best = {"director": "", "genres": ""}
    for q in queries:
        url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(q)}"
        try:
            page.goto(url, timeout=15000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            continue
        info = _extract_infolist(page)
        try:
            body = page.inner_text("body")
        except Exception:  # noqa: BLE001
            body = ""

        if not best["director"]:
            d = info.get("연출") or info.get("감독") or ""
            if d:
                best["director"] = d.strip().split(",")[0].strip()

        if not best["genres"]:
            g = info.get("장르") or ""
            if not g:
                gm = _NAVER_GENRE_LOOSE_RE.search(body)
                if gm:
                    g = gm.group(1).strip()
            if g:
                best["genres"] = _split_genres(g, max_n=2)

        if best["director"] and best["genres"]:
            break
    return best


def collect_movies_from_naver(browser, ott_df: pd.DataFrame) -> pd.DataFrame:
    if ott_df.empty:
        return pd.DataFrame(columns=["title", "year", "openDt", "audiCnt", "director", "genres"])
    movies = ott_df[ott_df["kind"] == "영화"][["title", "year"]].drop_duplicates().reset_index(drop=True)
    overrides = _load_naver_url_overrides()
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()
    rows = []
    for i, r in movies.iterrows():
        title = str(r["title"])
        year = str(r.get("year") or "").strip()
        info = _search_naver_movie(page, title, year, override_url=overrides.get(title))
        rows.append({
            "title": title, "year": year,
            "openDt": info["openDt"], "audiCnt": info["audiCnt"],
            "director": info["director"], "genres": info["genres"],
        })
        print(f"  M[{i+1}/{len(movies)}] {title} ({year}) → "
              f"개봉={info['openDt'] or '—'} · 관객={info['audiCnt'] or '—'} · "
              f"감독={info['director'] or '—'} · 장르={info['genres'] or '—'}", flush=True)
    ctx.close()
    return pd.DataFrame(rows)


def collect_series_from_naver(browser, ott_df: pd.DataFrame) -> pd.DataFrame:
    if ott_df.empty:
        return pd.DataFrame(columns=["title", "year", "director", "genres"])
    series = ott_df[ott_df["kind"] == "시리즈"][["title", "year"]].drop_duplicates().reset_index(drop=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()
    rows = []
    for i, r in series.iterrows():
        title = str(r["title"])
        year = str(r.get("year") or "").strip()
        info = _search_naver_series(page, title, year)
        rows.append({
            "title": title, "year": year,
            "director": info["director"], "genres": info["genres"],
        })
        print(f"  S[{i+1}/{len(series)}] {title} ({year}) → "
              f"연출={info['director'] or '—'} · 장르={info['genres'] or '—'}", flush=True)
    ctx.close()
    return pd.DataFrame(rows)


def main() -> None:
    now = _dt.datetime.now().isoformat(timespec="seconds")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("▶ OTT 랭킹 수집 중… (키노라이츠 2곳 + 웨이브 API + 왓챠 홈)", flush=True)
        ott_df = collect_ott(browser)
        if not ott_df.empty:
            print(f"  · {len(ott_df)}편 · 플랫폼별: {dict(ott_df['platform'].value_counts())}")
        print("▶ 네이버 영화 메타 수집 중…", flush=True)
        movies_df = collect_movies_from_naver(browser, ott_df)
        print("▶ 네이버 시리즈 메타 수집 중…", flush=True)
        series_df = collect_series_from_naver(browser, ott_df)
        browser.close()

    ott_df.to_csv(DATA / "ott.csv", index=False, encoding="utf-8")
    movies_df.to_csv(DATA / "movies.csv", index=False, encoding="utf-8")
    series_df.to_csv(DATA / "series.csv", index=False, encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps({"refreshed_at": now}, ensure_ascii=False))

    mgot_open = movies_df["openDt"].notna().sum() if not movies_df.empty else 0
    mgot_audi = movies_df["audiCnt"].notna().sum() if not movies_df.empty else 0
    mgot_dir = (movies_df["director"].astype(str).str.len() > 0).sum() if not movies_df.empty else 0
    mgot_gen = (movies_df["genres"].astype(str).str.len() > 0).sum() if not movies_df.empty else 0
    sgot_dir = (series_df["director"].astype(str).str.len() > 0).sum() if not series_df.empty else 0
    sgot_gen = (series_df["genres"].astype(str).str.len() > 0).sum() if not series_df.empty else 0
    print(
        f"✅ data/ 저장 완료 · {now}\n"
        f"  · 영화 {len(movies_df)}편 · 개봉일 {mgot_open} · 관객수 {mgot_audi} · "
        f"감독 {mgot_dir} · 장르 {mgot_gen}\n"
        f"  · 시리즈 {len(series_df)}편 · 연출 {sgot_dir} · 장르 {sgot_gen}"
    )


if __name__ == "__main__":
    main()
