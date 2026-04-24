"""로컬에서 OTT 랭킹 + 네이버 영화 메타를 수집해 data/*.csv 저장.

사용: `python scripts/refresh_data.py`

플랫폼별 랭킹 출처:
  - 쿠팡플레이 / 티빙 / 왓챠  → 키노라이츠 m.kinolights.com (공식 사이트 비로그인 크롤링이
    기술·법적으로 막혀 있어 중립 집계 사이트를 사용)
  - 웨이브                    → 웨이브 공식 API (실제 시청시간 기준 TOP 20)

영화 메타:
  - 네이버 모바일/PC 통합 검색의 영화 카드 텍스트에서
    개봉일 · 누적 관객수 · 감독 · 장르 최대 2개를 추출
  - 감독은 동명작 구분에 사용, 장르는 UI 표시용
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

_META_RE = re.compile(r"(영화|드라마|예능|애니메이션|키즈|다큐멘터리|다큐)\s*·\s*(\d{4})")
_NAVER_OPEN_RE = re.compile(r"개봉\s*일?\s*(\d{4})[년\.\s]+(\d{1,2})[월\.\s]+(\d{1,2})")
_NAVER_AUDI_RE = re.compile(r"누적\s*관객수\s*(?:약\s*)?([\d,\.]+)\s*(만|억)?\s*명")
# 감독 / 장르 / 주연 / 각본 등에서 문자열 끊는 경계 키워드
_META_BREAK = r"(?=\s*(?:감독|주연|출연|각본|제작|장르|국가|상영|등급|개봉|누적|손익|주요|OTT|관객|더보기|러닝타임|평점|관람|배급)\b|$|\n)"
_NAVER_DIR_RE = re.compile(r"감독\s+([가-힣A-Za-z·,\s]+?)" + _META_BREAK)
_NAVER_GENRE_RE = re.compile(r"장르\s+([가-힣A-Za-z/·,\s]+?)" + _META_BREAK)

KINOLIGHTS_PLATFORMS = {
    "쿠팡플레이": "coupang",
    "티빙": "tving",
    "왓챠": "watcha",
}

WAVVE_APIKEY = "E5F3E0D30947AA5440556471321BB6D9"
WAVVE_COMMON = (
    f"apikey={WAVVE_APIKEY}&device=pc&partner=pooq&region=kor"
    f"&targetage=all&pooqzone=none&drm=wm"
)


# ---------- 키노라이츠 (쿠팡플레이 / 티빙 / 왓챠) ----------

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
            ctype = m.group(1) if m else ""
            rows.append({
                "platform": plat_name,
                "rank": rk,
                "title": title,
                "content_type": ctype,
                "year": m.group(2) if m else "",
                "href": it.get("href") or "",
                "source": "kinolights",
            })
    return rows


# ---------- 웨이브 자체 API ----------

def collect_wavve_native() -> list[dict]:
    """MN503 영화 TOP 20 + CN2 통합 TOP 20 (시리즈만 추출)."""
    headers = {"Referer": "https://www.wavve.com/", "Accept": "application/json"}
    urls = [
        # 영화 TOP 20
        ("movie", (
            "https://apis.wavve.com/v1/catalog?broadcastid=MN503"
            "&catalogType=ranking&category=movie&data=catalog&genre=svod"
            "&limit=20&mtype=svod&offset=0&orderby=viewtime&rankingType=top"
            f"&uicode=MN503&uiparent=GN51-MN503&uirank=22&uitype=band_98&isBand=true&{WAVVE_COMMON}"
        )),
        # 통합 TOP 20 (시리즈만 추출)
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


# ---------- 통합 ----------

def collect_ott(browser) -> pd.DataFrame:
    all_rows: list[dict] = []
    all_rows.extend(collect_from_kinolights(browser))
    all_rows.extend(collect_wavve_native())
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


def _clean_list(raw: str, max_n: int) -> list[str]:
    """'박찬욱, 이정재' 같은 콤마 구분 문자열을 리스트로."""
    if not raw:
        return []
    # 가장 흔한 구분자들로 쪼개기
    parts = re.split(r"[,/·]|\s{2,}", raw)
    out = []
    for p in parts:
        p = p.strip()
        if p and len(p) <= 20 and p not in out:
            out.append(p)
        if len(out) >= max_n:
            break
    return out


def _search_naver(page, title: str, year: str) -> dict:
    queries = []
    if year:
        queries.extend([f"{title} {year} 영화", f"영화 {title} {year}"])
    queries.extend([f"{title} 영화", f"영화 {title}"])
    best = {"openDt": None, "audiCnt": None, "director": "", "genres": ""}
    for q in queries:
        url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(q)}"
        try:
            page.goto(url, timeout=15000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            continue
        try:
            text = page.inner_text("body")
        except Exception:  # noqa: BLE001
            continue
        om = _NAVER_OPEN_RE.search(text)
        am = _NAVER_AUDI_RE.search(text)
        dm = _NAVER_DIR_RE.search(text)
        gm = _NAVER_GENRE_RE.search(text)
        if om and best["openDt"] is None:
            best["openDt"] = f"{om.group(1)}-{int(om.group(2)):02d}-{int(om.group(3)):02d}"
        if am and best["audiCnt"] is None:
            best["audiCnt"] = _parse_audi(am)
        if dm and not best["director"]:
            dirs = _clean_list(dm.group(1), 3)
            if dirs:
                best["director"] = ", ".join(dirs)
        if gm and not best["genres"]:
            gens = _clean_list(gm.group(1), 2)
            if gens:
                best["genres"] = ", ".join(gens)
        if all([best["openDt"], best["audiCnt"], best["director"], best["genres"]]):
            break
    return best


def collect_movies_from_naver(browser, ott_df: pd.DataFrame) -> pd.DataFrame:
    if ott_df.empty:
        return pd.DataFrame(columns=["title", "year", "openDt", "audiCnt", "director", "genres"])
    movies = ott_df[ott_df["kind"] == "영화"][["title", "year"]].drop_duplicates().reset_index(drop=True)

    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()
    rows = []
    for i, r in movies.iterrows():
        title = str(r["title"])
        year = str(r.get("year") or "").strip()
        info = _search_naver(page, title, year)
        rows.append({
            "title": title,
            "year": year,
            "openDt": info["openDt"],
            "audiCnt": info["audiCnt"],
            "director": info["director"],
            "genres": info["genres"],
        })
        print(
            f"  · [{i+1}/{len(movies)}] {title} ({year}) → "
            f"{info['openDt'] or '—'}, {info['audiCnt'] or '—'}, "
            f"감독={info['director'] or '—'}, 장르={info['genres'] or '—'}",
            flush=True,
        )
    ctx.close()
    return pd.DataFrame(rows)


def main() -> None:
    now = _dt.datetime.now().isoformat(timespec="seconds")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("▶ OTT 랭킹 수집 중… (키노라이츠 3곳 + 웨이브 자체 API)", flush=True)
        ott_df = collect_ott(browser)
        print(f"  · {len(ott_df)}편 · 플랫폼별: ", end="")
        if not ott_df.empty:
            print(dict(ott_df["platform"].value_counts()))
        print("▶ 네이버 영화 메타 수집 중…", flush=True)
        movies_df = collect_movies_from_naver(browser, ott_df)
        browser.close()

    ott_df.to_csv(DATA / "ott.csv", index=False, encoding="utf-8")
    movies_df.to_csv(DATA / "movies.csv", index=False, encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps({"refreshed_at": now}, ensure_ascii=False))

    got_open = movies_df["openDt"].notna().sum() if not movies_df.empty else 0
    got_audi = movies_df["audiCnt"].notna().sum() if not movies_df.empty else 0
    got_dir = (movies_df["director"].astype(str).str.len() > 0).sum() if not movies_df.empty else 0
    got_gen = (movies_df["genres"].astype(str).str.len() > 0).sum() if not movies_df.empty else 0
    print(
        f"✅ data/ 저장 완료 · {now}\n"
        f"  · 영화 {len(movies_df)}편 · 개봉일 {got_open} · 관객수 {got_audi} · "
        f"감독 {got_dir} · 장르 {got_gen}"
    )


if __name__ == "__main__":
    main()
