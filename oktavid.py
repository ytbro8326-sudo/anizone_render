"""
OktaVid / OtakuVid & HiAnime Multi-Dataset Stream Extractor
===========================================================
Matches MAL ID / AniList ID & Episode Number across 37 HiAnime stream datasets
(hianime_streams_list.json through hianime_streams_list_37.json) on GitHub,
discovers all OktaVid / OtakuVid / EarnVids embed URLs (e.g. https://otakuvid.online/embed/udbogyu2axpc),
and extracts direct HLS m3u8 stream playlists and quality variants (360p, 720p, 1080p).
"""

import ast
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Any

from hianime_otakuhg import search_hianime_datasets, parse_master_playlist

EMBED_URL = "https://otakuvid.online/embed/udbogyu2axpc"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Referer": "https://otakuvid.online/",
    "Origin": "https://otakuvid.online",
}


PACKED_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,d\).*?"
    r"\(\s*'(?P<p>(?:\\.|[^'])*)'\s*,\s*"
    r"(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*"
    r"'(?P<k>(?:\\.|[^'])*)'\.split\('\|'\)\s*\)\)",
    re.S,
)

PLAYLIST_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:m3u8|txt)[^\s\"'<>]*"
    r"|/[^\s\"'<>]+?\.(?:m3u8|txt)[^\s\"'<>]*",
    re.I,
)


