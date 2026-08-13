import re
import html
import json
import math
import asyncio
import time
import tempfile
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse
import httpx

BASE = "https://anidb.app"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
COOKIE_JAR = os.path.join(tempfile.gettempdir(), "anidbapp_cookies.txt")

NAV_HEADERS = [
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language: en-US,en;q=0.9",
    'sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile: ?0",
    'sec-ch-ua-platform: "Windows"',
    "sec-fetch-dest: document",
    "sec-fetch-mode: navigate",
    "sec-fetch-site: none",
    "sec-fetch-user: ?1",
    "upgrade-insecure-requests: 1",
]

XHR_HEADERS = [
    "Accept: application/json, text/html, */*;q=0.8",
    "Accept-Language: en-US,en;q=0.9",
    'sec-ch-ua: "Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-mobile: ?0",
    'sec-ch-ua-platform: "Windows"',
    "sec-fetch-dest: empty",
    "sec-fetch-mode: cors",
    "sec-fetch-site: same-origin",
    "X-Requested-With: XMLHttpRequest",
]


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


def attr(tag_str: str, name: str) -> str:
    m = re.search(r'\b' + re.escape(name) + r'=["\']([^"\']*)["\']', tag_str, re.IGNORECASE)
    return m.group(1) if m else ""


def strip_tags(html_str: str = "") -> str:
    if not html_str:
        return ""
    clean = re.sub(r'<[^>]*>', '', html_str)
    return html.unescape(clean).strip()


def decode_entities(s: str = "") -> str:
    if not s:
        return ""
    return html.unescape(s).strip()


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
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"id": int(anilist_id)}},
            headers={"Content-Type": "application/json", "User-Agent": UA}
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
        "image": az_ep.get("image") or jk_ep.get("image_url"),
        "airDate": az_ep.get("airdate") or jk_ep.get("aired"),
    }


