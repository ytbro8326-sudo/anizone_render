"""
ViviBebe & HiAnime Multi-Dataset Stream Extractor
=================================================
Matches MAL ID / AniList ID & Episode Number across 37 HiAnime stream datasets
(hianime_streams_list.json through hianime_streams_list_37.json) on GitHub,
discovers all ViviBebe embed URLs (e.g. https://vivibebe.site/b62c1045846e7fe5),
and converts them into direct HLS master playlists and quality variants
(e.g. https://vivibebe.site/public/stream/b62c1045846e7fe5/master.m3u8).
"""

import sys
import re
import json
import urllib.request
from typing import Dict, List, Optional, Any

from hianime_otakuhg import search_hianime_datasets, parse_master_playlist

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

VIVIBEBE_BASE_URL = "https://vivibebe.site"


def convert_vivibebe_url(embed_url: str, fetch_variants: bool = True) -> dict:
    """
    Convert a ViviBebe embed link or file code to direct HLS m3u8 stream URL
    and parse quality variants (360p, 720p, 1080p).
    
    Example:
    Input:  https://vivibebe.site/b62c1045846e7fe5
    Output: https://vivibebe.site/public/stream/b62c1045846e7fe5/master.m3u8
    """
    embed_url = embed_url.strip()
    file_code = embed_url.rstrip("/").split("/")[-1]
    
    master_url = f"{VIVIBEBE_BASE_URL}/public/stream/{file_code}/master.m3u8"
    
    variants = []
    if fetch_variants:
        try:
            variants = parse_master_playlist(master_url, page_url=embed_url)
        except Exception as err:
            variants = [{"error": str(err)}]
            
    return {
        "file_code": file_code,
        "embed_url": embed_url if embed_url.startswith("http") else f"{VIVIBEBE_BASE_URL}/{file_code}",
        "master_url": master_url,
        "stream_url": master_url,
        "variants": variants,
    }


def get_vivibebe_streams_by_mal_id(mal_id: int, ep_num: int, fetch_variants: bool = True) -> dict:
    """
    Match MAL ID & Episode No across HiAnime datasets,
    find ViviBebe embed URLs, and convert them to direct video streams.
    """
    print("=" * 70)
    print(f" HiAnime ViviBebe Extractor (MAL ID: {mal_id} | Episode: {ep_num})")
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

    # Extract all ViviBebe embed URLs from entry
    vivibebe_embeds = {}
    for k, v in matched_entry.items():
        if isinstance(v, str):
            k_lower = k.lower()
            if "vivibebe" in v.lower() or "vivibebe" in k_lower:
                vivibebe_embeds[k] = v

    if not vivibebe_embeds:
        print(" ❌ No ViviBebe URLs found in this episode entry.")
        return {
            "status": "error",
            "message": "No ViviBebe URLs found in matched entry.",
            "matched_entry": matched_entry,
        }

    print(f"\n[2] Found {len(vivibebe_embeds)} ViviBebe embed URL(s):")
    for tag, embed_link in vivibebe_embeds.items():
        print(f"   [{tag}] -> {embed_link}")

    # Convert and extract streams for each embed link
    print("\n[3] Converting to direct HLS stream playlists ...")
    stream_results = []
    for tag, embed_link in vivibebe_embeds.items():
        try:
            print(f"\n → Converting {embed_link} ({tag}) ...")
            s_data = convert_vivibebe_url(embed_link, fetch_variants=fetch_variants)
            s_data["tag"] = tag
            s_data["server"] = "ViviBebe"
            stream_results.append(s_data)

            print(f"   Master Stream: {s_data.get('master_url')}")
            for var in s_data.get("variants", []):
                if isinstance(var, dict) and "resolution" in var:
                    print(f"   - Variant ({var.get('resolution')} @ {var.get('bandwidth')}): {var.get('url')}")
        except Exception as err:
            print(f"   ❌ Conversion failed for {embed_link}: {err}")
            stream_results.append({"tag": tag, "embed_url": embed_link, "error": str(err)})

    print("\n" + "=" * 70)
    print(" EXTRACTION SUCCESSFUL")
    print("=" * 70)

    return {
        "status": "success",
        "server": "ViviBebe",
        "mal_id": mal_id,
        "episode_no": ep_num,
        "anime_name": anime_name,
        "episode_url": ep_url,
        "source_dataset": source_file,
        "results": stream_results,
    }


if __name__ == "__main__":
    mal_input = 21
    ep_input = 1

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.startswith("http") or not arg.isdigit():
            # Convert directly from URL or file code
            res = convert_vivibebe_url(arg)
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

    get_vivibebe_streams_by_mal_id(mal_input, ep_input)
