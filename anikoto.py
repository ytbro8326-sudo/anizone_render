import re
import json
import base64
import random
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

ANIKOTO = "https://anikototv.to"
MAPPER = "https://mapper.nekostream.site/api/mal"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


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


async def get_media(anilist_id: int) -> dict:
    query = """
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        idMal
        title { english romaji native }
        synonyms
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


async def search_anikoto(query: str) -> List[dict]:
    url = f"{ANIKOTO}/filter?keyword={quote(query)}"
    try:
        search_html = await fetch_page_with_proxy(url, headers={"Referer": f"{ANIKOTO}/"})
    except Exception:
        return []

    candidates = []
    pattern = r'<a\s+class="name d-title"\s+href="https:\/\/anikototv\.to\/watch\/([^"/]+)(?:\/ep-\d+)?"[^>]*data-jp="([^"]*)"[^>]*>([\s\S]*?)<\/a>'
    for m in re.finditer(pattern, search_html):
        slug = m.group(1)
        jp = m.group(2).strip()
        name = re.sub(r'<[^>]*>', '', m.group(3)).strip()
        candidates.append({"slug": slug, "name": name, "jp": jp})

    if not candidates:
        fallback_pattern = r'<a\s+href="https:\/\/anikototv\.to\/watch\/([^"/]+)(?:\/ep-\d+)?"[^>]*>([\s\S]*?)<\/a>'
        for m in re.finditer(fallback_pattern, search_html):
            candidates.append({"slug": m.group(1), "name": m.group(1), "jp": ""})

    seen = set()
    result = []
    for c in candidates:
        if c["slug"] not in seen:
            seen.add(c["slug"])
            result.append(c)
    return result


def score_candidate(cand: dict, primary_en: str, primary_rom: str) -> int:
    c_name = (cand.get("name") or "").lower()
    c_slug = (cand.get("slug") or "").lower()
    p_en = (primary_en or "").lower()
    p_rom = (primary_rom or "").lower()

    score = 0
    if p_en and c_name == p_en:
        score += 1000
    if p_rom and c_name == p_rom:
        score += 900
    if p_en and c_slug.startswith(p_en.replace(" ", "-")):
        score += 500

    for mod in ["movie", "special", "episode of", "film", "3d", "sp", "ova"]:
        if mod in c_name and mod not in p_en and mod not in p_rom:
            score -= 300

    return score


async def find_anikoto_show(media: dict) -> dict:
    t_obj = media.get("title") or {}
    primary_en = t_obj.get("english")
    primary_rom = t_obj.get("romaji")
    synonyms = media.get("synonyms") or []

    keywords = list(dict.fromkeys([k for k in [primary_en, primary_rom, *synonyms] if k]))
    candidates_map = {}

    for k in keywords[:3]:
        res = await search_anikoto(k)
        for c in res:
            if c["slug"] not in candidates_map:
                candidates_map[c["slug"]] = c

    candidates = list(candidates_map.values())
    if not candidates:
        raise Exception(f"No results found on AniKoto for: {primary_en or primary_rom}")

    candidates.sort(key=lambda c: score_candidate(c, primary_en or "", primary_rom or ""), reverse=True)
    chosen = candidates[0]

    watch_html = await fetch_page_with_proxy(f"{ANIKOTO}/watch/{chosen['slug']}", headers={"Referer": f"{ANIKOTO}/"})
    show_id_m = re.search(r'data-id="(\d+)"', watch_html)
    if not show_id_m:
        raise Exception(f"Could not find show ID for slug: {chosen['slug']}")

    return {"slug": chosen["slug"], "showId": show_id_m.group(1), "title": chosen["name"]}


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    aud = audio.lower()
    media = await get_media(anilist_id)
    show = await find_anikoto_show(media)

    ajax_url = f"{ANIKOTO}/ajax/episode/list/{show['showId']}"
    ajax_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{ANIKOTO}/watch/{show['slug']}"
    }
    list_json = await fetch_json_with_proxy(ajax_url, headers=ajax_headers)
    html_res = list_json.get("result", "") if isinstance(list_json, dict) else ""

    target_ep = None
    ep_pattern = r'<a\s+[^>]*data-id="([^"]*)"[^>]*>'
    for m in re.finditer(ep_pattern, html_res):
        tag = m.group(0)
        num_m = re.search(r'data-num="([^"]*)"', tag)
        if num_m:
            try:
                if int(num_m.group(1)) == int(ep_num):
                    target_ep = {
                        "id": m.group(1),
                        "ids": (re.search(r'data-ids="([^"]*)"', tag) or [None, ""])[1],
                        "mal": (re.search(r'data-mal="([^"]*)"', tag) or [None, ""])[1],
                        "slug": (re.search(r'data-slug="([^"]*)"', tag) or [None, ""])[1],
                        "timestamp": (re.search(r'data-timestamp="([^"]*)"', tag) or [None, ""])[1],
                    }
                    break
            except ValueError:
                continue

    if not target_ep or not target_ep["ids"]:
        return {"error": f"AniKoto episode {ep_num} not found for {show['title']}"}

    srv_list_url = f"{ANIKOTO}/ajax/server/list?servers={quote(target_ep['ids'])}"
    srv_json = await fetch_json_with_proxy(srv_list_url, headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{ANIKOTO}/"})
    srv_html = srv_json.get("result", "") if isinstance(srv_json, dict) else ""

    server_items = []
    type_blocks = re.findall(r'<div class="type" data-type="([^"]+)">([\s\S]*?)<\/ul>\s*<\/div>', srv_html)
    for type_name, block in type_blocks:
        if type_name == aud or aud == "all":
            for li in re.finditer(r'<li\s+[^>]*data-link-id="([^"]+)"[^>]*>([\s\S]*?)<\/li>', block):
                link_id = li.group(1)
                srv_name = re.sub(r'<[^>]+>', '', li.group(2)).strip()
                server_items.append({"linkId": link_id, "name": srv_name})

    streams = []
    seen = set()
    for item in server_items:
        if item["name"] in seen:
            continue
        seen.add(item["name"])

        try:
            if item["linkId"].startswith("http"):
                embed_url = item["linkId"]
            else:
                get_srv_url = f"{ANIKOTO}/ajax/server?get={quote(item['linkId'])}"
                res = await fetch_json_with_proxy(get_srv_url, headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{ANIKOTO}/"})
                embed_url = res.get("result", {}).get("url") if isinstance(res, dict) else None

            if embed_url:
                hls_url = None
                if "#aHR0c" in embed_url:
                    try:
                        b64 = embed_url.split("#")[1]
                        decoded = base64.b64decode(b64).decode("utf-8")
                        if ".m3u8" in decoded:
                            hls_url = decoded
                    except Exception:
                        pass

                if hls_url:
                    streams.append({"server": f"AniKoto {item['name']} (HLS)", "url": hls_url, "type": "hls"})
                else:
                    streams.append({"server": f"AniKoto {item['name']}", "url": embed_url, "type": "embed"})
        except Exception:
            continue

    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "showTitle": show["title"],
        "audio": aud,
        "streams": streams
    }


if __name__ == "__main__":
    async def test():
        anilist_id = 21  # One Piece
        ep_num = 1
        print(f"Testing AniKoto extraction for AniList ID {anilist_id}, Ep {ep_num}...")
        res = await handle_watch(anilist_id, "sub", ep_num)
        print(json.dumps(res, indent=2))

    asyncio.run(test())
