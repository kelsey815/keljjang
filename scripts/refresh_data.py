"""로컬에서 키노라이츠 OTT 랭킹 + 네이버 영화 메타(개봉일·관객수)를 수집해 data/*.csv 저장.

사용: `python scripts/refresh_data.py`
저장 파일:
  - data/ott.csv     : OTT 플랫폼별 랭킹 (영화 + 시리즈)
  - data/movies.csv  : OTT에 등장한 영화들의 네이버 메타 (개봉일·관객수)
  - data/meta.json   : 최종 갱신 시각
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

_META_RE = re.compile(r"(영화|드라마|예능|애니메이션|키즈|다큐멘터리|다큐)\s*·\s*(\d{4})")
_NAVER_OPEN_RE = re.compile(r"개봉\s*일?\s*(\d{4})[년\.\s]+(\d{1,2})[월\.\s]+(\d{1,2})")
_NAVER_AUDI_RE = re.compile(r"누적\s*관객수\s*(?:약\s*)?([\d,\.]+)\s*(만|억)?\s*명")

PLATFORMS = {
    "쿠팡플레이": "coupang",
    "티빙": "tving",
    "왓챠": "watcha",
    "웨이브": "wavve",
}


def collect_ott(browser) -> pd.DataFrame:
    all_rows = []
    for plat_name, plat_key in PLATFORMS.items():
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
            print(f"[{plat_name}] ERROR: {e}", file=sys.stderr)
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
            all_rows.append(
                {
                    "platform": plat_name,
                    "rank": rk,
                    "title": title,
                    "content_type": m.group(1) if m else "",
                    "year": m.group(2) if m else "",
                    "href": it.get("href") or "",
                }
            )
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["kind"] = df["content_type"].apply(lambda x: "영화" if x == "영화" else "시리즈")
    df["platform_rank"] = df.groupby("platform")["rank"].rank(method="min").astype(int)
    return df.sort_values(["platform", "platform_rank"]).reset_index(drop=True)


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


def _search_naver(page, title: str, year: str) -> dict:
    """제목·연도로 네이버 검색 → 개봉일·관객수 추출. 여러 쿼리 시도."""
    queries = []
    if year:
        queries.extend([f"{title} {year} 영화", f"영화 {title} {year}"])
    queries.extend([f"{title} 영화", f"영화 {title}"])

    best = {"openDt": None, "audiCnt": None}
    for q in queries:
        url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(q)}"
        try:
            page.goto(url, timeout=15000)
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001
            continue
        try:
            text = page.inner_text("body")
        except Exception:  # noqa: BLE001
            continue
        om = _NAVER_OPEN_RE.search(text)
        am = _NAVER_AUDI_RE.search(text)
        if om and best["openDt"] is None:
            best["openDt"] = f"{om.group(1)}-{int(om.group(2)):02d}-{int(om.group(3)):02d}"
        if am and best["audiCnt"] is None:
            best["audiCnt"] = _parse_audi(am)
        if best["openDt"] and best["audiCnt"]:
            break
    return best


def collect_movies_from_naver(browser, ott_df: pd.DataFrame) -> pd.DataFrame:
    if ott_df.empty:
        return pd.DataFrame(columns=["title", "year", "openDt", "audiCnt"])
    movies = ott_df[ott_df["kind"] == "영화"][["title", "year"]].drop_duplicates()
    movies = movies.reset_index(drop=True)

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
        rows.append(
            {
                "title": title,
                "year": year,
                "openDt": info["openDt"],
                "audiCnt": info["audiCnt"],
            }
        )
        print(
            f"  · [{i+1}/{len(movies)}] {title} ({year}) → "
            f"{info['openDt'] or '—'}, {info['audiCnt'] or '—'}"
        )
    ctx.close()
    return pd.DataFrame(rows)


def main() -> None:
    now = _dt.datetime.now().isoformat(timespec="seconds")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        print("▶ OTT 랭킹 수집 중…")
        ott_df = collect_ott(browser)
        print(f"  · {len(ott_df)}편 (영화+시리즈)")
        print("▶ 네이버에서 영화 메타 보완 수집 중…")
        movies_df = collect_movies_from_naver(browser, ott_df)
        browser.close()

    ott_df.to_csv(DATA / "ott.csv", index=False, encoding="utf-8")
    movies_df.to_csv(DATA / "movies.csv", index=False, encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps({"refreshed_at": now}, ensure_ascii=False))

    total_movies = len(movies_df)
    got_open = movies_df["openDt"].notna().sum() if not movies_df.empty else 0
    got_audi = movies_df["audiCnt"].notna().sum() if not movies_df.empty else 0
    print(
        f"✅ data/ 저장 완료 · {now}\n"
        f"  · 영화 {total_movies}편 · 개봉일 {got_open}건 · 관객수 {got_audi}건"
    )


if __name__ == "__main__":
    main()