async def curl_fetch(url: str, headers: List[str], extra_args: Optional[List[str]] = None) -> str:
    extra_args = extra_args or []
    header_args = []
    for h in headers:
        header_args.extend(["-H", h])
    
    args = [
        "-s",
        "--compressed",
        "-A", UA,
        "-c", COOKIE_JAR,
        "-b", COOKIE_JAR,
        "-w", "\n__STATUS:%{http_code}",
        *header_args,
        *extra_args,
        url
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        stdout_str = stdout.decode("utf-8", errors="ignore")
        
        sep = stdout_str.rfind("\n__STATUS:")
        if sep >= 0:
            status = int(stdout_str[sep + 10:].strip())
            body = stdout_str[:sep]
        else:
            status = 0
            body = stdout_str

        if status < 200 or status >= 300:
            raise Exception(f"HTTP {status} fetching {url}")
        return body
    except FileNotFoundError:
        req_headers = {"User-Agent": UA}
        for h in headers:
            if ":" in h:
                k, v = h.split(":", 1)
                req_headers[k.strip()] = v.strip()
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code < 200 or res.status_code >= 300:
                raise Exception(f"HTTP {res.status_code} fetching {url}")
            return res.text


PROXY_URL = os.environ.get("PROXY_URL", "https://old-sun-d12a.andruilsyestems.workers.dev").rstrip("/")


async def fetch_anidb_html(url: str, referer: Optional[str] = None) -> str:
    if PROXY_URL:
        proxy_endpoint = f"{PROXY_URL}/?url={quote(url, safe='')}"
        if referer:
            proxy_endpoint += f"&ref={quote(referer, safe='')}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(proxy_endpoint, headers={"User-Agent": UA})
            if res.status_code < 200 or res.status_code >= 300:
                raise Exception(f"HTTP {res.status_code} fetching via proxy: {url}")
            return res.text
    headers = list(NAV_HEADERS)
    if referer:
        headers.append(f"Referer: {referer}")
    return await curl_fetch(url, headers)


async def fetch_xhr(url: str, referer: Optional[str] = None) -> str:
    if PROXY_URL:
        proxy_endpoint = f"{PROXY_URL}/?url={quote(url, safe='')}"
        if referer:
            proxy_endpoint += f"&ref={quote(referer, safe='')}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(proxy_endpoint, headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
            if res.status_code < 200 or res.status_code >= 300:
                raise Exception(f"HTTP {res.status_code} fetching via proxy: {url}")
            return res.text
    headers = list(XHR_HEADERS)
    if referer:
        headers.append(f"Referer: {referer}")
    return await curl_fetch(url, headers)


async def fetch_json(url: str, referer: Optional[str] = None) -> Any:
    text = await fetch_xhr(url, referer)
    return json.loads(text)


async def search(query: str) -> List[dict]:
    try:
        html_str = await fetch_xhr(f"{BASE}/search/suggestions?q={quote(query)}", f"{BASE}/home")
    except Exception:
        html_str = ""

    results = []
    for m in re.finditer(r'<a\b[^>]*data-search-item\b[^>]*>[\s\S]*?</a>', html_str, re.IGNORECASE):
        item_html = m.group(0)
        tag_m = re.search(r'<a\b[^>]*>', item_html, re.IGNORECASE)
        tag = tag_m.group(0) if tag_m else ""
        href = attr(tag, "href")
        
        path = urlparse(href).path if href.startswith("http") else href
        slug_m = re.search(r'^\/anime\/([^/?#]+)', path)
        if not slug_m:
            continue
        slug = slug_m.group(1)

        p_sm = re.search(r"""<p\b[^>]*class=["']\s*[^"']*text-sm[^"']*["'][^>]*>([\s\S]*?)</p>""", item_html, re.IGNORECASE)
        title = strip_tags(p_sm.group(1) if p_sm else "")

        p_xs = re.search(r"""<p\b[^>]*class=["']\s*[^"']*text-xs[^"']*["'][^>]*>([\s\S]*?)</p>""", item_html, re.IGNORECASE)
        meta = strip_tags(p_xs.group(1) if p_xs else "")

        site_id_m = re.search(r'-(\d+)$', slug)
        site_id = int(site_id_m.group(1)) if site_id_m else None

        results.append({
            "slug": slug,
            "title": title or slug.replace("-", " "),
            "meta": meta,
            "siteId": site_id
        })

    if results:
        return results

    try:
        browse_html = await fetch_anidb_html(f"{BASE}/browse?q={quote(query)}", f"{BASE}/home")
    except Exception:
        browse_html = ""

    seen = set()
    for m in re.finditer(
        r"""<a\b[^>]*href=["'](?:https:\/\/anidb\.app)?\/anime\/([^"']+)["'][^>]*class=["'][^"']*\banime-card\b[^"']*["'][^>]*>[\s\S]*?</a>""",
        browse_html, re.IGNORECASE
    ):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        card_html = m.group(0)

        t_m = (re.search(r"""title=["']([^"']+)["']""", card_html, re.IGNORECASE) or
               re.search(r"""alt=["']([^"']+)["']""", card_html, re.IGNORECASE))
        title = strip_tags(t_m.group(1)) if t_m else slug.replace("-", " ")

        site_id_m = re.search(r'-(\d+)$', slug)
        site_id = int(site_id_m.group(1)) if site_id_m else None

        results.append({
            "slug": slug,
            "title": title,
            "meta": "",
            "siteId": site_id
        })

    return results


def parse_external_ids(html_str: str) -> dict:
    an_m = re.search(r'https:\/\/anilist\.co\/anime\/(\d+)', html_str, re.IGNORECASE)
    mal_m = re.search(r'https:\/\/myanimelist\.net\/anime\/(\d+)', html_str, re.IGNORECASE)
    ad_m = re.search(r'https:\/\/anidb\.net\/anime\/(\d+)', html_str, re.IGNORECASE)
    kit_m = re.search(r'https:\/\/kitsu\.app\/anime\/(\d+)', html_str, re.IGNORECASE)
    return {
        "anilistId": int(an_m.group(1)) if an_m else None,
        "malId": int(mal_m.group(1)) if mal_m else None,
        "anidbId": int(ad_m.group(1)) if ad_m else None,
        "kitsuId": int(kit_m.group(1)) if kit_m else None,
    }


def parse_page_title(html_str: str) -> str:
    m = re.search(r'<h1\b[^>]*>([\s\S]*?)</h1>', html_str, re.IGNORECASE)
    return strip_tags(m.group(1)) if m else ""


def search_queries(media: dict, anizip: Optional[dict] = None) -> List[str]:
    titles = build_titles(media, anizip)
    out = []
    seen = set()
    for title in titles[:5]:
        if title and title not in seen:
            seen.add(title)
            out.append(title)
        words = title.strip().split() if title else []
        if len(words) > 4:
            w_str = " ".join(words[:4])
            if w_str not in seen:
                seen.add(w_str)
                out.append(w_str)
    return [q for q in out if len(q) >= 2]


async def resolve_series(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    cache_key = f"np:anidbapp:{anilist_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    media = ctx.get("media") or await get_media(anilist_id)
    queries = search_queries(media, ctx.get("anizip"))
    
    candidates: Dict[str, dict] = {}
    
    async def run_search(q: str):
        try:
            res = await search(q)
            for r in res:
                if r["slug"] not in candidates:
                    candidates[r["slug"]] = r
        except Exception:
            pass

    await asyncio.gather(*(run_search(q) for q in queries))

    for candidate in candidates.values():
        try:
            html_str = await fetch_anidb_html(f"{BASE}/anime/{candidate['slug']}", f"{BASE}/home")
        except Exception:
            html_str = ""
        if not html_str:
            continue
        ids = parse_external_ids(html_str)
        if ids.get("anilistId") == int(anilist_id):
            site_id_m = re.search(r'-(\d+)$', candidate["slug"])
            site_id = candidate.get("siteId") or (int(site_id_m.group(1)) if site_id_m else None)
            data = {
                "slug": candidate["slug"],
                "siteId": site_id,
                "title": parse_page_title(html_str) or candidate.get("title", ""),
                "matchType": "anilist",
                "matchScore": 1,
                **ids
            }
            cache.set(cache_key, data, SHOW_IDENTITY_TTL)
            return data

    mal_id = media.get("idMal") if media else None
    if mal_id:
        for candidate in candidates.values():
            try:
                html_str = await fetch_anidb_html(f"{BASE}/anime/{candidate['slug']}", f"{BASE}/home")
            except Exception:
                html_str = ""
            if not html_str:
                continue
            ids = parse_external_ids(html_str)
            if ids.get("anilistId") or ids.get("malId") != int(mal_id):
                continue
            site_id_m = re.search(r'-(\d+)$', candidate["slug"])
            site_id = candidate.get("siteId") or (int(site_id_m.group(1)) if site_id_m else None)
            data = {
                "slug": candidate["slug"],
                "siteId": site_id,
                "title": parse_page_title(html_str) or candidate.get("title", ""),
                "matchType": "mal",
                "matchScore": 0.9,
                **ids
            }
            cache.set(cache_key, data, SHOW_IDENTITY_TTL)
            return data

    raise Exception(f"AniDB.app match not found for AniList {anilist_id}")


async def fetch_provider_episodes(site_id: int) -> List[dict]:
    data = await fetch_json(f"{BASE}/api/frontend/anime/{site_id}/episodes", f"{BASE}/anime/{site_id}")
    if isinstance(data, dict) and isinstance(data.get("episodes"), list):
        return data["episodes"]
    return []


def infer_offset(provider_episodes: List[dict], expected: Optional[int]) -> int:
    nums = []
    for e in provider_episodes:
        try:
            n = float(e.get("number"))
            if math.isfinite(n) and n > 0:
                nums.append(int(n))
        except (TypeError, ValueError):
            pass
    if not nums or not expected:
        return 0
    min_val = min(nums)
    max_val = max(nums)
    if min_val > expected:
        return min_val - 1
    if min_val > 1 and (max_val - min_val + 1) >= expected:
        return min_val - 1
    return 0


async def fetch_languages(episode_id: Any, series_slug: str) -> List[dict]:
    try:
        data = await fetch_json(f"{BASE}/api/frontend/episode/{episode_id}/languages", f"{BASE}/anime/{series_slug}")
        if isinstance(data, dict) and isinstance(data.get("languages"), list):
            return data["languages"]
    except Exception:
        pass
    return []


def language_for_audio(languages: List[dict], audio: str) -> Optional[dict]:
    preferred = ["jpn", "ja", "japanese"] if audio == "sub" else ["eng", "en", "english"]
    for l in languages:
        code = str(l.get("code") or "").lower()
        if code in preferred:
            return l
    for l in languages:
        name = str(l.get("name") or "").lower()
        if name in preferred:
            return l
    return None


def has_language(languages: List[dict], audio: str) -> bool:
    lang = language_for_audio(languages, audio)
    return bool(lang and lang.get("embed_url"))


def build_episode_lists(anilist_id: int, provider_episodes: List[dict], ctx: dict, expected: Optional[int], offset: int, availability: dict) -> dict:
    sub = []
    dub = []
    for src in provider_episodes:
        try:
            source_number = int(float(src.get("number")))
        except (TypeError, ValueError):
            continue
        number = source_number - offset
        if number < 1:
            continue
        if expected and number > expected:
            continue
        
        meta = episode_meta(number, ctx)
        base = {
            "number": number,
            "title": meta.get("title") or f"Episode {number}",
            "duration": meta.get("duration"),
            "filler": src.get("filler", meta.get("filler")),
            "uncensored": meta.get("uncensored"),
            "description": meta.get("description"),
            "image": meta.get("image"),
            "airDate": meta.get("airDate"),
            "sourceNumber": source_number,
            "sourceId": src.get("id"),
        }
        if availability.get("hasSub"):
            sub.append({
                **base,
                "id": f"watch/anidbapp/{anilist_id}/sub/anidbapp-{number}",
                "audio": "sub"
            })
        if availability.get("hasDub"):
            dub.append({
                **base,
                "id": f"watch/anidbapp/{anilist_id}/dub/anidbapp-{number}",
                "audio": "dub"
            })
    return {"sub": sub, "dub": dub}


def extract_hls(html_str: str) -> Optional[str]:
    patterns = [
        r"""file\s*:\s*["'](https?:\/\/[^"']+\.m3u8[^"']*)["']""",
        r"""sources\s*:\s*\[\s*\{[^}]*file\s*:\s*["'](https?:\/\/[^"']+\.m3u8[^"']*)["']""",
        r"""["'](https?:\/\/[^"']+\/master\.m3u8[^"']*)["']""",
        r"""["'](https?:\/\/[^"']+\.m3u8[^"']*)["']""",
    ]
    for pattern in patterns:
        m = re.search(pattern, html_str, re.IGNORECASE)
        if m and m.group(1):
            return decode_entities(m.group(1))
    return None


async def streams_for_embed(embed_url: str, audio: str, language: dict) -> List[dict]:
    try:
        html_str = await fetch_anidb_html(embed_url, referer=f"{BASE}/")
    except Exception:
        html_str = ""

    hls = extract_hls(html_str) if html_str else None
    streams = []
    lang_code = language.get("code") if isinstance(language, dict) else None

    if hls:
        parsed = urlparse(embed_url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        streams.append({
            "url": hls,
            "type": "hls",
            "audio": audio,
            "language": lang_code,
            "server": "AniDB.app",
            "embed": embed_url,
            "referer": origin,
            "priority": 5,
            "isActive": True,
        })

    streams.append({
        "url": embed_url,
        "type": "embed",
        "audio": audio,
        "language": lang_code,
        "server": "AniDB.app-embed",
        "referer": f"{BASE}/",
        "priority": 4,
        "isActive": not bool(hls),
    })

    return streams


async def get_episodes(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    media = ctx.get("media") or await get_media(anilist_id)
    local_ctx = {**ctx, "media": media}
    series = await resolve_series(anilist_id, local_ctx)
    episodes = await fetch_provider_episodes(series["siteId"])
    expected = expected_count(media, ctx.get("anizip"), ctx.get("jikanEps"))
    offset = infer_offset(episodes, expected)

    sample_languages = []
    if episodes:
        for ep in episodes[:5]:
            ep_id = ep.get("id") if isinstance(ep, dict) else None
            if ep_id:
                langs = await fetch_languages(ep_id, series["slug"])
                sample_languages.extend(langs)

    availability = {
        "hasSub": has_language(sample_languages, "sub") or not sample_languages,
        "hasDub": has_language(sample_languages, "dub"),
    }

    return {
        "meta": {
            "id": series["slug"],
            "siteId": series["siteId"],
            "title": series["title"],
            "source": "anidbapp",
            "matchScore": series.get("matchScore"),
            "matchType": series.get("matchType"),
            "anilistId": series.get("anilistId"),
            "malId": series.get("malId"),
            "numbering": "offset" if offset else "local",
            "episodeOffset": offset,
        },
        "episodes": build_episode_lists(anilist_id, episodes, local_ctx, expected, offset, availability)
    }


async def handle_watch(anilist_id: int, audio: str, ep_num: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    series = await resolve_series(anilist_id, ctx)
    episodes = await fetch_provider_episodes(series["siteId"])
    try:
        media = ctx.get("media") or await get_media(anilist_id)
    except Exception:
        media = None

    expected = expected_count(media, ctx.get("anizip"), ctx.get("jikanEps"))
    offset = infer_offset(episodes, expected)
    provider_ep = int(ep_num) + offset

    episode = None
    for e in episodes:
        try:
            if int(float(e.get("number"))) == provider_ep:
                episode = e
                break
        except (TypeError, ValueError):
            continue

    if not episode:
        return {"error": f"AniDB.app episode {ep_num} not found", "status": 404}

    languages = await fetch_languages(episode.get("id"), series["slug"])
    
    aud_str = str(audio or "both").lower()
    if aud_str == "sub":
        audios_to_fetch = ["sub"]
    elif aud_str == "dub":
        audios_to_fetch = ["dub"]
    else:
        audios_to_fetch = ["sub", "dub"]
    all_streams = []
    used_lang_codes = []

    for aud in audios_to_fetch:
        language = language_for_audio(languages, aud)
        if language and language.get("embed_url"):
            embed_url = decode_entities(language.get("embed_url"))
            st = await streams_for_embed(embed_url, aud, language)
            all_streams.extend(st)
            if language.get("code"):
                used_lang_codes.append(language.get("code"))

    return {
        "anilistId": int(anilist_id),
        "episode": int(ep_num),
        "providerEpisode": provider_ep,
        "audio": audio,
        "language": ",".join(used_lang_codes) if used_lang_codes else None,
        "streams": all_streams
    }
