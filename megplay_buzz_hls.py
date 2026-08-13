"""
MegaPlay M3U8 Extractor — minimal
Edit MAL_ID and EPISODE below and run.
"""

import base64, json, re, urllib.request

MAL_ID  = 1735
EPISODE = 123

# ── internal ──────────────────────────────────────────────

BASE = "https://megaplay.buzz"
HDR  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer":    BASE + "/",
}

def get_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=15) as r:
        return r.read()

def decode_response(raw: bytes) -> dict:
    # Try plain JSON first
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Try base64 (with padding fix)
    try:
        s = raw.strip()
        s += b"=" * (-len(s) % 4)
        return json.loads(base64.b64decode(s))
    except Exception:
        pass
    # Try base64 of the text decoded as latin-1 (handles 0xb2 etc.)
    try:
        s = raw.strip().decode("latin-1")
        s += "=" * (-len(s) % 4)
        return json.loads(base64.b64decode(s))
    except Exception as e:
        raise RuntimeError(f"Could not decode getSources response: {e}\nRaw (first 100 bytes): {raw[:100]}")

def file_id(mal_id, episode, typ):
    raw = get_bytes(f"{BASE}/stream/mal/{mal_id}/{episode}/{typ}?autostart=true")
    m = re.search(rb'data-id="(\d+)"', raw)
    if not m: raise RuntimeError(f"data-id not found for {typ}")
    return m.group(1).decode()

def sources(fid):
    raw = get_bytes(f"{BASE}/stream/getSources?id={fid}&id={fid}")
    data = decode_response(raw)
    return data["sources"]["file"], data.get("intro"), data.get("outro")

def parse_variants(master_url):
    try:
        req = urllib.request.Request(master_url, headers=HDR)
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8")
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
                res = attrs.get("RESOLUTION", "")
                if i + 1 < len(lines):
                    sp = lines[i + 1].strip()
                    if sp and not sp.startswith("#"):
                        abs_url = sp if sp.startswith("http") else base + sp
                        variants.append({"resolution": res, "url": abs_url})
        return variants
    except Exception:
        return []

def get_megaplay_streams_by_mal_id(mal_id: int, episode: int) -> dict:
    streams = []
    for typ in ("sub", "dub"):
        try:
            fid = file_id(mal_id, episode, typ)
            m3u8, intro, outro = sources(fid)
            
            # Master playlist stream
            streams.append({
                "server": f"MegaPlay {typ.upper()} (Master)",
                "url": m3u8,
                "type": "hls",
                "quality": f"{typ.upper()} Master",
                "referer": "https://megaplay.buzz/",
                "ref": "https://megaplay.buzz/",
                "origin": "https://megaplay.buzz",
                "intro": intro,
                "outro": outro
            })

            # Quality variant playlists (e.g. 1080p, 720p)
            var_list = parse_variants(m3u8)
            for v in var_list:
                res_str = v["resolution"] if v["resolution"] else "Direct Track"
                streams.append({
                    "server": f"MegaPlay {typ.upper()} ({res_str})",
                    "url": v["url"],
                    "type": "hls",
                    "quality": f"{typ.upper()} {res_str}",
                    "referer": "https://megaplay.buzz/",
                    "ref": "https://megaplay.buzz/",
                    "origin": "https://megaplay.buzz",
                    "intro": intro,
                    "outro": outro
                })
        except Exception:
            pass

    if not streams:
        raise RuntimeError(f"No MegaPlay streams found for MAL ID {mal_id} Ep {episode}")

    return {
        "status": "success",
        "server": "MegaPlay",
        "malId": mal_id,
        "episode": episode,
        "results": {
            "stream_url": streams[0]["url"],
            "streams": streams
        }
    }

# ── run ───────────────────────────────────────────────────

if __name__ == "__main__":
    for typ in ("sub", "dub"):
        try:
            fid = file_id(MAL_ID, EPISODE, typ)
            m3u8, intro, outro = sources(fid)
            print(f"\n[{typ.upper()}]")
            print(f"  M3U8  : {m3u8}")
            vars_found = parse_variants(m3u8)
            for v in vars_found:
                print(f"  Variant ({v['resolution']}): {v['url']}")
            print(f"  Intro : {intro['start']}s – {intro['end']}s" if intro else "  Intro : none")
            print(f"  Outro : {outro['start']}s – {outro['end']}s" if outro else "  Outro : none")
        except Exception as e:
            print(f"\n[{typ.upper()}] Error: {e}")
