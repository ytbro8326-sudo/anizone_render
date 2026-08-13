import re
import html
import json
import base64
import random
import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, unquote, urlparse
import httpx

from proxies import PROXIES

BASE_URL = "https://www.animegg.org"
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
SHOW_IDENTITY_TTL = 86400


def decode_entities(s: str = "") -> str:
    if not s:
        return ""
    return html.unescape(s).strip()


def strip_tags(html_str: str = "") -> str:
    if not html_str:
        return ""
    clean = re.sub(r"<[^>]*>", " ", html_str)
    clean = re.sub(r"\s+", " ", clean)
    return decode_entities(clean)


def get_attr(tag: str, name: str) -> str:
    m = re.search(r'%s=["\']([^"\']*)["\']' % re.escape(name), tag, re.IGNORECASE)
    return decode_entities(m.group(1)) if m else ""


def norm(s: str = "") -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def dice_coeff(a: str, b: str) -> float:
    na = norm(a)
    nb = norm(b)
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 0.0
    bigrams: Dict[str, int] = {}
    for i in range(len(na) - 1):
        bg = na[i:i+2]
        bigrams[bg] = bigrams.get(bg, 0) + 1
    hits = 0
    for i in range(len(nb) - 1):
        bg = nb[i:i+2]
        count = bigrams.get(bg, 0)
        if count > 0:
            hits += 1
            bigrams[bg] = count - 1
    return (2.0 * hits) / (len(na) + len(nb) - 2)


def title_score(query: str, candidate: str, slug: str) -> float:
    base = max(dice_coeff(query, candidate), dice_coeff(query, slug.replace("-", " ")))
    
    q_norm = norm(query)
    q_num_match = re.search(r'\d+', q_norm)
    query_first_num = q_num_match.group(0) if q_num_match else ""

    s_num_match = re.search(r'\d+', slug)
    slug_first_num = s_num_match.group(0) if s_num_match else ""

    if query_first_num and slug_first_num and query_first_num != slug_first_num:
        return base * 0.65
    if query_first_num and not slug_first_num:
        return base * 0.65
    if not query_first_num and slug_first_num:
        try:
            n = int(slug_first_num)
            if 1 < n < 1900:
                return base * (1 - 0.06 * (n - 1))
        except ValueError:
            pass

    is_movie_query = bool(re.search(r'\b(movie|film|the movie)\b', query, re.IGNORECASE))
    is_movie_match = bool(re.search(r'\b(movie|film)\b', candidate, re.IGNORECASE) or re.search(r'movie|film', slug, re.IGNORECASE))
    if is_movie_query and not is_movie_match:
        return base * 0.4

    q_len = len(q_norm)
    s_len = len(norm(slug.replace("-", " ")))
    return base * 0.8 if s_len > q_len * 1.6 + 4 else base


