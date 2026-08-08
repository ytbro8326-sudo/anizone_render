import re
import html
import json
import time
import os
import random
import asyncio
import base64
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse
import httpx

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

BASE_URL = "https://2dhive.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Cache:
    def __init__(self):
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            data, expires_at = self._store[key]
            if time.time() < expires_at:
                return data
            else:
                del self._store[key]
        return None

    def set(self, key: str, data: Any, ttl_seconds: float = 86400):
        self._store[key] = (data, time.time() + ttl_seconds)


cache = Cache()


def decode_entities(s: str = "") -> str:
    if not s:
        return ""
    return html.unescape(s).strip()


def enc_aes_gcm(key_b64: str, payload_str: str) -> str:
    if not HAS_CRYPTO:
        raise Exception("cryptography library required for AES-GCM encryption")
    key = base64.b64decode(key_b64)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, payload_str.encode('utf-8'), None)
    return base64.b64encode(nonce + ct).decode('utf-8')


def dec_aes_gcm(key_b64: str, ciphertext_b64: str) -> str:
    if not HAS_CRYPTO:
        raise Exception("cryptography library required for AES-GCM decryption")
    key = base64.b64decode(key_b64)
    data = base64.b64decode(ciphertext_b64)
    nonce = data[:12]
    ct = data[12:]
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ct, None)
    return decrypted.decode('utf-8')


async def fetch_page(url: str, headers: Optional[dict] = None) -> str:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)

    # 1. Direct request
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            res.raise_for_status()
            return res.text
    except Exception as direct_err:
        # 2. Proxy rotation retry
        if PROXIES:
            shuffled = list(PROXIES)
            random.shuffle(shuffled)
            for proxy in shuffled:
                try:
                    async with httpx.AsyncClient(proxy=proxy, timeout=12.0, follow_redirects=True) as client:
                        res = await client.get(url, headers=req_headers)
                        res.raise_for_status()
                        return res.text
                except Exception:
                    continue
        raise direct_err


async def httpx_post_with_proxy(url: str, json_data: dict, headers: Optional[dict] = None, timeout: float = 12.0) -> httpx.Response:
    # 1. Direct request
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json=json_data, headers=headers)
            if res.status_code == 200:
                return res
    except Exception:
        pass

    # 2. Proxy rotation retry
    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout) as client:
                    res = await client.post(url, json=json_data, headers=headers)
                    if res.status_code == 200:
                        return res
            except Exception:
                continue

    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(url, json=json_data, headers=headers)
        return res


async def fetch_json(url: str, headers: Optional[dict] = None) -> Any:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            res.raise_for_status()
            return res.json()
    except Exception as direct_err:
        if PROXIES:
            shuffled = list(PROXIES)
            random.shuffle(shuffled)
            for proxy in shuffled:
                try:
                    async with httpx.AsyncClient(proxy=proxy, timeout=12.0, follow_redirects=True) as client:
                        res = await client.get(url, headers=req_headers)
                        res.raise_for_status()
                        return res.json()
                except Exception:
                    continue
        raise direct_err


async def get_media(anilist_id: int) -> dict:
    query = """
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        idMal
        title { english romaji native }
        status
        format
        episodes
        synonyms
      }
    }
    """
    req_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    url = "https://graphql.anilist.co"
    payload = {"query": query, "variables": {"id": int(anilist_id)}}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
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
                async with httpx.AsyncClient(proxy=proxy, timeout=12.0) as client:
                    res = await client.post(url, json=payload, headers=req_headers)
                    if res.status_code == 200:
                        data = res.json()
                        media = data.get("data", {}).get("Media")
                        if media:
                            return media
            except Exception:
                continue

    raise Exception(f"No media found for AniList ID {anilist_id}")


async def get_mal_id(anilist_id: int, ctx: Optional[dict] = None) -> int:
    ctx = ctx or {}
    media = ctx.get("media")
    if not media or not media.get("idMal"):
        media = await get_media(anilist_id)
    id_mal = media.get("idMal")
    if not id_mal:
        raise Exception(f"2dhive: no MAL ID found for AniList {anilist_id}")
    return int(id_mal)


