import re
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

BASE_URL = "https://epeng.animeapps.top"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


async def fetch_page_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 10.0) -> str:
    req_headers = {"User-Agent": USER_AGENT}
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
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
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
        episodes
      }
    }
    """
    req_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
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


async def fetch_servers(anilist_id: int) -> List[dict]:
    url = f"{BASE_URL}/api2.php?epid={anilist_id}"
    try:
        data = await fetch_json_with_proxy(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def fetch_player_links(provider_link: str) -> List[dict]:
    url = f"{BASE_URL}/apilink.php?data={quote(provider_link)}"
    try:
        data = await fetch_json_with_proxy(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def extract_video_url(html_str: str, origin: str) -> Optional[str]:
    m = re.search(r'videoUrl\s*:\s*"([^"]+)"', html_str)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"{origin}{'' if raw.startswith('/') else '/'}{raw}"


async def resolve_player_stream(player_link: str) -> dict:
    parsed = urlparse(player_link)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    referer = f"{origin}/"
    html_str = await fetch_page_with_proxy(player_link, headers={"Referer": referer})
    hls = extract_video_url(html_str, origin)
    if not hls:
        raise Exception(f"anibd: no videoUrl found at {player_link}")
    return {"hls": hls, "referer": referer}


def audio_from_server_name(name: str = "") -> str:
    return "dub" if re.search(r'dub', name, re.IGNORECASE) else "sub"


async def find_episode_link(anilist_id: int, audio: str, ep_num: int) -> Optional[str]:
    groups = await fetch_servers(anilist_id)
    for group in groups:
        if audio_from_server_name(group.get("server_name", "")) != audio:
            continue
        for ep in group.get("server_data", []) or []:
            try:
                num = int(ep.get("name") or ep.get("slug"))
                if num == ep_num:
                    return ep.get("link")
            except (ValueError, TypeError):
                continue
    return None


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    aud = audio.lower()
    provider_link = await find_episode_link(anilist_id, aud, ep_num)
    if not provider_link:
        return {"error": f"AniBD episode {ep_num} not found for AniList {anilist_id}"}

    servers = await fetch_player_links(provider_link)
    streams = []
    active_assigned = False

    for entry in servers:
        link = entry.get("link")
        if not link:
            continue
        srv_name = entry.get("server") or "AniBD"
        try:
            resolved = await resolve_player_stream(link)
            streams.append({
                "url": resolved["hls"],
                "type": "hls",
                "server": srv_name,
                "referer": resolved["referer"],
                "priority": 4 if active_assigned else 5,
                "isActive": not active_assigned,
            })
            active_assigned = True
        except Exception:
            try:
                parsed = urlparse(link)
                origin = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                origin = link
            streams.append({
                "url": link,
                "type": "embed",
                "server": srv_name,
                "referer": f"{origin}/",
                "priority": 1,
                "isActive": False,
            })

    return {"anilistId": int(anilist_id), "episode": int(ep_num), "audio": aud, "streams": streams}


if __name__ == "__main__":
    async def test():
        anilist_id = 21  # One Piece AniList ID
        ep_num = 1
        print(f"Testing AniBD extraction for AniList ID {anilist_id}, Ep {ep_num}...")
        res = await handle_watch(anilist_id, "sub", ep_num)
        print(json.dumps(res, indent=2))

    asyncio.run(test())
