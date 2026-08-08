import re
import json
import random
import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote
import httpx

from proxies import PROXIES

BASE = "https://kaa.lt"
HLS_BASE = "https://hls.krussdomi.com/manifest"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


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


def norm(s: str = "") -> str:
    return re.sub(r'[^\w]', '', (s or "").lower())


def bigrams(s: str) -> Set[str]:
    clean = norm(s)
    if not clean:
        return set()
    if len(clean) == 1:
        return {clean}
    return {clean[i:i+2] for i in range(len(clean) - 1)}


def dice_coeff(a: str, b: str) -> float:
    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    inter = len(bg_a & bg_b)
    return (2.0 * inter) / (len(bg_a) + len(bg_b))


async def httpx_get_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 12.0) -> httpx.Response:
    # 1. Direct request first
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                return res
    except Exception:
        pass

    # 2. Proxy rotation retry
    shuffled = list(PROXIES)
    random.shuffle(shuffled)
    for proxy in shuffled:
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return res
        except Exception:
            continue

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        return res


async def httpx_post_with_proxy(url: str, json_data: dict, headers: Optional[dict] = None, timeout: float = 12.0) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json=json_data, headers=headers)
            if res.status_code == 200:
                return res
    except Exception:
        pass

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
        res.raise_for_status()
        return res


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
        seasonYear
        synonyms
      }
    }
    """
    res = await httpx_post_with_proxy(
        "https://graphql.anilist.co",
        json_data={"query": query, "variables": {"id": int(anilist_id)}},
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}
    )
    if res.status_code != 200:
        raise Exception(f"AniList HTTP {res.status_code}")
    data = res.json()
    media = data.get("data", {}).get("Media")
    if not media:
        raise Exception(f"No media found for AniList ID {anilist_id}")
    return media


def build_titles(media: dict, anizip: Optional[dict] = None) -> List[str]:
    titles = []
    if media and media.get("title"):
        t = media["title"]
        for k in ["english", "romaji", "native"]:
            if t.get(k):
                titles.append(t[k])
    if media and media.get("synonyms"):
        for syn in media["synonyms"]:
            if syn:
                titles.append(syn)
    if anizip and isinstance(anizip.get("titles"), dict):
        for val in anizip["titles"].values():
            if val:
                titles.append(val)
    return list(dict.fromkeys(titles))


# KAA API Functions
async def kaa_search(query: str) -> list:
    url = f"{BASE}/api/fsearch"
    headers = {**HEADERS, "Content-Type": "application/json"}
    res = await httpx_post_with_proxy(url, json_data={"page": 1, "query": query}, headers=headers)
    if res.status_code != 200:
        raise Exception(f"kaa fsearch HTTP {res.status_code}")
    data = res.json()
    return data.get("result") if isinstance(data.get("result"), list) else []


async def kaa_show_info(show_slug: str) -> dict:
    url = f"{BASE}/api/show/{show_slug}"
    res = await httpx_get_with_proxy(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"kaa show HTTP {res.status_code}: {show_slug}")
    return res.json()


async def kaa_episode_page(show_slug: str, ep: Any) -> dict:
    url = f"{BASE}/api/show/{show_slug}/episodes?ep={ep}&lang=ja-JP"
    res = await httpx_get_with_proxy(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"kaa episodes HTTP {res.status_code}")
    return res.json()


async def kaa_all_episodes(show_slug: str) -> list:
    first = await kaa_episode_page(show_slug, 1)
    pages = first.get("pages") if isinstance(first.get("pages"), list) else []
    all_eps = list(first.get("result")) if isinstance(first.get("result"), list) else []

    if len(pages) > 1:
        async def fetch_page(pg):
            eps_list = pg.get("eps")
            if isinstance(eps_list, list) and eps_list:
                start_ep = eps_list[0]
                d = await kaa_episode_page(show_slug, start_ep)
                return d.get("result") if isinstance(d.get("result"), list) else []
            return []

        rest_results = await asyncio.gather(*[fetch_page(pg) for pg in pages[1:]], return_exceptions=True)
        for batch in rest_results:
            if isinstance(batch, list):
                all_eps.extend(batch)

    return all_eps


async def kaa_episode_servers(show_slug: str, full_ep_slug: str) -> dict:
    url = f"{BASE}/api/show/{show_slug}/episode/{full_ep_slug}"
    res = await httpx_get_with_proxy(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"kaa episode servers HTTP {res.status_code}")
    return res.json()


def build_kaa_queries(titles: List[str]) -> List[str]:
    queries = set()
    for title in titles[:4]:
        if re.search(r'[\u3000-\u9fff\u4e00-\u9faf]', title):
            continue
        clean = re.sub(r'[^\w\s]', ' ', title)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if not clean or len(clean) < 3:
            continue
        words = [w for w in clean.split() if w]
        if len(words) <= 3:
            queries.add(clean)
        else:
            queries.add(" ".join(words[:2]))
            queries.add(" ".join(words[:3]))
    return list(queries)


def score_candidate(candidate: dict, titles: List[str], season_year: Optional[int], anilist_format: Optional[str]) -> float:
    title_en = candidate.get("title_en") or ""
    title_jp = candidate.get("title") or ""
    kaa_year = int(candidate.get("year")) if str(candidate.get("year", "")).isdigit() else None
    kaa_type = (candidate.get("type") or "").lower()

    base = 0.0
    for t in titles[:3]:
        if re.search(r'[\u3000-\u9fff\u4e00-\u9faf]', t):
            continue
        base = max(base, dice_coeff(t, title_en), dice_coeff(t, title_jp))

    year_mult = 1.0
    if season_year and kaa_year:
        diff = abs(int(season_year) - kaa_year)
        if diff == 0:
            year_mult = 1.2
        elif diff == 1:
            year_mult = 0.8
        else:
            year_mult = 0.5

    type_mult = 1.0
    af = (anilist_format or "").upper()
    if af == "MOVIE" and kaa_type != "movie":
        type_mult = 0.25
    elif af != "MOVIE" and kaa_type == "movie":
        type_mult = 0.25
    elif af in ["OVA", "ONA", "SPECIAL"] and kaa_type == "tv":
        type_mult = 0.5
    elif af == "TV" and kaa_type in ["ova", "special"]:
        type_mult = 0.5

    return min(1.0, base * year_mult) * type_mult


async def resolve_series(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    cache_key = f"np:kaa:{anilist_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    ctx = ctx or {}
    media = ctx.get("media") or await get_media(anilist_id)
    titles = build_titles(media, ctx.get("anizip"))
    queries = build_kaa_queries(titles)
    season_year = media.get("seasonYear")
    format_val = media.get("format")

    if not queries:
        raise Exception(f"KAA: no usable search queries for AniList {anilist_id}")

    all_candidates = {}
    
    async def search_query(q):
        try:
            results = await kaa_search(q)
            for r in results:
                if r.get("slug") and r["slug"] not in all_candidates:
                    all_candidates[r["slug"]] = r
        except Exception:
            pass

    await asyncio.gather(*[search_query(q) for q in queries])

    if not all_candidates:
        raise Exception(f"KAA: no search results for AniList {anilist_id}")

    scored = []
    for cand in all_candidates.values():
        score = score_candidate(cand, titles, season_year, format_val)
        if score >= 0.5:
            scored.append({
                "slug": cand["slug"],
                "title": cand.get("title_en") or cand.get("title"),
                "locales": cand.get("locales") if isinstance(cand.get("locales"), list) else [],
                "score": score
            })

    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        raise Exception(f"KAA: no confident match for AniList {anilist_id}")

    best = scored[0]
    if best["score"] < 0.6:
        raise Exception(f"KAA: low confidence match for AniList {anilist_id} — best '{best['slug']}' score {best['score']:.3f}")

    data = {
        "slug": best["slug"],
        "title": best["title"],
        "locales": best["locales"],
        "score": best["score"]
    }
    cache.set(cache_key, data, ttl_seconds=86400)
    return data


async def build_ep_map(show_slug: str, show_info: dict) -> List[dict]:
    if show_info.get("type") == "movie":
        watch_uri = show_info.get("watch_uri", "")
        m = re.search(r'/(ep-(\d+)-([a-f0-9]+))$', watch_uri, re.I)
        if m:
            return [{"number": 1, "fullSlug": m.group(1)}]
        return []
    
    episodes = await kaa_all_episodes(show_slug)
    out = []
    for e in episodes:
        num = e.get("episode_number")
        duration_ms = e.get("duration_ms")
        duration = round(duration_ms / 1000) if duration_ms else None
        out.append({
            "number": num,
            "fullSlug": f"ep-{num}-{e.get('slug')}",
            "title": e.get("title"),
            "duration": duration
        })
    return out


async def get_episodes(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    media = ctx.get("media") or await get_media(anilist_id)
    local_ctx = {**ctx, "media": media}
    series = await resolve_series(anilist_id, local_ctx)
    show_info = await kaa_show_info(series["slug"])

    locales = show_info.get("locales") if isinstance(show_info.get("locales"), list) else series["locales"]
    has_dub = "en-US" in locales

    ep_map = await build_ep_map(series["slug"], show_info)
    if not ep_map:
        raise Exception(f"KAA: no episodes found for AniList {anilist_id} (slug: {series['slug']})")

    sub = []
    dub = []
    for ep in ep_map:
        num = ep["number"]
        if not isinstance(num, int) or num < 1:
            continue
        base = {
            "number": num,
            "title": ep.get("title") or f"Episode {num}",
            "duration": ep.get("duration"),
            "filler": False,
            "uncensored": False,
            "description": None,
            "image": None,
            "airDate": None,
        }
        sub.append({"id": f"watch/kaa/{anilist_id}/sub/kaa-{num}", **base, "audio": "sub"})
        if has_dub:
            dub.append({"id": f"watch/kaa/{anilist_id}/dub/kaa-{num}", **base, "audio": "dub"})

    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": "kaa",
            "matchScore": round(series["score"], 3),
        },
        "episodes": {"sub": sub, "dub": dub},
    }


async def handle_watch(anilist_id: int, audio: str, ep_num: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    series = await resolve_series(anilist_id, ctx)
    show_info = await kaa_show_info(series["slug"])

    locales = show_info.get("locales") if isinstance(show_info.get("locales"), list) else series["locales"]
    if audio == "dub" and "en-US" not in locales:
        raise Exception(f"KAA: no English dub for AniList {anilist_id}")

    ep_map = await build_ep_map(series["slug"], show_info)
    ep = next((e for e in ep_map if e["number"] == int(ep_num)), None)
    if not ep:
        raise Exception(f"KAA: episode {ep_num} not found for AniList {anilist_id}")

    episode_data = await kaa_episode_servers(series["slug"], ep["fullSlug"])
    servers = episode_data.get("servers") if isinstance(episode_data.get("servers"), list) else []
    if not servers:
        raise Exception(f"KAA: no streams for episode {ep_num} (AniList {anilist_id})")

    streams = []
    for s in servers:
        src = s.get("src")
        if not src:
            continue
        m = re.search(r'[?&]id=([^&]+)', src)
        if not m:
            continue
        streams.append({
            "url": f"{HLS_BASE}/{m.group(1)}/master.m3u8",
            "type": "hls",
            "server": s.get("name") or "KAA",
            "headers": {"Referer": "https://krussdomi.com/"},
            "priority": 1,
            "isActive": True,
            "iframeUrl": src
        })

    if not streams:
        raise Exception(f"KAA: could not resolve stream for episode {ep_num}")

    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "audio": audio,
        "streams": streams,
    }