def parse_episode_nums(html_str: str, mal_id: int) -> List[int]:
    pattern = r'/episode\?anime=%d&(?:amp;)?ep_num=(\d+)' % mal_id
    matches = re.finditer(pattern, html_str, re.IGNORECASE)
    nums = set()
    for m in matches:
        nums.add(int(m.group(1)))
    return sorted(list(nums))


async def resolve_babastream(mal_id: int, ep_num: int, audio: str = "sub") -> List[dict]:
    """Extract direct streams from 2Dhive BabaStream resolver with proxy fallback."""
    embed_url = f"https://babastream.top/embed/{mal_id}/{ep_num}/{audio}"
    headers = {"User-Agent": USER_AGENT, "Referer": "https://2dhive.com/"}
    
    try:
        html_content = await fetch_page(embed_url, headers=headers)
    except Exception:
        return []

    cfg_match = re.search(r'var CFG\s*=\s*(\{[\s\S]*?\});', html_content)
    if not cfg_match:
        return []

    try:
        cfg = json.loads(cfg_match.group(1))
    except Exception:
        return []

    pk = cfg.get("pk")
    sid = cfg.get("sid")
    if not pk or not sid:
        return []

    payload = json.dumps({"ts": int(time.time() * 1000)})
    enc_d = enc_aes_gcm(pk, payload)

    streams = []

    # 1. Primary resolve endpoint (uses proxy rotation fallback)
    try:
        resolve_res = await httpx_post_with_proxy(
            "https://babastream.top/api/resolve",
            json_data={"s": sid, "d": enc_d},
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, "Referer": embed_url}
        )
        if resolve_res.status_code == 200:
            resp_json = resolve_res.json()
            if "d" in resp_json:
                dec_str = dec_aes_gcm(pk, resp_json["d"])
                dec_data = json.loads(dec_str)
                stream_url = dec_data.get("u")
                if stream_url:
                    is_hls = ".m3u8" in stream_url
                    streams.append({
                        "server": f"BabaStream ({audio.upper()})",
                        "url": stream_url,
                        "type": "hls" if is_hls else "mp4",
                        "priority": 1,
                        "isActive": True
                    })
    except Exception:
        pass

    # 2. Alternate Vidara resolve endpoint (uses proxy rotation fallback)
    try:
        vidara_res = await httpx_post_with_proxy(
            "https://babastream.top/api/vidara",
            json_data={"s": sid, "d": enc_d},
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, "Referer": embed_url}
        )
        if vidara_res.status_code == 200:
            v_json = vidara_res.json()
            if "d" in v_json:
                dec_str = dec_aes_gcm(pk, v_json["d"])
                dec_data = json.loads(dec_str)
                v_url = dec_data.get("u")
                if v_url:
                    streams.append({
                        "server": f"Vidara ({audio.upper()})",
                        "url": v_url,
                        "type": "embed",
                        "priority": 2,
                        "isActive": False
                    })
    except Exception:
        pass

    return streams


def expected_count(media: Optional[dict] = None, anizip: Optional[dict] = None, jikan_eps: Optional[list] = None) -> Optional[int]:
    counts = []
    if media and media.get("episodes") and isinstance(media["episodes"], int) and media["episodes"] > 0:
        counts.append(media["episodes"])
    if anizip and isinstance(anizip.get("episodes"), dict):
        for k in anizip["episodes"].keys():
            try:
                num = int(k)
                if num > 0:
                    counts.append(num)
            except ValueError:
                pass
    if jikan_eps and isinstance(jikan_eps, list):
        for e in jikan_eps:
            if isinstance(e, dict) and isinstance(e.get("mal_id"), int) and e["mal_id"] > 0:
                counts.append(e["mal_id"])
    return max(counts) if counts else None


