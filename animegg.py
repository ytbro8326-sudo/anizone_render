"""
AnimeGG Stream Extractor & Multi-Dataset Search Module
=====================================================
Searches MAL ID and Episode across 6 AnimeGG series datasets on GitHub:
- animegg_series.json
- animegg_series2.json
- animegg_series3.json
- animegg_series4.json
- animegg_series5.json
- animegg_series6.json

Extracts direct MP4/HLS video streams from AnimeGG embed URLs (e.g. https://www.animegg.org/embed/27657).
"""

import re
import json
import time
import urllib.request
import urllib.error
import concurrent.futures
from typing import Dict, List, Optional, Any

DATASET_URLS = [
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series.json",
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series2.json",
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series3.json",
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series4.json",
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series5.json",
    "https://raw.githubusercontent.com/dokkarrr/final_animgeg_embed-scraper/refs/heads/main/output/animegg_series6.json",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

EMBED_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PLAY_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Range": "bytes=0-",
}

CDN_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.animegg.org/",
    "Range": "bytes=0-",
}


class NoRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirection())

_DATASET_CACHE: List[dict] = []
_CACHE_TIME: float = 0.0
CACHE_TTL: float = 3600.0


def resolve_final_url(proxy_url: str, referer: str) -> Optional[str]:
    """Follow animegg /play/ → vidcache:8161 → sN.vidcache:8166 (2 hops) using urllib."""
    headers = dict(PLAY_HEADERS)
    headers["Referer"] = referer

    try:
        req1 = urllib.request.Request(proxy_url, headers=headers)
        vidcache_url = None
        try:
            resp1 = _NO_REDIRECT_OPENER.open(req1, timeout=12)
            vidcache_url = proxy_url
        except urllib.error.HTTPError as e1:
            if e1.code in (301, 302, 303, 307, 308):
                vidcache_url = e1.headers.get("Location", "")

        if not vidcache_url:
            return None

        req2 = urllib.request.Request(vidcache_url, headers=CDN_HEADERS)
        try:
            resp2 = _NO_REDIRECT_OPENER.open(req2, timeout=12)
            return vidcache_url
        except urllib.error.HTTPError as e2:
            if e2.code in (301, 302, 303, 307, 308):
                return e2.headers.get("Location", vidcache_url)
            return vidcache_url
    except Exception:
        return None


def extract_animegg_embed(embed_url: str) -> dict:
    """Extract direct video stream URLs from an AnimeGG embed link."""
    try:
        req = urllib.request.Request(embed_url, headers=EMBED_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")

        vs_match = re.search(r"var videoSources\s*=\s*(\[.*?\])\s*;", html, re.DOTALL)
        if not vs_match:
            return {}

        raw = vs_match.group(1)
        sources = re.findall(r'\{file:\s*"([^"]+)".*?label:\s*"([^"]+)"', raw, re.DOTALL)

        results = {}
        for file_path, label in sources:
            proxy_url = "https://www.animegg.org" + file_path if file_path.startswith("/") else file_path
            final = resolve_final_url(proxy_url, embed_url)
            if final:
                results[label] = final

        return results
    except Exception:
        return {}


def _fetch_dataset(url: str) -> list:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


def search_animegg_datasets(mal_id: int) -> Optional[dict]:
    """Search for MAL ID in AnimeGG series datasets in parallel with early exit & caching."""
    global _DATASET_CACHE, _CACHE_TIME

    if _DATASET_CACHE and (time.time() - _CACHE_TIME < CACHE_TTL):
        for entry in _DATASET_CACHE:
            if entry.get("mal_id") == mal_id:
                return entry

    found_entry = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_fetch_dataset, url) for url in DATASET_URLS]
        for future in concurrent.futures.as_completed(futures):
            dataset = future.result()
            if dataset:
                _DATASET_CACHE.extend(dataset)
                _CACHE_TIME = time.time()
                if not found_entry:
                    for entry in dataset:
                        if entry.get("mal_id") == mal_id:
                            found_entry = entry
                            break

    return found_entry


def get_animegg_streams_by_mal_id(mal_id: int, ep_num: int) -> dict:
    """Get stream links for a given MAL ID and Episode Number."""
    anime_entry = search_animegg_datasets(mal_id)
    if not anime_entry:
        raise RuntimeError(f"MAL ID {mal_id} not found in AnimeGG datasets")

    title = anime_entry.get("title", f"Anime {mal_id}")
    episodes = anime_entry.get("episodes", [])

    matching_ep = None
    for ep in episodes:
        if ep.get("ep") == ep_num:
            matching_ep = ep
            break

    if not matching_ep:
        raise RuntimeError(f"Episode {ep_num} for MAL ID {mal_id} ('{title}') not found in AnimeGG dataset")

    sub_embed = matching_ep.get("sub")
    dub_embed = matching_ep.get("dub")

    streams = []

    if sub_embed:
        sub_res = extract_animegg_embed(sub_embed)
        for label, url in sub_res.items():
            streams.append({
                "server": f"AnimeGG SUB ({label})",
                "url": url,
                "type": "mp4",
                "quality": f"SUB {label}",
                "embed_url": sub_embed
            })

    if dub_embed:
        dub_res = extract_animegg_embed(dub_embed)
        for label, url in dub_res.items():
            streams.append({
                "server": f"AnimeGG DUB ({label})",
                "url": url,
                "type": "mp4",
                "quality": f"DUB {label}",
                "embed_url": dub_embed
            })

    if not streams:
        raise RuntimeError(f"No direct stream URLs resolved for MAL ID {mal_id} Ep {ep_num}")

    return {
        "status": "success",
        "server": "AnimeGG",
        "malId": mal_id,
        "episode": ep_num,
        "animeTitle": title,
        "subEmbed": sub_embed,
        "dubEmbed": dub_embed,
        "results": {
            "stream_url": streams[0]["url"],
            "streams": streams
        }
    }


if __name__ == "__main__":
    import sys
    mal_input = 21
    ep_input = 1
    if len(sys.argv) > 1:
        try:
            mal_input = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            ep_input = int(sys.argv[2])
        except ValueError:
            pass
    print(f"Searching AnimeGG for MAL ID {mal_input} Ep {ep_input}...")
    res = get_animegg_streams_by_mal_id(mal_input, ep_input)
    print(json.dumps(res, indent=2))