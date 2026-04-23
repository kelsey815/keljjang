"""키노라이츠(m.kinolights.com) OTT 플랫폼별 랭킹 스크래핑.

쿠팡플레이 / 티빙 / 왓챠 / 웨이브 각 플랫폼 랭킹 페이지를 Playwright로 렌더링한 뒤
영화만 필터해서 Top N을 반환한다.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright

PLATFORMS = {
    "쿠팡플레이": "coupangplay",
    "티빙": "tving",
    "왓챠": "watcha",
    "웨이브": "wavve",
}

_META_RE = re.compile(r"(영화|드라마|예능|애니메이션|키즈|다큐멘터리|다큐)\s*·\s*(\d{4})")


def _extract_one_platform(page, platform_key: str) -> list[dict]:
    url = f"https://m.kinolights.com/ranking/{platform_key}"
    page.goto(url, timeout=30000)
    page.wait_for_selector("li.ranking-item", timeout=15000)
    # 스크롤로 지연 로딩 대비
    for _ in range(6):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        page.wait_for_timeout(400)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
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
                text: (li.innerText || '').replace(/\\s+/g, ' ').trim(),
            };
        })
        """
    )
    items = []
    for it in raw:
        try:
            rank = int(it["rank"])
        except (TypeError, ValueError):
            continue
        title = (it["title"] or "").strip()
        if not title:
            continue
        meta_match = _META_RE.search(it.get("text") or "")
        content_type = meta_match.group(1) if meta_match else ""
        year = meta_match.group(2) if meta_match else ""
        items.append(
            {
                "rank": rank,
                "title": title,
                "content_type": content_type,
                "year": year,
                "href": it.get("href") or "",
            }
        )
    return items


@st.cache_data(ttl=1800, show_spinner="키노라이츠에서 OTT 랭킹 수집 중 (약 20초)...")
def collect_ott_rankings(top_n: int = 30) -> pd.DataFrame:
    all_rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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
                items = _extract_one_platform(page, plat_key)
            except Exception as e:  # noqa: BLE001
                st.warning(f"{plat_name} 수집 중 오류: {e}")
                items = []
            for it in items:
                it["platform"] = plat_name
                all_rows.append(it)
            ctx.close()
        browser.close()

    if not all_rows:
        return pd.DataFrame(columns=["platform", "rank", "title", "content_type", "year", "href"])

    df = pd.DataFrame(all_rows)
    df = df[df["content_type"] == "영화"].copy()
    # 플랫폼 내 영화끼리 1..N 순위 재부여 (원본 rank는 영화+드라마+예능 통합)
    df["platform_movie_rank"] = df.groupby("platform")["rank"].rank(method="min").astype(int)
    # Top N 필터는 영화 순위 기준. 플랫폼 내 영화가 적으면 그만큼만 남음.
    df = df[df["platform_movie_rank"] <= top_n].copy()
    return df.sort_values(["platform", "platform_movie_rank"]).reset_index(drop=True)