def episode_meta(n: int, ctx: dict) -> dict:
    anizip = ctx.get("anizip") or {}
    jikan_eps = ctx.get("jikanEps") or []

    az_ep = (anizip.get("episodes") or {}).get(str(n)) or {}
    jk_ep = next((e for e in jikan_eps if isinstance(e, dict) and e.get("mal_id") == n), {})

    runtime = az_ep.get("runtime") or az_ep.get("length")
    duration = runtime * 60 if runtime else None

    az_title = az_ep.get("title") or {}
    title = jk_ep.get("title") or az_title.get("en") or az_title.get("x-jat")

    return {
        "title": title or f"Episode {n}",
        "duration": duration,
        "filler": jk_ep.get("filler") or az_ep.get("filler", False),
        "uncensored": False,
        "description": az_ep.get("overview") or az_ep.get("summary"),
        "image": az_ep.get("image") or (anizip.get("images") or {}).get("cover"),
        "airDate": jk_ep.get("aired") or az_ep.get("airdate") or az_ep.get("aired"),
    }


async def get_episodes(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    mal_id = await get_mal_id(anilist_id, ctx)
    anime_html = await fetch_page(f"{BASE_URL}/anime?anime={mal_id}")
    ep_nums = parse_episode_nums(anime_html, mal_id)
    if not ep_nums:
        ep_nums = list(range(1, 26))

    media = ctx.get("media") or await get_media(anilist_id)
    expected = expected_count(media, ctx.get("anizip"), ctx.get("jikanEps"))

    sub = []
    dub = []
    for num in ep_nums:
        if expected and num > expected:
            continue
        meta = episode_meta(num, ctx)
        base = {
            "number": num,
            "title": meta.get("title") or f"Episode {num}",
            "duration": meta.get("duration"),
            "filler": meta.get("filler", False),
            "uncensored": meta.get("uncensored", False),
            "description": meta.get("description"),
            "image": meta.get("image"),
            "airDate": meta.get("airDate"),
        }
        sub.append({"id": f"watch/2dhive/{anilist_id}/sub/2dhive-{num}", **base, "audio": "sub"})
        dub.append({"id": f"watch/2dhive/{anilist_id}/dub/2dhive-{num}", **base, "audio": "dub"})

    return {
        "meta": {
            "id": str(anilist_id),
            "source": "2dhive",
            "matchScore": 1,
            "numbering": "standard",
            "episodeOffset": 0,
        },
        "episodes": {"sub": sub, "dub": dub},
    }


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    mal_id = await get_mal_id(anilist_id)
    referer = f"{BASE_URL}/episode?anime={mal_id}&ep_num={ep_num}"
    aud_str = str(audio or "sub").lower()

    # 1. BabaStream & Vidara resolver (using proxy rotation fallback)
    streams = await resolve_babastream(mal_id, ep_num, aud_str)

    # 2. Check hiAnime endpoint
    if aud_str != "dub":
        try:
            url = f"{BASE_URL}/api/hianime?mal_id={mal_id}&ep_num={ep_num}"
            hianime = await fetch_json(url, headers={"Referer": referer})
            if isinstance(hianime, dict) and hianime.get("m3u8"):
                entry = {"server": "hiAnime", "url": hianime["m3u8"]}
                if hianime.get("subtitle"):
                    entry["subtitle"] = hianime["subtitle"]
                streams.append(entry)
        except Exception:
            pass

    # 3. MegaPlay stream embed
    megaplay_audio = "dub" if aud_str == "dub" else "sub"
    streams.append({
        "server": "MegaPlay Dub" if aud_str == "dub" else "MegaPlay Sub",
        "url": f"https://megaplay.buzz/stream/mal/{mal_id}/{ep_num}/{megaplay_audio}",
        "type": "embed"
    })

    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "audio": audio,
        "streams": streams
    }


if __name__ == "__main__":
    async def test():
        anilist_id = 21  # One Piece AniList ID (MAL 21)
        ep_num = 1
        print(f"Testing 2dhive extraction for AniList ID {anilist_id}, Episode {ep_num}...")
        try:
            watch_sub = await handle_watch(anilist_id, "sub", ep_num)
            print("\nWatch Streams SUB:", json.dumps(watch_sub, indent=2))
        except Exception as e:
            print("Error during test:", e)

    asyncio.run(test())
