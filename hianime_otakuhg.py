"""
HiAnime & OtakuHG Multi-Dataset Stream Extractor
=================================================
Matches MAL ID / AniList ID & Episode Number across 37 HiAnime stream datasets
(hianime_streams_list.json through hianime_streams_list_37.json) on GitHub,
discovers all OtakuHG embed URLs (e.g. https://otakuhg.site/e/fbxdhpv4mzbl),
and extracts direct HLS m3u8 streams and quality variants.
"""

import sys
import re
import json
import urllib.request
from typing import Dict, List, Optional, Any

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Dataset URLs on GitHub
RAW_BASE_URL = "https://raw.githubusercontent.com/srtfile/hi_anime_streams_scraper/refs/heads/main/"

# In-memory cache for fetched datasets
_DATASET_CACHE: Dict[str, list] = {}


def fetch_url(url: str, referer: str = None, timeout: float = 15.0) -> str:
    """Fetch text content from a URL."""
    headers = {"User-Agent": DEFAULT_UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="ignore")


def load_dataset(filename: str) -> list:
    """Load and cache a JSON dataset file from GitHub raw repository."""
    if filename in _DATASET_CACHE:
        return _DATASET_CACHE[filename]

    url = RAW_BASE_URL + filename
    try:
        raw_json = fetch_url(url, timeout=12.0)
        data = json.loads(raw_json)
        _DATASET_CACHE[filename] = data
        return data
    except Exception:
        return []


def search_hianime_datasets(mal_id: int, ep_num: int) -> Optional[dict]:
    """
    Search across all 37 HiAnime datasets for an entry matching
    mal_id / anilist_id and episode_no.
    """
    # 1. Generate list of filenames: hianime_streams_list.json, hianime_streams_list_2.json ... list_37.json
    filenames = ["hianime_streams_list.json"] + [f"hianime_streams_list_{i}.json" for i in range(2, 38)]

    target_mid = str(mal_id).strip()
    target_ep = str(ep_num).strip()

    for fname in filenames:
        items = load_dataset(fname)
        if not items:
            # Fallback check for listX.json without underscore
            alt_fname = fname.replace("_", "")
            items = load_dataset(alt_fname)

        for item in items:
            mid = str(item.get("mal_id/anilist_id/tmdb_id") or "").strip()
            ep = str(item.get("episode_no") or "").strip()

            if mid == target_mid and ep == target_ep:
                item["_source_file"] = fname
                return item

    return None


def decode_packed_js(html: str) -> str:
    """Deobfuscate Dean Edwards p,a,c,k,e,d JavaScript block."""
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}"
        r"\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)\)\)",
        html,
        re.DOTALL,
    )
    if not m:
        return ""

    obfuscated, base, count, word_list = (
        m.group(1),
        int(m.group(2)),
        int(m.group(3)),
        m.group(4).split("|"),
    )
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"

    def unbase(n, b):
        if n == 0:
            return "0"
        res = ""
        while n:
            res = chars[n % b] + res
            n //= b
        return res

    lookup = {
        unbase(i, base): (word_list[i] if i < len(word_list) and word_list[i] else unbase(i, base))
        for i in range(count)
    }
    return re.sub(r"\b\w+\b", lambda match: lookup.get(match.group(0), match.group(0)), obfuscated)


def parse_master_playlist(master_url: str, page_url: str = None) -> list:
    """Parse HLS master playlist for quality variants (480p, 720p, 1080p)."""
    try:
        content = fetch_url(master_url, referer=page_url)
    except Exception as err:
        return [{"error": str(err)}]

    base = master_url.rsplit("/", 1)[0] + "/"
    variants = []
    lines = content.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = {}
            for am in re.finditer(r'([\w-]+)=(?:"([^"]*)"|([^,\s]+))', line):
                key = am.group(1).upper()
                val = am.group(2) if am.group(2) is not None else am.group(3)
                attrs[key] = val

            resolution = attrs.get("RESOLUTION", "Unknown")
            bandwidth = attrs.get("BANDWIDTH", "0")
            bw_kbps = f"{int(bandwidth) // 1000} kbps" if bandwidth.isdigit() else bandwidth

            if i + 1 < len(lines):
                stream_path = lines[i + 1].strip()
                if stream_path and not stream_path.startswith("#"):
                    abs_stream = stream_path if stream_path.startswith("http") else base + stream_path
                    variants.append({
                        "resolution": resolution,
                        "bandwidth": bw_kbps,
                        "url": abs_stream,
                    })

    return variants


