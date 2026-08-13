"""
OtakuHG & HiAnime Stream Extractor
==================================
1. Resolves MAL ID / AniList ID & Episode Number across 37 HiAnime stream datasets on GitHub.
2. Finds OtakuHG embed URLs (e.g. https://otakuhg.site/e/fbxdhpv4mzbl).
3. Extracts direct HLS m3u8 stream playlists and quality variants (480p, 720p, 1080p).
"""

import sys
import re
import json
import urllib.request

from hianime_otakuhg import (
    extract_otakuhg_streams,
    get_streams_by_mal_id,
    search_hianime_datasets,
)

if __name__ == "__main__":
    # Default sample test inputs: MAL ID 60425, Episode 1
    mal_input = 21
    ep_input = 1

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.startswith("http") or not arg.isdigit():
            # Extract directly from URL or file code
            extract_otakuhg_streams(arg)
            sys.exit(0)
        else:
            mal_input = int(arg)

    if len(sys.argv) > 2:
        try:
            ep_input = int(sys.argv[2])
        except ValueError:
            pass

    get_streams_by_mal_id(mal_input, ep_input)



