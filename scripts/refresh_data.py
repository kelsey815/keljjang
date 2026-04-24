"""로컬에서 KOBIS 박스오피스 + 키노라이츠 OTT 랭킹을 수집해 data/*.parquet로 저장.

사용: `python scripts/refresh_data.py`
저장된 parquet 파일들이 Streamlit Cloud 배포의 데이터 소스가 된다.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

_KOBIS_URL = "https://www.kobis.or.kr/kobis/business/stat/boxs/findYearlyBoxOfficeList.do"
_NUM_RE = re.compile(r"[^0-9]")
_META_RE = re.compile(r"(영화|드라마|예능|애니메이션|키즈|다큐멘터리|다큐)\s*·\s*(\d{4})")

PLATFORMS = {
    "쿠팡플레이": "coupangplay",
    "티빙": "tving",
    "왓챠": "watcha",
    "웨이브": "wavve",
}


def _to_int(s: str) -> int:
    d = _NUM_RE.sub("", s or "")
    return int(d) if d else 0


def collect_kobis(page) -> pd.DataFrame:
    current_year = _dt.date.today().year
    years = [y for y in (2025, 2026) if y <= current_year]
    rows = []
    for y in years:
        page.goto(_KOBIS_URL, timeout=30000)
        page.wait_for_selector("#sSearchYearFrom", timeout=15000)
        page.select_option("#sSearchYearFrom", str(y))
        page.evaluate("chkform('search')")
        try:
            page.wait_for_function(
                "document.querySelectorAll('table.tbl_comm tbody tr').length > 0 "
                "&& !document.querySelector('table.tbl_comm tbody tr td[colspan]')",
                timeout=20000,
            )
        except Exception:  # noqa: BLE001
            continue
        trs = page.query_selector_all("table.tbl_comm tbody tr")
        for tr in trs:
            tds = [td.inner_text().strip() for td in tr.query_selector_all("td")]
            if len(tds) < 7:
                continue
            try:
                rows.append(
                    {
                        "year": y,
                        "rank": int(tds[0]),
                        "movieNm": tds[1],
                        "openDt": tds[2],
                        "salesAmt": _to_int(tds[3]),
                        "salesShare": tds[4],
                        "audiCnt": _to_int(tds[5]),
                        "screenCnt": _to_int(tds[6]),
                        "showCnt": _to_int(tds[7]) if len(tds) > 7 else 0,
                    }
                )
            except ValueError:
                continue
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=["movieNm", "openDt", "salesAmt", "audiCnt", "screenCnt", "showCnt"]
        )
    df = df[df["openDt"] >= "2025-01-01"].copy()
    df = (
        df.sort_values("audiCnt", ascending=False)
        .drop_duplicates(subset=["movieNm", "openDt"], keep="first")
        .reset_index(drop=True)
    )
    return df


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


def main() -> None:
    now = _dt.datetime.now().isoformat(timespec="seconds")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="Mozilla/5.0")
        page = ctx.new_page()
        print("▶ KOBIS 수집 중…")
        kobis_df = collect_kobis(page)
        ctx.close()
        print(f"  · {len(kobis_df)}편")
        print("▶ OTT 랭킹 수집 중…")
        ott_df = collect_ott(browser)
        print(f"  · {len(ott_df)}편 (영화+시리즈)")
        browser.close()

    kobis_df.to_csv(DATA / "kobis.csv", index=False, encoding="utf-8")
    ott_df.to_csv(DATA / "ott.csv", index=False, encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps({"refreshed_at": now}, ensure_ascii=False))
    print(f"✅ data/ 저장 완료 · {now}")


if __name__ == "__main__":
    main()
