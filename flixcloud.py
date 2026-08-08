import sys
import re
import json
import json5
import httpx
from urllib.parse import urlencode

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

LUNA_API  = "https://api.lunaranime.ru/api/3rdprovider"
FLIXCLOUD = "https://flixcloud.cc"
ENC_DEC   = "https://enc-dec.app/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Referer": f"{FLIXCLOUD}/",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Proxy Fallback HTTP Request ───────────────────────────────────────────────

def _http_request(url, method="GET", json_payload=None, params=None, headers=None, timeout=20.0):
    if headers is None:
        headers = HEADERS

    proxy_list = [None] + list(PROXIES)
    last_err = None

    for p in proxy_list:
        try:
            kwargs = {"timeout": timeout, "follow_redirects": True, "verify": False}
            if p:
                kwargs["proxy"] = p
            with httpx.Client(**kwargs) as client:
                if method.upper() == "POST":
                    resp = client.post(url, json=json_payload, headers=headers)
                else:
                    resp = client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return resp
                else:
                    last_err = f"HTTP {resp.status_code}"
        except Exception as err:
            last_err = err
            continue

    raise RuntimeError(f"Failed to fetch {url}. Last error: {last_err}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(tag, msg):
    print(f"  [{tag}]  {msg}")


def validate_encdec(data, endpoint):
    if data.get("status") != 200:
        err = data.get("error") or data.get("message") or "unknown"
        raise RuntimeError(f"enc-dec.app error at {endpoint!r}: {err}")
    result = data.get("result")
    if result is None:
        raise RuntimeError(f"enc-dec.app missing 'result' at {endpoint!r}")
    return result


def audio_label(audio_str):
    """Normalize audio field → clean label."""
    a = (audio_str or "").lower().strip()
    if a in ("sub", "subbed", "japanese"):
        return "SUB"
    if a in ("dub", "dubbed", "english"):
        return "DUB"
    if a in ("dual", "both"):
        return "DUAL"
    return a.upper() if a else "UNKNOWN"


# ── Step 1: LunarAnime → all FlixCloud entries for this episode ───────────────

def fetch_all_entries(anilist_id, episode):
    log("LUNA", f"GET anilist={anilist_id}  episode={episode}")
    resp = _http_request(
        LUNA_API,
        params={"anilist": anilist_id, "episode": episode, "autoplay": "true"},
        timeout=20,
    )
    body = resp.json()

    if body.get("status") != "success" or not body.get("success"):
        raise RuntimeError(f"LunarAnime API failure:\n{json.dumps(body, indent=2)}")

    all_entries = body.get("data", [])
    if not all_entries:
        raise RuntimeError(
            f"No entries for anilist={anilist_id} ep={episode}. "
            "Episode may not exist on this provider."
        )

    # Keep only FlixCloud entries
    fc_entries = [e for e in all_entries if "flixcloud.cc" in e.get("player_url", "")]
    if not fc_entries:
        raise RuntimeError("No FlixCloud entries found in LunarAnime response.")

    log("LUNA", f"{len(fc_entries)} FlixCloud entry/entries found")
    for e in fc_entries:
        log("LUNA", f"  audio={e.get('audio'):<6}  server={e.get('server')}  url={e.get('player_url')}")

    return fc_entries


# ── Step 2: FlixCloud embed page → encrypted data blob ───────────────────────

def fetch_embed_data(player_url):
    resp = _http_request(player_url, headers=HEADERS, timeout=20)
    html = resp.text

    m = re.search(
        r'type\s*:\s*["\']data["\']\s*,\s*data\s*:\s*(\{.*?\})\s*,\s*uses\s*:',
        html, re.DOTALL
    )
    if not m:
        m = re.search(
            r'"type"\s*:\s*"data"\s*,\s*"data"\s*:\s*(\{.*?\})\s*,\s*"uses"\s*:',
            html, re.DOTALL
        )
    if not m:
        raise RuntimeError(
            "Could not find encrypted data blob in FlixCloud page. "
            "Embed format may have changed."
        )

    try:
        data = json5.loads(m.group(1))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse data blob as JSON5: {exc}") from exc

    data.pop("subtitles", None)   # drop subtitles entirely — not needed
    return data


# ── Step 3: enc-dec.app → decode token ───────────────────────────────────────

def decode_token(data):
    endpoint = f"{ENC_DEC}/dec-flixcloud?type=token"
    resp = _http_request(endpoint, method="POST", json_payload={"data": data}, timeout=20)
    result = validate_encdec(resp.json(), endpoint)
    if "token" not in result:
        raise RuntimeError(f"Token result missing 'token': {result}")
    return result


# ── Step 4: FlixCloud → encrypted stream metadata ────────────────────────────

def fetch_encrypted_stream(token):
    url = f"{FLIXCLOUD}/api/m3u8/{token}"
    resp = _http_request(url, headers=HEADERS, timeout=20)
    return resp.json()


# ── Step 5: enc-dec.app → final HLS URL ──────────────────────────────────────

def decrypt_stream(context, encrypted_stream):
    endpoint = f"{ENC_DEC}/dec-flixcloud?type=stream"
    payload  = {"data": {"context": context, "stream_response": encrypted_stream}}
    resp = _http_request(endpoint, method="POST", json_payload=payload, timeout=20)
    result = validate_encdec(resp.json(), endpoint)
    if "stream" not in result:
        raise RuntimeError(f"Stream result missing 'stream': {result}")
    return result


# ── Step 6: enc-dec.app → M3U8 manifest ──────────────────────────────────────

def fetch_manifest(stream_url, stream_result):
    w_payload = (
        stream_result.get("context", {}).get("w_payload")
        or stream_result.get("w_payload", "")
    )
    qs       = urlencode({"url": stream_url, "w_payload": w_payload})
    endpoint = f"{ENC_DEC}/parse-flixcloud?{qs}"
    resp     = _http_request(endpoint, timeout=20)
    return resp.text


# ── Resolve one entry end-to-end ──────────────────────────────────────────────

def resolve_entry(entry):
    player_url = entry["player_url"]
    label      = audio_label(entry.get("audio"))

    log(label, f"resolving  {player_url}")

    embed_data      = fetch_embed_data(player_url)
    token_result    = decode_token(embed_data)
    enc_stream      = fetch_encrypted_stream(token_result["token"])
    stream_result   = decrypt_stream(token_result["context"], enc_stream)
    manifest        = fetch_manifest(stream_result["stream"], stream_result)

    log(label, f"stream OK  {stream_result['stream']}")

    return {
        "label":    label,
        "audio":    entry.get("audio"),
        "server":   entry.get("server"),
        "stream":   stream_result["stream"],
        "manifest": manifest,
        "referer":  f"{FLIXCLOUD}/",
    }


def get_streams_by_anilist_id(anilist_id: int, episode: int, mal_id: int = None) -> dict:
    """Fetch and resolve FlixCloud streams for given AniList ID and Episode No."""
    entries = fetch_all_entries(anilist_id, episode)
    streams = []
    for entry in entries:
        try:
            res = resolve_entry(entry)
            streams.append(res)
        except Exception as e:
            label = audio_label(entry.get("audio"))
            streams.append({"error": str(e), "label": label, "server": entry.get("server")})

    return {
        "status": "success",
        "server": "FlixCloud",
        "mal_id": mal_id,
        "anilist_id": anilist_id,
        "episode_no": episode,
        "results": streams,
    }


# ── Main CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    anilist_input = 1735
    ep_input = 250

    if len(sys.argv) > 1:
        try:
            anilist_input = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            ep_input = int(sys.argv[2])
        except ValueError:
            pass

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print(f"║   LunarAnime → FlixCloud → HLS Resolver              ║")
    print(f"║   anilist = {anilist_input:<6}   episode = {ep_input:<6}              ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    data = get_streams_by_anilist_id(anilist_input, ep_input)
    streams = [s for s in data.get("results", []) if "stream" in s]

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║   STREAMS                                            ║")
    print("╚══════════════════════════════════════════════════════╝")

    if not streams:
        print("\n  ✖ No streams could be resolved.\n")
    else:
        for s in streams:
            bar   = "─" * 54
            label = s["label"]
            icon  = "🎌" if label == "SUB" else "🔊" if label == "DUB" else "🎬"

            print()
            print(f"  {icon}  {label}  (server: {s['server']})")
            print(f"  {bar}")
            print(f"  Stream URL  :  {s['stream']}")
            print(f"  Referer     :  {s['referer']}")
            print()
            print(f"  Manifest (M3U8):")
            for line in s.get("manifest", "").strip().splitlines():
                print(f"    {line}")
            print(f"  {bar}")

        print()
        print("  ── Player commands ───────────────────────────────────")
        for s in streams:
            print(f"  [{s['label']}]  mpv --referrer=\"{s['referer']}\" \"{s['stream']}\"")
        print()
