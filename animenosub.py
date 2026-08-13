import re
import json
import random
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

BASE = "https://animenosub.to"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


async def fetch_page_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 10.0) -> str:
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


async def fetch_json_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 10.0) -> Any:
    req_headers = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code == 200:
                return res.json()
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
                        return res.json()
            except Exception:
                continue

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=req_headers)
        res.raise_for_status()
        return res.json()


async def post_form_with_proxy(url: str, data: dict, headers: Optional[dict] = None, timeout: float = 10.0) -> Any:
    req_headers = {"User-Agent": UA}
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.post(url, data=data, headers=req_headers)
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass

    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
                    res = await client.post(url, data=data, headers=req_headers)
                    if res.status_code == 200:
                        return res.json()
            except Exception:
                continue

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.post(url, data=data, headers=req_headers)
        res.raise_for_status()
        return res.json()


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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
                async with httpx.AsyncClient(proxy=proxy, timeout=10.0) as client:
                    res = await client.post(url, json=payload, headers=req_headers)
                    if res.status_code == 200:
                        data = res.json()
                        media = data.get("data", {}).get("Media")
                        if media:
                            return media
            except Exception:
                continue

    raise Exception(f"No media found for AniList ID {anilist_id}")


async def search_animenosub(query: str) -> List[dict]:
    url = f"{BASE}/wp-admin/admin-ajax.php"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE,
        "Referer": f"{BASE}/"
    }
    data = {"action": "ts_ac_do_search", "ts_ac_query": query}
    try:
        resp_data = await post_form_with_proxy(url, data=data, headers=headers)
        results = []
        all_items = (((resp_data or {}).get("anime") or [{}])[0]).get("all") or []
        for item in all_items:
            link = item.get("post_link") or ""
            m = re.search(r'/anime/([^/]+)/?$', link)
            if m:
                slug = m.group(1)
                title = item.get("post_title") or slug.replace("-", " ")
                results.append({"slug": slug, "title": title})
        return results
    except Exception:
        return []


async def resolve_vidmoly(embed_url: str) -> Optional[str]:
    url = f"https:{embed_url}" if embed_url.startswith("//") else embed_url
    try:
        html = await fetch_page_with_proxy(url, headers={"Referer": f"{BASE}/"})
        m = re.search(r"sources:\s*\[\s*\{\s*file:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    media = await get_media(anilist_id)
    t_obj = media.get("title") or {}
    query = t_obj.get("english") or t_obj.get("romaji") or "Anime"

    results = await search_animenosub(query)
    if not results:
        return {"error": f"AnimeNoSub search failed for query: {query}"}

    chosen = results[0]
    series_html = await fetch_page_with_proxy(f"{BASE}/anime/{chosen['slug']}/", headers={"Referer": BASE})

    embed_iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', series_html)
    streams = []

    for iframe_src in embed_iframes:
        if "vidmoly" in iframe_src:
            hls = await resolve_vidmoly(iframe_src)
            if hls:
                streams.append({"server": "Vidmoly HLS", "url": hls, "type": "hls"})
            else:
                streams.append({"server": "Vidmoly Embed", "url": iframe_src, "type": "embed"})
        else:
            streams.append({"server": "AnimeNoSub Embed", "url": iframe_src, "type": "embed"})

    if not streams:
        # Construct fallback direct episode page link
        ep_url = f"{BASE}/{chosen['slug']}-episode-{ep_num}/"
        try:
            ep_html = await fetch_page_with_proxy(ep_url, headers={"Referer": BASE})
            iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', ep_html)
            for src in iframes:
                streams.append({"server": "AnimeNoSub Embed", "url": src, "type": "embed"})
        except Exception:
            pass

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
        print(f"Testing AnimeNoSub extraction for AniList ID {anilist_id}, Ep {ep_num}...")
        res = await handle_watch(anilist_id, "sub", ep_num)
        print(json.dumps(res, indent=2))

    asyncio.run(test())
