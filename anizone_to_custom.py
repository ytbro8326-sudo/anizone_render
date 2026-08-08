#!/usr/bin/env python3
"""
anizone_to_custom.py – Stream URL extractor & English Dub patcher for anizone.to (with proxy rotation)
"""

import re
import sys
import os
import html
import json
import random
import urllib.request
import urllib.parse
import urllib.error
from typing import Any, Dict, List, Optional, Set

from proxies import PROXIES

MAL_ID = 1735
EPISODE = 1

CDN_BASE = "https://seiryuu.vid-cdn.xyz"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://anizone.to/",
}


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


def decode_entities(s: str = "") -> str:
    if not s:
        return ""
    return html.unescape(s).strip()


def process_json_arg(raw: str) -> dict:
    ph = "\x01U\x01"
    s = re.sub(r'\\\\u([0-9a-fA-F]{4})', r'%s\1' % ph, raw)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'\x01U\x01([0-9a-fA-F]{4})', r'\\u\1', s)
    try:
        return json.loads(s)
    except Exception:
        return {}


def get_proxy_opener(proxy_url: str):
    proxy_handler = urllib.request.ProxyHandler({
        "http": proxy_url,
        "https": proxy_url
    })
    return urllib.request.build_opener(proxy_handler)


def fetch(url: str, extra_headers: dict | None = None) -> str:
    headers = {**HEADERS, **(extra_headers or {})}
    shuffled_proxies = list(PROXIES)
    random.shuffle(shuffled_proxies)

    last_error = None
    # 1. Try rotating proxies to bypass Render 403 blocks
    for proxy in shuffled_proxies:
        try:
            opener = get_proxy_opener(proxy)
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=12) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_error = e
            continue

    # 2. Fallback to direct request
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise Exception(f"Fetch failed for {url}: {last_error or e}")


