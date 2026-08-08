"""
HiAnime & PlayMongo / Doodstream Multi-Dataset Stream Extractor
=================================================================
Matches MAL ID / AniList ID & Episode Number across 37 HiAnime stream datasets
(hianime_streams_list.json through hianime_streams_list_37.json) on GitHub,
discovers all PlayMongo / Doodstream embed URLs (e.g. https://playmogo.com/e/i2oifvy9edjn),
and extracts direct video stream links.
"""

import sys
import re
import json
import urllib.request
from typing import Dict, List, Optional, Any

from hianime_otakuhg import search_hianime_datasets
from playmongo import get_direct_link_from_doodstream

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def get_playmongo_streams_by_mal_id(mal_id: int, ep_num: int) -> dict:
    """
    Match MAL ID & Episode No across HiAnime datasets,
    find PlayMongo / Doodstream embed URLs, and extract direct video streams.
    """
    print("=" * 70)
    print(f" HiAnime PlayMongo Extractor (MAL ID: {mal_id} | Episode: {ep_num})")
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

    # Extract all PlayMongo / Doodstream embed URLs from entry
    playmongo_embeds = {}
    for k, v in matched_entry.items():
        if isinstance(v, str):
            k_lower = k.lower()
            if (
                "playmogo.com" in v
                or "dood" in v
                or "doodstream" in k_lower
                or "playmogo" in k_lower
            ):
                playmongo_embeds[k] = v

    if not playmongo_embeds:
        print(" ❌ No PlayMongo / Doodstream URLs found in this episode entry.")
        return {
            "status": "error",
            "message": "No PlayMongo / Doodstream URLs found in matched entry.",
            "matched_entry": matched_entry,
        }

    print(f"\n[2] Found {len(playmongo_embeds)} PlayMongo / Doodstream embed URL(s):")
    for tag, embed_link in playmongo_embeds.items():
        print(f"   [{tag}] -> {embed_link}")

    # Extract direct streams for each embed link
    print("\n[3] Extracting direct video stream links ...")
    stream_results = []
    for tag, embed_link in playmongo_embeds.items():
        try:
            print(f"\n → Extracting from {embed_link} ({tag}) ...")
            direct_link, final_base = get_direct_link_from_doodstream(embed_link)
            file_code = embed_link.rstrip("/").split("/")[-1]

            res_item = {
                "tag": tag,
                "file_code": file_code,
                "embed_url": embed_link,
                "stream_url": direct_link,
                "referer": f"{final_base}/",
            }
            stream_results.append(res_item)

            print(f"   Direct Stream: {direct_link}")
            print(f"   Referer      : {final_base}/")
        except Exception as err:
            print(f"   ❌ Extraction failed for {embed_link}: {err}")
            stream_results.append({"tag": tag, "embed_url": embed_link, "error": str(err)})

    print("\n" + "=" * 70)
    print(" EXTRACTION SUCCESSFUL")
    print("=" * 70)

    return {
        "status": "success",
        "server": "PlayMongo",
        "mal_id": mal_id,
        "episode_no": ep_num,
        "anime_name": anime_name,
        "episode_url": ep_url,
        "source_dataset": source_file,
        "results": stream_results,
    }


if __name__ == "__main__":
    mal_input = 60425
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

    get_playmongo_streams_by_mal_id(mal_input, ep_input)