def fetch_text(url, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", "replace"), resp.url


def base_n(num, base):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if num == 0:
        return "0"
    out = ""
    while num:
        num, rem = divmod(num, base)
        out = chars[rem] + out
    return out


def unpack_packed_js(html):
    unpacked = []
    for match in PACKED_RE.finditer(html):
        payload = ast.literal_eval("'" + match.group("p") + "'")
        base = int(match.group("a"))
        count = int(match.group("c"))
        words = ast.literal_eval("'" + match.group("k") + "'").split("|")

        for index in range(count - 1, -1, -1):
            if index < len(words) and words[index]:
                token = re.escape(base_n(index, base))
                payload = re.sub(r"\b" + token + r"\b", words[index], payload)

        unpacked.append(payload)
    return unpacked


def extract_link_objects(js_text):
    objects = []
    for match in re.finditer(r"var\s+(?:links|o)\s*=\s*(\{.*?\});", js_text, re.S):
        raw = match.group(1)
        try:
            objects.append(json.loads(raw))
            continue
        except json.JSONDecodeError:
            pass

        found = {}
        for key, value in re.findall(
            r'["\']?([A-Za-z0-9_]+)["\']?\s*:\s*["\']([^"\']+)["\']',
            raw,
        ):
            found[key] = value
        if found:
            objects.append(found)
    return objects


def absolute_url(url, base):
    return urllib.parse.urljoin(base, url)


def uniq(items):
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_child_playlists(master_text, master_url):
    children = []

    for uri in re.findall(r'URI="([^"]+\.(?:m3u8|txt)[^"]*)"', master_text, re.I):
        children.append(absolute_url(uri, master_url))

    for line in master_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.search(r"\.(?:m3u8|txt)(?:[?#].*)?$", line, re.I):
            children.append(absolute_url(line, master_url))

    return uniq(children)


def extract_oktavid_streams(embed_url: str) -> dict:
    """
    Extract direct HLS video streams, master playlist, and quality variants
    from an OktaVid / OtakuVid / EarnVids embed URL or file code.
    """
    embed_url = embed_url.strip()
    if not embed_url.startswith("http"):
        embed_url = f"https://otakuvid.online/embed/{embed_url}"

    file_code = embed_url.rstrip("/").split("/")[-1]

    try:
        html, final_embed_url = fetch_text(embed_url)
    except Exception as exc:
        return {
            "file_code": file_code,
            "embed_url": embed_url,
            "error": f"Could not fetch embed page: {exc}",
        }

    candidates = []
    candidates.extend(PLAYLIST_RE.findall(html))

    unpacked_blocks = unpack_packed_js(html)
    for js in unpacked_blocks:
        candidates.extend(PLAYLIST_RE.findall(js))
        for link_object in extract_link_objects(js):
            for key in ("hls4", "hls3", "hls2", "file"):
                value = link_object.get(key)
                if value and re.search(r"\.(?:m3u8|txt)(?:[?#].*)?$", value, re.I):
                    candidates.append(value)

    candidates = uniq(absolute_url(url, final_embed_url) for url in candidates)

    all_playlists = list(candidates)
    for playlist_url in candidates:
        try:
            text, final_playlist_url = fetch_text(playlist_url, referer=final_embed_url)
        except (urllib.error.URLError, TimeoutError) as exc:
            continue

        if "#EXTM3U" in text:
            all_playlists.extend(parse_child_playlists(text, final_playlist_url))

    all_playlists = uniq(all_playlists)
    m3u8_urls = [url for url in all_playlists if ".m3u8" in url.lower()]
    media_m3u8_urls = [url for url in m3u8_urls if "/iframes-" not in url.lower()]
    iframe_m3u8_urls = [url for url in m3u8_urls if "/iframes-" in url.lower()]
    txt_hls_urls = [url for url in all_playlists if ".txt" in url.lower()]

    master_url = media_m3u8_urls[0] if media_m3u8_urls else (m3u8_urls[0] if m3u8_urls else None)

    variants = []
    if master_url:
        try:
            variants = parse_master_playlist(master_url, page_url=final_embed_url)
        except Exception:
            pass

    return {
        "file_code": file_code,
        "embed_url": embed_url,
        "master_url": master_url,
        "media_m3u8_urls": media_m3u8_urls,
        "iframe_m3u8_urls": iframe_m3u8_urls,
        "txt_hls_urls": txt_hls_urls,
        "all_playlists": all_playlists,
        "variants": variants,
    }


def get_oktavid_streams_by_mal_id(mal_id: int, ep_num: int) -> dict:
    """
    Match MAL ID & Episode No across HiAnime datasets,
    find OktaVid / OtakuVid / EarnVids embed URLs, and extract direct video streams.
    """
    print("=" * 70)
    print(f" HiAnime OktaVid Extractor (MAL ID: {mal_id} | Episode: {ep_num})")
    print("=" * 70)

    print("\n[1] Searching datasets for matching episode ...")
    matched_entry = search_hianime_datasets(mal_id, ep_num)

    if not matched_entry:
        print(f" ❌ Error: No match found for MAL ID {mal_id}, Episode {ep_num}")
        return {
            "status": "error",
            "message": f"No match found for MAL ID {mal_id}, Episode {ep_num}",
        }

    anime_name = matched_entry.get("anime_name", "Unknown Anime")
    ep_url = matched_entry.get("episode_url", "")
    source_file = matched_entry.get("_source_file", "")

    print(f" ✓ Match Found in {source_file}:")
    print(f"   Anime Title : {anime_name}")
    print(f"   Episode Page: {ep_url}")

    # Extract all OktaVid / OtakuVid / EarnVids embed URLs from entry
    oktavid_embeds = {}
    for k, v in matched_entry.items():
        if isinstance(v, str):
            k_lower = k.lower()
            v_lower = v.lower()
            if (
                "otakuvid.online" in v_lower
                or "earnvids" in v_lower
                or "oktavid" in v_lower
                or "earnvids" in k_lower
                or "otakuvid" in k_lower
                or "oktavid" in k_lower
            ):
                oktavid_embeds[k] = v

    if not oktavid_embeds:
        print(" ❌ No OktaVid / OtakuVid URLs found in this episode entry.")
        return {
            "status": "error",
            "message": "No OktaVid / OtakuVid URLs found in matched entry.",
            "matched_entry": matched_entry,
        }

    print(f"\n[2] Found {len(oktavid_embeds)} OktaVid / OtakuVid embed URL(s):")
    for tag, embed_link in oktavid_embeds.items():
        print(f"   [{tag}] -> {embed_link}")

    # Extract direct streams for each embed link
    print("\n[3] Extracting direct video stream links ...")
    stream_results = []
    for tag, embed_link in oktavid_embeds.items():
        try:
            print(f"\n → Extracting from {embed_link} ({tag}) ...")
            s_data = extract_oktavid_streams(embed_link)
            s_data["tag"] = tag
            s_data["server"] = "OktaVid"
            stream_results.append(s_data)

            print(f"   Master Stream: {s_data.get('master_url')}")
            for var in s_data.get("variants", []):
                if isinstance(var, dict) and "resolution" in var:
                    print(f"   - Variant ({var.get('resolution')} @ {var.get('bandwidth')}): {var.get('url')}")
        except Exception as err:
            print(f"   ❌ Extraction failed for {embed_link}: {err}")
            stream_results.append({"tag": tag, "embed_url": embed_link, "error": str(err)})

    print("\n" + "=" * 70)
    print(" EXTRACTION SUCCESSFUL")
    print("=" * 70)

    return {
        "status": "success",
        "server": "OktaVid",
        "mal_id": mal_id,
        "episode_no": ep_num,
        "anime_name": anime_name,
        "episode_url": ep_url,
        "source_dataset": source_file,
        "results": stream_results,
    }


get_streams_by_mal_id = get_oktavid_streams_by_mal_id


if __name__ == "__main__":
    mal_input = 21
    ep_input = 1

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.startswith("http") or not arg.isdigit():
            # Extract directly from URL or file code
            res = extract_oktavid_streams(arg)
            print(json.dumps(res, indent=2))
            sys.exit(0)
        else:
            try:
                mal_input = int(arg)
            except ValueError:
                pass

    if len(sys.argv) > 2:
        try:
            ep_input = int(sys.argv[2])
        except ValueError:
            pass

    get_oktavid_streams_by_mal_id(mal_input, ep_input)