async def fetch_html(url: str, headers: Optional[dict] = None, referer: Optional[str] = None) -> str:
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        req_headers.update(headers)
    if referer:
        req_headers["Referer"] = referer

    # 1. Try direct connection first
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            res.raise_for_status()
            return res.text
    except Exception as direct_err:
        # 2. Try rotating proxies on 403 or error
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
        startDate { year }
        synonyms
        nextAiringEpisode { episode airingAt timeUntilAiring }
      }
    }
    """
    url = "https://graphql.anilist.co"
    payload = {"query": query, "variables": {"id": int(anilist_id)}}
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    # Direct request first
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                media = data.get("data", {}).get("Media")
                if media:
                    return media
    except Exception:
        pass

    # Proxy retry
    shuffled = list(PROXIES)
    random.shuffle(shuffled)
    for proxy in shuffled:
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=12.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    media = data.get("data", {}).get("Media")
                    if media:
                        return media
        except Exception:
            continue

    raise Exception(f"Failed to fetch AniList media for AniList ID {anilist_id}")


def build_titles(media: dict, anizip: Optional[dict] = None) -> List[str]:
    titles = []
    title_obj = media.get("title") or {}
    if title_obj.get("english"):
        titles.append(title_obj["english"])
    if title_obj.get("romaji"):
        titles.append(title_obj["romaji"])
    if title_obj.get("native"):
        titles.append(title_obj["native"])

    synonyms = media.get("synonyms") or []
    if isinstance(synonyms, list):
        titles.extend(synonyms)

    if anizip and isinstance(anizip.get("titles"), dict):
        az_titles = anizip["titles"]
        if az_titles.get("en"):
            titles.append(az_titles["en"])
        if az_titles.get("x-jat"):
            titles.append(az_titles["x-jat"])
        if az_titles.get("ja"):
            titles.append(az_titles["ja"])

    return [t for t in titles if t]


def expected_count(media: dict, anizip: Optional[dict] = None, jikan_eps: Optional[list] = None) -> Optional[int]:
    counts = []
    if media.get("episodes") and isinstance(media["episodes"], int) and media["episodes"] > 0:
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


def build_search_queries(title: str) -> List[str]:
    queries = {title}
    words = title.strip().split()
    if len(words) > 4:
        queries.add(" ".join(words[:4]))
    if len(words) > 3:
        queries.add(" ".join(words[:3]))
    stripped = re.sub(r'\bseason\s*\d+\b', '', title, flags=re.IGNORECASE)
    stripped = re.sub(r'\bpart\s*\d+\b', '', stripped, flags=re.IGNORECASE)
    stripped = re.sub(r'\b\d+rd\b|\b\d+th\b|\b\d+st\b|\b\d+nd\b', '', stripped, flags=re.IGNORECASE)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    if stripped and stripped != title:
        queries.add(stripped)
    return [q for q in queries if len(q) >= 3]


async def find_top_slugs(titles: List[str], search_fn_param, n: int = 6) -> List[dict]:
    all_candidates: Dict[str, str] = {}
    search_queries: Set[str] = set()
    for title in titles[:4]:
        for q in build_search_queries(title):
            search_queries.add(q)
    
    tasks = [search_fn_param(q) for q in search_queries]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results_list:
        if isinstance(res, list):
            for r in res:
                if r["slug"] not in all_candidates:
                    all_candidates[r["slug"]] = r["text"]

    scored = []
    for slug, text in all_candidates.items():
        best = 0.0
        for title in titles[:2]:
            best = max(best, title_score(title, text, slug))
        if best >= 0.5:
            scored.append({"slug": slug, "title": text, "score": best})
            
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]


async def get_prequel_offset(anilist_id: int) -> int:
    query = """
    query($id:Int){
      Media(id:$id,type:ANIME){
        relations{
          edges{
            relationType(version:2)
            node{
              id type episodes
              relations{
                edges{
                  relationType(version:2)
                  node{
                    id type episodes
                    relations{
                      edges{
                        relationType(version:2)
                        node{ id type episodes }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    url = "https://graphql.anilist.co"
    payload = {"query": query, "variables": {"id": int(anilist_id)}}
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                relations = data.get("data", {}).get("Media", {}).get("relations")
                
                def compute_offset(rel, depth=0):
                    if not rel or depth > 5:
                        return 0
                    edges = rel.get("edges") or []
                    prequel_edge = next(
                        (e for e in edges if e.get("relationType") == "PREQUEL" 
                         and (e.get("node") or {}).get("type") == "ANIME" 
                         and ((e.get("node") or {}).get("episodes") or 0) >= 5),
                        None
                    )
                    if not prequel_edge:
                        return 0
                    node = prequel_edge.get("node") or {}
                    episodes = node.get("episodes") or 0
                    return episodes + compute_offset(node.get("relations"), depth + 1)

                return compute_offset(relations)
    except Exception:
        pass
    return 0


async def select_series(candidates: list, scrape_series_fn, expected: Optional[int], status: Optional[str], offset: int, options: Optional[dict] = None) -> Optional[dict]:
    options = options or {}
    
    async def evaluate_candidate(candidate):
        episodes = await scrape_series_fn(candidate["slug"])
        max_num = max([e["number"] for e in episodes], default=0)
        local_hits = len([e for e in episodes if 1 <= e["number"] <= expected]) if expected else len(episodes)
        offset_hits = len([e for e in episodes if offset < e["number"] <= offset + expected]) if expected and offset else 0
        
        mode = "offset" if offset_hits > local_hits else "local"
        hits = max(local_hits, offset_hits)
        
        count_score = 1.0
        if expected and expected >= 6:
            needed = int(expected * 0.9) if status == "FINISHED" else max(1, expected - 3)
            count_score = 1.0 if hits >= needed else hits / float(needed)
            
        score = candidate["score"] * 0.7 + count_score * 0.3
        return {**candidate, "episodes": episodes, "max": max_num, "mode": mode, "score": score}

    tasks = [evaluate_candidate(c) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    min_score = options.get("minScore", 0.65)
    viable = [
        r for r in results 
        if isinstance(r, dict) and r.get("episodes") and r.get("score", 0) >= min_score
    ]
    if not viable:
        return None
    viable.sort(key=lambda x: x["score"], reverse=True)
    return viable[0]


async def search(query: str) -> List[dict]:
    try:
        html_content = await fetch_html(f"{BASE_URL}/search/?q={quote(query)}")
    except Exception:
        return []

    results = []
    matches = re.finditer(r"""<a\b[^>]*class=["'][^"']*mse[^"']*["'][^>]*>[\s\S]*?</a>""", html_content, re.IGNORECASE)
    for m in matches:
        full_block = m.group(0)
        tag_match = re.search(r"""<a\b[^>]*>""", full_block, re.IGNORECASE)
        tag = tag_match.group(0) if tag_match else ""
        href = get_attr(tag, "href")
        slug_match = re.search(r"""^\/series\/([^/?#]+)""", href)
        if not slug_match:
            continue
        slug = slug_match.group(1)
        
        strong_match = re.search(r"""<strong[^>]*>([\s\S]*?)</strong>""", full_block, re.IGNORECASE)
        title = strip_tags(strong_match.group(1)) if strong_match else slug.replace("-", " ")
        results.append({"slug": slug, "text": title})

    return results


async def search_fn(query: str) -> List[dict]:
    r1 = await search(query)
    words = query.split()
    compact = re.sub(r"""[^a-zA-Z0-9]""", '', words[0]) if words else ""
    if len(compact) >= 4 and compact.lower() != query.lower():
        try:
            r2 = await search(compact)
            seen = {r["slug"] for r in r1}
            for r in r2:
                if r["slug"] not in seen:
                    r1.append(r)
        except Exception:
            pass
    return r1


async def scrape_series(slug: str) -> list:
    try:
        html_content = await fetch_html(f"{BASE_URL}/series/{slug}")
    except Exception:
        return []

    episodes = []
    blocks = re.findall(r"""<li\b[^>]*>([\s\S]*?)</li>""", html_content, re.IGNORECASE)
    for block in blocks:
        if not re.search(r"""\banm_det_pop\b""", block):
            continue
        link_m = re.search(r"""<a\b[^>]*class=["'][^"']*anm_det_pop[^"']*["'][^>]*>""", block, re.IGNORECASE)
        link = link_m.group(0) if link_m else ""
        href = get_attr(link, "href")
        href = re.sub(r"""#.*$""", '', href).lstrip('/')

        strong_m = re.search(r"""<strong[^>]*>([\s\S]*?)</strong>""", block, re.IGNORECASE)
        strong = strip_tags(strong_m.group(1)) if strong_m else ""

        range_match = re.search(r"""(\d+)-(\d+)\s*$""", strong)
        num_match = range_match or re.search(r"""(\d+)\s*$""", strong)
        if not num_match or not href:
            continue
        number = int(num_match.group(1))

        title_m = re.search(r"""<i\b[^>]*class=["'][^"']*anititle[^"']*["'][^>]*>([\s\S]*?)</i>""", block, re.IGNORECASE)
        title = strip_tags(title_m.group(1)) if title_m else strong

        audio = []
        if re.search(r"""\bbtn-subbed\b""", block):
            audio.append("sub")
        if re.search(r"""\bbtn-dubbed\b""", block):
            audio.append("dub")

        episodes.append({
            "number": number,
            "title": title,
            "epSlug": href,
            "hasSub": "sub" in audio,
            "hasDub": "dub" in audio
        })

    episodes.sort(key=lambda x: x["number"])
    seen = set()
    out = []
    for e in episodes:
        if e["number"] not in seen:
            seen.add(e["number"])
            out.append(e)
    return out


async def scrape_embed(embed_id: str) -> list:
    try:
        html_content = await fetch_html(f"{BASE_URL}/embed/{embed_id}", referer=BASE_URL)
    except Exception:
        return []

    m = re.search(r"""var\s+videoSources\s*=\s*(\[[\s\S]*?\]);""", html_content)
    if not m:
        return []

    parsed = []
    try:
        as_json = m.group(1)
        as_json = re.sub(r"""([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:""", r'\1"\2":', as_json)
        as_json = re.sub(r""":\s*'([^']*)'""", r': "\1"', as_json)
        parsed = json.loads(as_json)
    except Exception:
        return []

    results = []
    for s in parsed:
        backup = None
        if s.get("bk"):
            try:
                raw_b64 = base64.b64decode(s["bk"]).decode('utf-8', errors='ignore')
                backup = unquote(raw_b64)
            except Exception:
                backup = None

        file_url = s.get("file", "")
        if file_url:
            full_url = file_url if file_url.startswith("http") else f"{BASE_URL}{file_url}"
            results.append({
                "quality": s.get("label", "unknown"),
                "url": full_url,
                "backup": backup
            })

    return results


async def scrape_episode_watch(ep_slug: str, audio: str) -> dict:
    try:
        html_content = await fetch_html(f"{BASE_URL}/{ep_slug}", referer=BASE_URL)
    except Exception:
        return {"title": "", "streams": []}

    title_m = re.search(r"""<div\b[^>]*class=["'][^"']*info[^"']*["'][^>]*>[\s\S]*?<a[^>]*>([\s\S]*?)</a>""", html_content, re.IGNORECASE)
    title = strip_tags(title_m.group(1)) if title_m else ""

    tabs = []
    matches = re.finditer(r"""<a\b[^>]*data-toggle=["']tab["'][^>]*>""", html_content, re.IGNORECASE)
    for m in matches:
        tag = m.group(0)
        embed_id = get_attr(tag, "data-id")
        server = get_attr(tag, "data-mirror") or "AnimeGG"
        version = get_attr(tag, "data-version") or "subbed"
        if not embed_id:
            continue
        normalized = "dub" if version.startswith("dub") else "sub"
        if audio == "all" or normalized == audio:
            tabs.append({
                "embedId": embed_id,
                "embedUrl": f"{BASE_URL}/embed/{embed_id}",
                "server": server,
                "normalized": normalized
            })

    tasks = [scrape_embed(t["embedId"]) for t in tabs]
    embed_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_streams = []
    for i, (tab, res) in enumerate(zip(tabs, embed_results)):
        sources = res if isinstance(res, list) else []
        parsed_origin = f"{urlparse(tab['embedUrl']).scheme}://{urlparse(tab['embedUrl']).netloc}/"
        for j, s in enumerate(sources):
            stream_url = s.get("url", "")
            is_hls = ".m3u8" in stream_url
            all_streams.append({
                "url": stream_url,
                "type": "hls" if is_hls else "mp4",
                "quality": s.get("quality", "unknown"),
                "backup": s.get("backup"),
                "audio": tab["normalized"],
                "server": tab["server"],
                "embed": tab["embedUrl"],
                "referer": parsed_origin,
                "priority": len(tabs) - i,
                "isActive": i == 0 and j == 0
            })
        all_streams.append({
            "url": tab["embedUrl"],
            "type": "embed",
            "audio": tab["normalized"],
            "server": f"{tab['server']}-embed",
            "referer": parsed_origin,
            "priority": 1,
            "isActive": False
        })

    return {"title": title, "streams": all_streams}


async def resolve_series(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    cache_key = f"np:animegg:{anilist_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    media = ctx.get("media") or await get_media(anilist_id)
    titles = build_titles(media, ctx.get("anizip"))
    candidates = await find_top_slugs(titles, search_fn)
    expected = expected_count(media, ctx.get("anizip"), ctx.get("jikanEps"))
    offset = await get_prequel_offset(anilist_id)
    
    fmt = str(media.get("format") or "").upper()
    is_single_movie = fmt == "MOVIE" or expected == 1
    
    selected = await select_series(candidates, scrape_series, expected, media.get("status"), offset, {
        "minScore": 0.9 if is_single_movie else 0.65
    })
    if not selected:
        raise Exception(f"AnimeGG match not found for AniList {anilist_id}")

    data = {
        "slug": selected["slug"],
        "title": selected["title"],
        "mode": selected["mode"],
        "offset": offset,
        "score": selected["score"]
    }
    cache.set(cache_key, data, SHOW_IDENTITY_TTL)
    return data


def build_episode_lists(anilist_id: int, series: dict, provider_episodes: list, ctx: dict, expected: Optional[int]) -> dict:
    sub = []
    dub = []
    for src in provider_episodes:
        number = src["number"] - series["offset"] if series["mode"] == "offset" else src["number"]
        if number < 1:
            continue
        if expected and number > expected:
            continue
        meta = episode_meta(number, ctx)
        base = {
            "number": number,
            "title": meta.get("title") or src.get("title") or f"Episode {number}",
            "duration": meta.get("duration"),
            "filler": meta.get("filler"),
            "uncensored": meta.get("uncensored"),
            "description": meta.get("description"),
            "image": meta.get("image"),
            "airDate": meta.get("airDate"),
            "sourceNumber": src["number"],
        }
        if src.get("hasSub"):
            sub.append({
                **base,
                "id": f"watch/animegg/{anilist_id}/sub/animegg-{number}",
                "audio": "sub"
            })
        if src.get("hasDub"):
            dub.append({
                **base,
                "id": f"watch/animegg/{anilist_id}/dub/animegg-{number}",
                "audio": "dub"
            })
    return {"sub": sub, "dub": dub}


async def get_episodes(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    media = ctx.get("media") or await get_media(anilist_id)
    local_ctx = {**ctx, "media": media}
    series = await resolve_series(anilist_id, local_ctx)
    episodes = await scrape_series(series["slug"])
    expected = expected_count(media, ctx.get("anizip"), ctx.get("jikanEps"))

    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": "animegg",
            "matchScore": round(float(series["score"]), 3),
            "numbering": series["mode"],
            "episodeOffset": series["offset"] if series["mode"] == "offset" else 0,
        },
        "episodes": build_episode_lists(anilist_id, series, episodes, local_ctx, expected),
    }


async def handle_watch(anilist_id: int, audio: str, ep_num: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    series = await resolve_series(anilist_id, ctx)
    provider_ep = int(ep_num) + series["offset"] if series["mode"] == "offset" else int(ep_num)
    episodes = await scrape_series(series["slug"])
    ep = next((e for e in episodes if e["number"] == provider_ep), None)
    if not ep:
        return {"error": f"AnimeGG episode {provider_ep} not found", "status": 404}

    watch = await scrape_episode_watch(ep["epSlug"], audio)
    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "providerEpisode": provider_ep,
        "audio": audio,
        "title": watch.get("title", ""),
        "streams": watch.get("streams", [])
    }
