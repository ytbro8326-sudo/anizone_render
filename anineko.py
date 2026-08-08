import re
import html
import json
import random
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse
import httpx

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

BASE = "https://anineko.to"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


async def fetch_page_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 4.0) -> str:
    req_headers = {"User-Agent": UA}
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code == 200:
                return res.text
    except Exception:
        pass

    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
                    res = await client.get(url, headers=req_headers)
                    if res.status_code == 200:
                        return res.text
            except Exception:
                continue

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=req_headers)
        res.raise_for_status()
        return res.text


async def get_media(anilist_id: int) -> dict:
    query = """
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        idMal
        title { english romaji native }
      }
    }
    """
    req_headers = {"Content-Type": "application/json", "User-Agent": UA}
    url = "https://graphql.anilist.co"
    payload = {"query": query, "variables": {"id": int(anilist_id)}}

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(url, json=payload, headers=req_headers)
            if res.status_code == 200:
                data = res.json()
                media = data.get("data", {}).get("Media")
                if media:
                    return media
    except Exception:
        pass

    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=4.0) as client:
                    res = await client.post(url, json=payload, headers=req_headers)
                    if res.status_code == 200:
                        data = res.json()
                        media = data.get("data", {}).get("Media")
                        if media:
                            return media
            except Exception:
                continue

    raise Exception(f"No media found for AniList ID {anilist_id}")


async def search_anineko(query: str) -> List[dict]:
    url = f"{BASE}/browser?keyword={quote(query)}"
    try:
        html_content = await fetch_page_with_proxy(url)
    except Exception:
        return []

    results = []
    blocks = re.findall(r'<a\b[^>]*class=["\'][^"\']*nv-anime-thumb[^"\']*["\'][^>]*>[\s\S]*?<\/a>', html_content, re.IGNORECASE)
    for block in blocks:
        slug_m = re.search(r'href=["\']/watch/([^"\'/?#]+)', block)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        title_m = re.search(r'<(?:h3|[^>]+class=["\'][^"\']*nv-anime-title[^"\']*["\'][^>]*)>([\s\S]*?)<\/(?:h3|[^>]+)>', block, re.IGNORECASE)
        title = re.sub(r'<[^>]*>', '', title_m.group(1)).strip() if title_m else slug.replace("-", " ")
        results.append({"slug": slug, "title": title})

    return results


def score_candidate(cand: dict, primary_en: str, primary_rom: str) -> int:
    c_title = (cand.get("title") or "").lower().strip()
    c_slug = (cand.get("slug") or "").lower().strip()
    p_en = (primary_en or "").lower().strip()
    p_rom = (primary_rom or "").lower().strip()

    score = 0
    if p_en and c_title == p_en:
        score += 1000
    if p_rom and c_title == p_rom:
        score += 900
    if p_en and c_slug == p_en.replace(" ", "-"):
        score += 800

    for mod in ["movie", "special", "episode of", "film", "3d", "sp", "ova", "fan letter", "recap"]:
        if mod in c_title and mod not in p_en and mod not in p_rom:
            score -= 300

    return score


async def extract_hls(embed_url: str) -> Optional[str]:
    try:
        html_content = await fetch_page_with_proxy(embed_url, headers={"Referer": f"{BASE}/"}, timeout=2.5)
        patterns = [
            r'const\s+src\s*=\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'file\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+/master\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html_content, re.IGNORECASE)
            if m:
                return html.unescape(m.group(1))
    except Exception:
        pass
    return None


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    media = await get_media(anilist_id)
    t_obj = media.get("title") or {}
    p_en = t_obj.get("english") or ""
    p_rom = t_obj.get("romaji") or ""
    query = p_en or p_rom or "Anime"

    results = await search_anineko(query)
    if not results:
        return {"error": f"AniNeko search failed for query: {query}"}

    results.sort(key=lambda c: score_candidate(c, p_en, p_rom), reverse=True)
    chosen = results[0]

    ep_url = f"{BASE}/watch/{chosen['slug']}/ep-{ep_num}"
    
    try:
        page_html = await fetch_page_with_proxy(ep_url, headers={"Referer": f"{BASE}/watch/{chosen['slug']}"})
    except Exception:
        return {"error": f"AniNeko episode page fetch failed for {chosen['slug']} ep {ep_num}"}

    embed_urls = []
    for btn in re.finditer(r'data-video=["\']([^"\']+)["\']', page_html):
        embed_urls.append(html.unescape(btn.group(1)))

    hls_results = await asyncio.gather(*[extract_hls(u) for u in embed_urls], return_exceptions=True)

    streams = []
    for embed_url, hls in zip(embed_urls, hls_results):
        if isinstance(hls, str) and hls:
            streams.append({"server": "AniNeko HLS", "url": hls, "type": "hls"})
        streams.append({"server": "AniNeko Embed", "url": embed_url, "type": "embed"})

    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "animeTitle": chosen["title"],
        "audio": audio,
        "streams": streams
    }


if __name__ == "__main__":
    async def test():
        anilist_id = 21  # One Piece
        ep_num = 1
        print(f"Testing AniNeko extraction for AniList ID {anilist_id}, Ep {ep_num}...")
        res = await handle_watch(anilist_id, "sub", ep_num)
        print(json.dumps(res, indent=2))

    asyncio.run(test())