def get_media_by_mal_id(mal_id: int) -> dict:
    query = """
    query ($idMal: Int) {
      Media (idMal: $idMal, type: ANIME) {
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
    req_data = json.dumps({"query": query, "variables": {"idMal": int(mal_id)}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]}
    url = "https://graphql.anilist.co"

    shuffled_proxies = list(PROXIES)
    random.shuffle(shuffled_proxies)

    last_error = None
    data = None
    for proxy in shuffled_proxies:
        try:
            opener = get_proxy_opener(proxy)
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            with opener.open(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception as e:
            last_error = e
            continue

    if not data:
        try:
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise Exception(f"Failed to fetch AniList media for MAL ID {mal_id}: {last_error or e}")

    media = data.get("data", {}).get("Media") if data else None
    if not media:
        raise Exception(f"No media found for MAL ID {mal_id}")
    return media


def build_titles(media: dict) -> List[str]:
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
    return list(dict.fromkeys(titles))


def search_anizone(query: str) -> List[dict]:
    url = f"https://anizone.to/anime?search={urllib.parse.quote(query)}"
    try:
        html_str = fetch(url)
    except Exception:
        return []
    results = []
    for m in re.finditer(r'x-data="(\{[^"]*anmTitles[^"]*\})"', html_str):
        idx = m.start()
        ctx_start = max(0, idx - 300)
        ctx_end = min(len(html_str), idx + len(m.group(0)) + 800)
        ctx = html_str[ctx_start:ctx_end]
        slug_m = re.search(r'href="(?:https://anizone\.to)?/anime/([a-z0-9-]+)"', ctx)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        xdata = decode_entities(m.group(1))
        json_m = re.search(r'anmTitles:\s*JSON\.parse\(\'((?:[^\'\\]|\\.)*)\'\)', xdata)
        if not json_m:
            continue
        titles_dict = process_json_arg(json_m.group(1))
        title = titles_dict.get("1") or titles_dict.get("5") or titles_dict.get("8") or (list(titles_dict.values())[0] if titles_dict else "")
        if title:
            results.append({"slug": slug, "title": title})
    return results


def resolve_anizone_slug(mal_id: int) -> dict:
    print(f"[*] Resolving AniZone slug for MAL ID {mal_id} via AniList...")
    media = get_media_by_mal_id(mal_id)
    titles = build_titles(media)
    season_year = media.get("seasonYear")

    candidates = {}
    for t in titles[:4]:
        res = search_anizone(t)
        for r in res:
            if r["slug"] not in candidates:
                candidates[r["slug"]] = r["title"]

    scored = []
    for slug, text in candidates.items():
        best = 0.0
        for title in titles[:2]:
            score = max(dice_coeff(title, text), dice_coeff(title, slug.replace("-", " ")))
            best = max(best, score)

        if season_year:
            m = re.search(r'\((\d{4})\)', text)
            if m:
                best = min(1.0, best * 1.3) if int(m.group(1)) == season_year else best * 0.5

        if best >= 0.4:
            scored.append({"slug": slug, "title": text, "score": best})

    scored.sort(key=lambda x: x["score"], reverse=True)
    if not scored:
        raise Exception(f"No AniZone anime match found for MAL ID {mal_id} ({titles[:1]})")

    selected = scored[0]
    print(f"    Matched: '{selected['title']}' (slug: {selected['slug']}, score: {selected['score']:.2f})")
    return selected


def extract_uuid(html: str) -> str | None:
    patterns = [
        r"https?://[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/master\.m3u8",
        r"vid-cdn\.xyz/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/",
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def patch_master_for_english_default(content: str, master_url: str) -> str:
    out_lines = []
    base_folder = master_url.rsplit("/", 1)[0] + "/"

    for line in content.splitlines():
        if line.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in line:
            lang_match = re.search(r'LANGUAGE="?([^",\s]+)"?', line, re.IGNORECASE)
            lang = lang_match.group(1).lower() if lang_match else ""
            is_english = lang in ("en", "eng")

            line = re.sub(r'DEFAULT=(YES|NO)', f'DEFAULT={"YES" if is_english else "NO"}', line)
            line = re.sub(r'AUTOSELECT=(YES|NO)', f'AUTOSELECT={"YES" if is_english else "NO"}', line)

            if "DEFAULT=" not in line:
                line += f',DEFAULT={"YES" if is_english else "NO"}'
            if "AUTOSELECT=" not in line:
                line += f',AUTOSELECT={"YES" if is_english else "NO"}'

            uri_match = re.search(r'URI="?([^",\s]+)"?', line)
            if uri_match:
                rel_uri = uri_match.group(1)
                if not rel_uri.startswith("http"):
                    abs_uri = base_folder + rel_uri
                    line = line.replace(f'URI="{rel_uri}"', f'URI="{abs_uri}"')

        elif line.strip() and not line.strip().startswith("#"):
            rel_path = line.strip()
            if not rel_path.startswith("http"):
                line = base_folder + rel_path

        out_lines.append(line)
    return "\n".join(out_lines)


def process_mal_episode(mal_id: int, episode: int) -> dict:
    series = resolve_anizone_slug(mal_id)
    page_url = f"https://anizone.to/anime/{series['slug']}/{episode}"
    print(f"[1] Fetching AniZone page: {page_url}")
    try:
        html_str = fetch(page_url)
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code} – {e.reason}")

    uuid = extract_uuid(html_str)
    if not uuid:
        raise Exception("Could not find video UUID in page HTML.")

    master_url = f"{CDN_BASE}/{uuid}/master.m3u8"
    try:
        master_content = fetch(master_url, extra_headers={"Origin": "https://anizone.to"})
    except urllib.error.HTTPError as e:
        raise Exception(f"Failed to fetch master playlist: HTTP {e.code}")

    patched = patch_master_for_english_default(master_content, master_url)

    video_urls = []
    audio_urls = {}

    curr_res = ""
    for line in master_content.splitlines():
        if line.strip().startswith("#EXT-X-STREAM-INF"):
            res = re.search(r'RESOLUTION=([\dx]+)', line)
            bw  = re.search(r'BANDWIDTH=(\d+)', line)
            curr_res = f"{res.group(1) if res else '?'} ({int(bw.group(1))//1000}kbps)"
        elif line.strip() and not line.strip().startswith("#"):
            url = line.strip()
            if not url.startswith("http"):
                url = master_url.rsplit("/", 1)[0] + "/" + url
            video_urls.append((curr_res, url))

    for line in patched.splitlines():
        if line.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in line:
            lang = re.search(r'LANGUAGE="?([^",\s]+)"?', line)
            uri  = re.search(r'URI="?([^",\s]+)"?', line)
            if lang and uri:
                audio_urls[lang.group(1).lower()] = uri.group(1)

    video_qualities = [{"resolution": r, "url": u} for r, u in video_urls]
    streams = [
        {
            "url": master_url,
            "type": "hls",
            "server": "AniZone Master HLS (Auto Sub/Dub)",
            "audio": "both",
            "priority": 1,
            "isActive": True
        }
    ]
    for r, u in video_urls:
        streams.append({
            "url": u,
            "type": "hls",
            "server": f"AniZone Video ({r})",
            "audio": "none",
            "priority": 2,
            "isActive": False
        })
    if "en" in audio_urls:
        streams.append({
            "url": audio_urls["en"],
            "type": "hls",
            "server": "AniZone English Dub Audio",
            "audio": "dub",
            "priority": 3,
            "isActive": False
        })
    if "ja" in audio_urls:
        streams.append({
            "url": audio_urls["ja"],
            "type": "hls",
            "server": "AniZone Japanese Audio",
            "audio": "sub",
            "priority": 4,
            "isActive": False
        })

    return {
        "title": series.get("title"),
        "slug": series.get("slug"),
        "uuid": uuid,
        "originalMasterM3u8": master_url,
        "patchedMasterM3u8Content": patched,
        "videoQualities": video_qualities,
        "audioTracks": audio_urls,
        "streams": streams
    }


if __name__ == "__main__":
    res = process_mal_episode(MAL_ID, EPISODE)
    print(json.dumps(res, indent=2))