def extract_otakuhg_streams(embed_url: str, fetch_variants: bool = True) -> dict:
    """Extract direct HLS streams and quality variants from an OtakuHG or OtakuVid embed page."""
    file_code = embed_url.rstrip("/").split("/")[-1]
    html = fetch_url(embed_url)
    decoded_js = decode_packed_js(html)

    links_m = re.search(r"var\s+links\s*=\s*(\{.*?\});", decoded_js)
    if not links_m:
        raise ValueError(f"Could not extract stream links from embed page: {embed_url}")

    raw_links = json.loads(links_m.group(1))
    parsed_domain = embed_url.split("/")[0] + "//" + embed_url.split("/")[2]

    links = {}
    for key, path in raw_links.items():
        links[key] = parsed_domain + path if path.startswith("/") else path

    master_url = links.get("hls4") or links.get("hls3") or links.get("hls2")

    variants = []
    if fetch_variants and master_url:
        variants = parse_master_playlist(master_url, page_url=embed_url)

    return {
        "file_code": file_code,
        "embed_url": embed_url,
        "master_url": master_url,
        "links": links,
        "variants": variants,
    }


def get_streams_by_mal_id(mal_id: int, ep_num: int, include_otakuvid: bool = False) -> dict:
    """
    Main function: Match MAL ID & Episode No, extract OtakuHG (and optionally OtakuVid)
    embed URLs, and fetch direct HLS video streams.
    """
    print("=" * 70)
    print(f" HiAnime Stream Extractor (MAL ID: {mal_id} | Episode: {ep_num} | OtakuVid: {include_otakuvid})")
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

    # Extract embed URLs from entry
    otakuhg_embeds = {}
    for k, v in matched_entry.items():
        if not isinstance(v, str):
            continue
        k_lower = k.lower()

        # OtakuHG (default)
        is_otakuhg = "otakuhg.site" in v or "streamhg" in k_lower
        # OtakuVid / EarnVids (optional)
        is_otakuvid = include_otakuvid and ("otakuvid.online" in v or "earnvids" in k_lower)

        if is_otakuhg or is_otakuvid:
            otakuhg_embeds[k] = v

    if not otakuhg_embeds:
        print(" ❌ No matching stream URLs found in this episode entry.")
        return {
            "status": "error",
            "message": "No matching stream URLs found in matched entry.",
            "matched_entry": matched_entry,
        }

    print(f"\n[2] Found {len(otakuhg_embeds)} embed URL(s):")
    for tag, embed_link in otakuhg_embeds.items():
        print(f"   [{tag}] -> {embed_link}")

    # Extract streams for each link
    print("\n[3] Extracting direct HLS stream tracks ...")
    stream_results = []
    for tag, embed_link in otakuhg_embeds.items():
        try:
            print(f"\n → Extracting from {embed_link} ({tag}) ...")
            s_data = extract_otakuhg_streams(embed_link)
            s_data["tag"] = tag
            stream_results.append(s_data)

            print(f"   Master Stream: {s_data.get('master_url')}")
            for var in s_data.get("variants", []):
                print(f"   - Variant ({var.get('resolution')} @ {var.get('bandwidth')}): {var.get('url')}")
        except Exception as err:
            print(f"   ❌ Extraction failed for {embed_link}: {err}")
            stream_results.append({"tag": tag, "embed_url": embed_link, "error": str(err)})

    print("\n" + "=" * 70)
    print(" EXTRACTION SUCCESSFUL")
    print("=" * 70)

    return {
        "status": "success",
        "mal_id": mal_id,
        "episode_no": ep_num,
        "anime_name": anime_name,
        "episode_url": ep_url,
        "source_dataset": source_file,
        "results": stream_results,
    }


if __name__ == "__main__":
    # Default sample test inputs: MAL ID 60425, Episode 1
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

    res = get_streams_by_mal_id(mal_input, ep_input)
