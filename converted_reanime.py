import re
import json
import base64
import hashlib
import asyncio
import time
import random
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
import httpx

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []

BASE = "https://reanime.to"
FLIX = "https://flixcloud.cc"
ANIZIP2 = "https://api.ani.zip/mappings"
UA5 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA5, "Accept": "application/json, */*"}


# In-Memory Cache
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


async def fetch_page_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 10.0) -> str:
    req_headers = {"User-Agent": UA5}
    if headers:
        req_headers.update(headers)

    # 1. Direct request
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code == 200:
                return res.text
    except Exception:
        pass

    # 2. Proxy rotation retry if direct failed or returned non-200 (e.g. 403)
    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
                    res = await client.get(url, headers=req_headers)
                    if res.status_code == 200:
                        return res.text
            except Exception:
                continue

    # Final attempt to raise status / return error
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=req_headers)
        res.raise_for_status()
        return res.text


async def fetch_json_with_proxy(url: str, headers: Optional[dict] = None, timeout: float = 10.0) -> Any:
    req_headers = {"User-Agent": UA5, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    # 1. Direct request
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass

    # 2. Proxy rotation retry if direct failed or returned non-200 (e.g. 403)
    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
                    res = await client.get(url, headers=req_headers)
                    if res.status_code == 200:
                        return res.json()
            except Exception:
                continue

    # Final attempt to raise status / return error
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        res = await client.get(url, headers=req_headers)
        res.raise_for_status()
        return res.json()


def sha256hex(s: Any) -> str:
    if isinstance(s, str):
        data = s.encode("utf-8")
    else:
        data = bytes(s)
    return hashlib.sha256(data).hexdigest()


def b64to_u8(b64_str: str) -> bytes:
    pad = len(b64_str) % 4
    if pad:
        b64_str += "=" * (4 - pad)
    return base64.b64decode(b64_str)


def derive_fields(seed: str) -> dict:
    e = seed
    for i in range(3):
        e = sha256hex(e + str(i))
    l = e
    for i in range(3):
        l = sha256hex(l + str(i))
    return {
        "keyField": "kf_" + e[8:16],
        "ivField": "ivf_" + e[16:24],
        "containerName": "cd_" + e[24:32],
        "arrayName": "ad_" + e[32:40],
        "objectName": "od_" + e[40:48],
        "tokenField": e[48:64] + "_" + e[56:64],
        "keyFrag2Field": l[0:16] + "_" + l[16:24]
    }


def extract_ssr_obj(html_str: str) -> str:
    m = re.search(r'\{type:"data",data:(\{)', html_str)
    if not m:
        raise Exception("SSR data block not found")
    start = html_str.find("{", m.start() + len(m.group(0)) - 1)
    depth = 0
    for i in range(start, len(html_str)):
        if html_str[i] == "{":
            depth += 1
        elif html_str[i] == "}":
            depth -= 1
            if depth == 0:
                return html_str[start:i+1]
    raise Exception("SSR brace matching failed")


def parse_js_literal(src: str) -> Any:
    i = 0

    def ws():
        nonlocal i
        while i < len(src) and src[i].isspace():
            i += 1

    def parse_value():
        nonlocal i
        ws()
        if i >= len(src):
            return None
        c = src[i]
        if c == "{":
            return parse_object()
        if c == "[":
            return parse_array()
        if c == '"':
            return parse_dstr()
        if c == "'":
            return parse_sstr()
        if src.startswith("true", i):
            i += 4
            return True
        if src.startswith("false", i):
            i += 5
            return False
        if src.startswith("null", i):
            i += 4
            return None
        if src.startswith("undefined", i):
            i += 9
            return None
        if src.startswith("!0", i):
            i += 2
            return True
        if src.startswith("!1", i):
            i += 2
            return False
        m = re.match(r'^-?[\d.]+([eE][+-]?\d+)?', src[i:])
        if m:
            i += len(m.group(0))
            val_str = m.group(0)
            return float(val_str) if ("." in val_str or "e" in val_str.lower()) else int(val_str)
        raise Exception(f"JS parse error at pos {i}: ...{src[i:i+20]}")

    def parse_dstr():
        nonlocal i
        res = []
        i += 1
        while i < len(src) and src[i] != '"':
            if src[i] == "\\":
                i += 1
                if i < len(src):
                    esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                    res.append(esc.get(src[i], src[i]))
                    i += 1
            else:
                res.append(src[i])
                i += 1
        i += 1
        return "".join(res)

    def parse_sstr():
        nonlocal i
        res = []
        i += 1
        while i < len(src) and src[i] != "'":
            if src[i] == "\\":
                i += 1
                if i < len(src):
                    esc = {"n": "\n", "t": "\t", "r": "\r", "'": "'", "\\": "\\"}
                    res.append(esc.get(src[i], src[i]))
                    i += 1
            else:
                res.append(src[i])
                i += 1
        i += 1
        return "".join(res)

    def parse_key():
        nonlocal i
        ws()
        if i < len(src) and src[i] in ['"', "'"]:
            return parse_dstr() if src[i] == '"' else parse_sstr()
        m = re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*', src[i:])
        if m:
            i += len(m.group(0))
            return m.group(0)
        raise Exception(f"Bad key at pos {i}: {src[i:i+20]}")

    def parse_object():
        nonlocal i
        obj = {}
        i += 1
        ws()
        while i < len(src) and src[i] != "}":
            if src[i] == ",":
                i += 1
                ws()
                continue
            k = parse_key()
            ws()
            if i < len(src) and src[i] == ":":
                i += 1
            obj[k] = parse_value()
            ws()
        i += 1
        return obj

    def parse_array():
        nonlocal i
        arr = []
        i += 1
        ws()
        while i < len(src) and src[i] != "]":
            if src[i] == ",":
                i += 1
                ws()
                continue
            arr.append(parse_value())
            ws()
        i += 1
        return arr

    return parse_value()


def parse_wasm_decrypt(wasm_bytes: bytes) -> Tuple[int, Any]:
    b = wasm_bytes
    pos = 8
    while pos < len(b):
        sec_id = b[pos]
        pos += 1
        sz = 0
        sh = 0
        while True:
            by = b[pos]
            pos += 1
            sz |= (by & 127) << sh
            sh += 7
            if not (by & 128):
                break
        if sec_id == 10:
            pos += 1
            sbs = 0
            sh2 = 0
            while True:
                by2 = b[pos]
                pos += 1
                sbs |= (by2 & 127) << sh2
                sh2 += 7
                if not (by2 & 128):
                    break
            pos += sbs
            break
        pos += sz

    rbs = 0
    sh3 = 0
    while True:
        by3 = b[pos]
        pos += 1
        rbs |= (by3 & 127) << sh3
        sh3 += 7
        if not (by3 & 128):
            break

    r = b[pos:pos + rbs]

    def leb(arr, idx):
        v = 0
        s = 0
        while True:
            b2 = arr[idx]
            idx += 1
            v |= (b2 & 127) << s
            s += 7
            if not (b2 & 128):
                break
        return v, idx

    xor_end = [32, 2, 32, 5, 106, 45, 0, 0, 115, 33, 6]
    tx_start = -1
    for i in range(len(r) - len(xor_end)):
        match = True
        for j in range(len(xor_end)):
            if r[i + j] != xor_end[j]:
                match = False
                break
        if match:
            tx_start = i + len(xor_end)
            break

    if tx_start < 0:
        raise Exception("WASM: transform start not found")

    tx_end = -1
    step = 36
    for i in range(tx_start, len(r) - 4):
        if r[i] == 32 and r[i+1] == 5 and r[i+2] == 65:
            val, ni = leb(r, i + 3)
            if ni < len(r) and r[ni] == 108:
                tx_end = i
                step = val
                break

    if tx_end < 0:
        raise Exception("WASM: keystream not found")

    code = r[tx_start:tx_end]

    def transform(input_byte: int) -> int:
        local6 = input_byte & 255
        stk = []
        c_idx = 0
        while c_idx < len(code):
            op = code[c_idx]
            c_idx += 1
            if op == 32:
                idx, ni = leb(code, c_idx)
                c_idx = ni
                stk.append(local6 if idx == 6 else 0)
            elif op == 33:
                idx, ni = leb(code, c_idx)
                c_idx = ni
                v = stk.pop()
                if idx == 6:
                    local6 = v & 255
            elif op == 65:
                v, ni = leb(code, c_idx)
                c_idx = ni
                stk.append(v)
            elif op == 106:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a + b2) & 255)
            elif op == 107:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a - b2 + 256) & 255)
            elif op == 113:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a & b2) & 255)
            elif op == 114:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a | b2) & 255)
            elif op == 115:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a ^ b2) & 255)
            elif op == 116:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a << (b2 & 7)) & 255)
            elif op == 118:
                b2 = stk.pop()
                a = stk.pop()
                stk.append((a >> (b2 & 7)) & 255)
        return local6

    return step, transform


def run_decrypt(wasm_bytes: bytes, frag1: bytes, kf2: bytes, t_bytes: bytes, seed_int: int) -> bytes:
    step, transform = parse_wasm_decrypt(wasm_bytes)
    out = bytearray(len(frag1))
    for i in range(len(frag1)):
        c = (frag1[i] ^ kf2[i] ^ t_bytes[i]) & 255
        out[i] = (transform(c) ^ (i * step + seed_int)) & 255
    return bytes(out)


async def decrypt_embed(html_content: str) -> dict:
    if not HAS_CRYPTO and not AES:
        raise RuntimeError("cryptography or pycryptodome library required for ReAnime decryption.")
    raw_ssr = extract_ssr_obj(html_content)
    data = parse_js_literal(raw_ssr)
    seed = data.get("obfuscation_seed")
    if not seed:
        raise Exception("obfuscation_seed missing")

    fields = derive_fields(seed)
    ocd = data.get("obfuscated_crypto_data")
    if not ocd:
        raise Exception("obfuscated_crypto_data missing")

    container = ocd.get(fields["containerName"])
    if not container:
        raise Exception(f"containerName '{fields['containerName']}' not in ocd")

    arr = container.get(fields["arrayName"])
    if not arr or not isinstance(arr, list):
        raise Exception(f"arrayName '{fields['arrayName']}' not in container")

    obj = arr[0].get(fields["objectName"])
    if not obj:
        raise Exception(f"objectName '{fields['objectName']}' not in arr[0]")

    frag1 = b64to_u8(obj[fields["keyField"]])
    iv = b64to_u8(obj[fields["ivField"]])
    kf2raw = data.get(fields["keyFrag2Field"])
    if not kf2raw:
        raise Exception(f"kf2 field '{fields['keyFrag2Field']}' not in data")
    kf2 = b64to_u8(kf2raw)

    token = data.get(fields["tokenField"])
    if not token:
        raise Exception(f"tokenField '{fields['tokenField']}' missing")

    tok_data = await fetch_json_with_proxy(f"{FLIX}/api/m3u8/{token}", headers={**HEADERS, "Referer": f"{BASE}/"})

    vid_key = sha256hex(token + "vid")[:10]
    key_key = sha256hex(token + "key")[:10]
    v_bytes = b64to_u8(tok_data.get(vid_key, ""))
    t_bytes = b64to_u8(tok_data.get(key_key, ""))

    if not v_bytes or not t_bytes:
        raise Exception("Token fields missing")

    seed_int = int(seed[:8], 16)
    w_payload = b64to_u8(data.get("w_payload", ""))
    if not w_payload:
        raise Exception("w_payload missing from embed data")

    wasm_out = run_decrypt(w_payload, frag1, kf2, t_bytes, seed_int)

    # PBKDF2 Key Derivation
    derived = hashlib.pbkdf2_hmac('sha256', wasm_out, seed.encode("utf-8"), 1000, dklen=32)
    derived = bytearray(derived)
    for i in range(32):
        derived[i] ^= ord(seed[i % len(seed)])

    aes_key_bytes = hashlib.sha256(bytes(derived)).digest()

    if HAS_CRYPTO:
        cipher = Cipher(algorithms.AES(aes_key_bytes), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        plain = decryptor.update(v_bytes) + decryptor.finalize()
    elif AES:
        cipher = AES.new(aes_key_bytes, AES.MODE_CBC, iv)
        plain = cipher.decrypt(v_bytes)
    else:
        raise RuntimeError("No AES cipher backend available")

    # PKCS7 unpad
    pad_len = plain[-1]
    if pad_len < 16:
        plain = plain[:-pad_len]

    url = plain.decode("utf-8", errors="ignore").strip().rstrip("\x00")
    if not url.startswith("http"):
        raise Exception(f"Unexpected decrypted value: {url[:60]}")

    return {
        "url": url,
        "subtitles": data.get("subtitles") or [],
        "thumbnails_vtt": data.get("thumbnails_vtt"),
        "video_title": data.get("video_title"),
        "intro_chapter": data.get("intro_chapter"),
        "outro_chapter": data.get("outro_chapter"),
        "video_id": data.get("video_id")
    }


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
    req_headers = {"Content-Type": "application/json", "User-Agent": UA5}
    url = "https://graphql.anilist.co"
    payload = {"query": query, "variables": {"id": int(anilist_id)}}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload, headers=req_headers)
            if res.status_code == 200:
                data = res.json()
                media = data.get("data", {}).get("Media")
                if media:
                    return media
    except Exception:
        pass

    if PROXIES:
        shuffled = list(PROXIES)
        random.shuffle(shuffled)
        for proxy in shuffled:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=10.0) as client:
                    res = await client.post(url, json=payload, headers=req_headers)
                    if res.status_code == 200:
                        data = res.json()
                        media = data.get("data", {}).get("Media")
                        if media:
                            return media
            except Exception:
                continue

    raise Exception(f"No media found for AniList ID {anilist_id}")


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


async def search_reanime(query: str) -> List[dict]:
    url = f"{BASE}/api/v1/search?q={quote(query)}&limit=10"
    try:
        data = await fetch_json_with_proxy(url, headers=HEADERS)
        return data.get("results") if isinstance(data.get("results"), list) else []
    except Exception:
        return []


async def fetch_anime_detail(anime_id: str) -> Optional[dict]:
    url = f"{BASE}/api/v1/anime/{anime_id}"
    try:
        return await fetch_json_with_proxy(url, headers=HEADERS)
    except Exception:
        return None


def extract_anilist_id_from_cover(cover_image: Optional[dict]) -> Optional[int]:
    if not isinstance(cover_image, dict):
        return None
    urls = [cover_image.get("extra_large"), cover_image.get("large"), cover_image.get("medium")]
    for url in urls:
        if url:
            m = re.search(r'anilist\.co/.*\/bx(\d+)-', url)
            if m:
                return int(m.group(1))
    return None


async def resolve_series(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    cache_key = f"np:reanime:{anilist_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    ctx = ctx or {}
    media = ctx.get("media") or await get_media(anilist_id)
    mal_id = media.get("idMal")
    titles = build_titles(media, ctx.get("anizip"))[:5]

    candidates = {}
    for q in titles:
        res = await search_reanime(q)
        for r in res:
            aid = r.get("anime_id")
            if aid and aid not in candidates:
                candidates[aid] = r

    # 1. Direct anilist_id match from search response
    for aid, r in candidates.items():
        if r.get("anilist_id") and int(r["anilist_id"]) == int(anilist_id):
            t_obj = r.get("title") or {}
            data = {
                "animeId": aid,
                "title": t_obj.get("english") or t_obj.get("romaji") or aid,
                "anilistId": int(anilist_id),
                "malId": r.get("mal_id"),
                "subbed": r.get("subbed"),
                "dubbed": r.get("dubbed"),
                "episodesCount": r.get("episodes"),
                "matchType": "search_anilist_id",
                "matchScore": 1
            }
            cache.set(cache_key, data, ttl_seconds=86400)
            return data

    # 2. Cover image matching
    for aid, r in candidates.items():
        cover_id = extract_anilist_id_from_cover(r.get("cover_image"))
        if cover_id and cover_id == int(anilist_id):
            data = {
                "animeId": aid,
                "title": (r.get("title") or {}).get("english") or (r.get("title") or {}).get("romaji") or aid,
                "anilistId": int(anilist_id),
                "malId": None,
                "subbed": r.get("subbed"),
                "dubbed": r.get("dubbed"),
                "episodesCount": r.get("episodes"),
                "matchType": "cover_image",
                "matchScore": 1
            }
            cache.set(cache_key, data, ttl_seconds=86400)
            return data

    # 3. Detailed anime check for top candidates
    needs_detail = [aid for aid, r in list(candidates.items())[:5] if extract_anilist_id_from_cover(r.get("cover_image")) is None]
    details = await asyncio.gather(*[fetch_anime_detail(aid) for aid in needs_detail], return_exceptions=True)

    for aid, detail in zip(needs_detail, details):
        if isinstance(detail, dict) and detail.get("anilist_id") and int(detail["anilist_id"]) == int(anilist_id):
            t_obj = detail.get("title") or {}
            data = {
                "animeId": aid,
                "title": t_obj.get("english") or t_obj.get("romaji") or aid,
                "anilistId": int(anilist_id),
                "malId": detail.get("mal_id"),
                "subbed": detail.get("subbed"),
                "dubbed": detail.get("dubbed"),
                "episodesCount": detail.get("episodes"),
                "matchType": "anilist",
                "matchScore": 1
            }
            cache.set(cache_key, data, ttl_seconds=86400)
            return data

    if mal_id:
        for aid, detail in zip(needs_detail, details):
            if isinstance(detail, dict) and detail.get("mal_id") and int(detail["mal_id"]) == int(mal_id):
                t_obj = detail.get("title") or {}
                data = {
                    "animeId": aid,
                    "title": t_obj.get("english") or t_obj.get("romaji") or aid,
                    "anilistId": int(anilist_id),
                    "malId": int(mal_id),
                    "subbed": detail.get("subbed"),
                    "dubbed": detail.get("dubbed"),
                    "episodesCount": detail.get("episodes"),
                    "matchType": "mal",
                    "matchScore": 0.9
                }
                cache.set(cache_key, data, ttl_seconds=86400)
                return data

    raise Exception(f"No confirmed reanime match for AniList {anilist_id}")


async def fetch_episodes_list(anime_id: str, limit: int = 2000) -> List[dict]:
    url = f"{BASE}/api/v1/anime/{anime_id}/episodes?limit={limit}"
    data = await fetch_json_with_proxy(url, headers=HEADERS)
    return data.get("data") if isinstance(data.get("data"), list) else []


def merge_episode(anilist_id: int, ep: dict, meta: Optional[dict], audio: str) -> dict:
    num = ep.get("episode_number")
    m_title = (meta.get("title") or {}) if meta else {}
    return {
        "id": f"watch/reanime/{anilist_id}/{audio}/reanime-{num}",
        "number": num,
        "title": m_title.get("en") or m_title.get("x-jat") or ep.get("title") or f"Episode {num}",
        "titleJapanese": m_title.get("ja") or ep.get("title_japanese"),
        "titleRomanji": m_title.get("x-jat") or ep.get("title_romanji"),
        "image": meta.get("image") if meta else ep.get("thumbnail"),
        "airDate": meta.get("airdate") if meta else ep.get("aired"),
        "duration": meta.get("runtime") * 60 if meta and meta.get("runtime") else (ep.get("duration") * 60 if ep.get("duration") else None),
        "score": None,
        "filler": ep.get("is_filler", False),
        "recap": ep.get("is_recap", False),
        "description": meta.get("overview") if meta else ep.get("description"),
        "audio": audio
    }


async def get_episodes(anilist_id: int, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or {}
    series = await resolve_series(anilist_id, ctx)
    reanime_eps = await fetch_episodes_list(series["animeId"])
    if not reanime_eps:
        raise Exception(f"No reanime episodes found for AniList {anilist_id} (slug {series['animeId']})")

    has_sub = series.get("subbed") is None or series.get("subbed", 0) > 0
    dub_count = series.get("dubbed") or 0

    sub = []
    dub = []
    for ep in reanime_eps:
        ep_num = ep.get("episode_number")
        if has_sub:
            sub.append(merge_episode(anilist_id, ep, None, "sub"))
        if dub_count > 0 and ep_num and ep_num <= dub_count:
            dub.append(merge_episode(anilist_id, ep, None, "dub"))

    sub.sort(key=lambda x: x["number"])
    dub.sort(key=lambda x: x["number"])

    return {
        "meta": {"title": series["title"], "malId": series.get("malId"), "animeId": series["animeId"]},
        "episodes": {"sub": sub, "dub": dub}
    }


async def resolve_stream(anilist_id: int, audio: str, ep: int) -> dict:
    series = await resolve_series(anilist_id)
    title_str = series["title"]
    slug = series["animeId"]
    order = {"HD-2": 0, "HD-1": 1}

    async def fetch_watch():
        url = f"{BASE}/api/watch/{slug}/{ep}"
        try:
            return await fetch_json_with_proxy(url, headers=HEADERS)
        except Exception:
            return None

    async def fetch_flix():
        url = f"{BASE}/api/flix/{anilist_id}/{ep}"
        try:
            return await fetch_json_with_proxy(url, headers=HEADERS)
        except Exception:
            return None

    watch_data, flix_data = await asyncio.gather(fetch_watch(), fetch_flix())
    watch_links = (watch_data.get("episode_links") if isinstance(watch_data, dict) else []) or []
    links = list(watch_links)

    if isinstance(flix_data, dict) and flix_data.get("success") and isinstance(flix_data.get("servers"), list):
        seen = {s.get("$id") for s in links if "$id" in s}
        for s in flix_data["servers"]:
            if s.get("$id") not in seen:
                links.append(s)

    audio_types = ["sub", "s-sub"] if audio == "sub" else ["dub", "s-dub"]
    servers = [s for s in links if s.get("dataType") in audio_types]
    servers.sort(key=lambda s: order.get(s.get("serverName"), 9))

    if not servers:
        raise Exception(f"No {audio} servers for '{title_str}' ep {ep}")

    # Try each available server until one successfully decrypts
    last_err = None
    for target_server in servers:
        data_link = target_server.get("dataLink")
        if not data_link:
            continue
        try:
            embed_html = await fetch_page_with_proxy(data_link, headers={**HEADERS, "Referer": f"{BASE}/"})
            stream = await decrypt_embed(embed_html)
            return {
                "title": title_str,
                "slug": slug,
                "watchData": watch_data,
                "stream": stream,
                "server": target_server.get("serverName"),
                "servers": servers
            }
        except Exception as err:
            last_err = err
            continue

    raise Exception(f"Failed to extract stream from Flixcloud servers: {last_err}")


async def handle_watch(anilist_id: int, audio: str, ep_num: int) -> dict:
    ep = int(ep_num)
    if audio == "all":
        async def safe_watch(aud):
            try:
                return await handle_watch(anilist_id, aud, ep)
            except Exception as e:
                return {"error": str(e)}

        sub_data, dub_data = await asyncio.gather(safe_watch("sub"), safe_watch("dub"))
        return {
            "anilistId": int(anilist_id),
            "episode": ep,
            "audio": "all",
            "sub": sub_data,
            "dub": dub_data
        }

    resolved = await resolve_stream(anilist_id, audio, ep)
    title_str = resolved["title"]
    slug = resolved["slug"]
    watch_data = resolved["watchData"]
    stream = resolved["stream"]
    server = resolved["server"]
    servers = resolved["servers"]

    return {
        "anime": title_str,
        "slug": slug,
        "ep": ep,
        "audio": audio,
        "server": server,
        "stream_url": stream["url"],
        "streams": [
            {"url": stream["url"], "type": "hls"},
            *[{"url": s.get("dataLink"), "type": "embed", "server": s.get("serverName")} for s in servers if s.get("dataLink")]
        ],
        "subtitles": stream.get("subtitles") or [],
        "thumbnails_vtt": stream.get("thumbnails_vtt"),
        "video_title": stream.get("video_title"),
        "intro": stream.get("intro_chapter"),
        "outro": stream.get("outro_chapter"),
        "intro_start": watch_data.get("intro_start") if watch_data else None,
        "intro_end": watch_data.get("intro_end") if watch_data else None,
        "outro_start": watch_data.get("outro_start") if watch_data else None,
        "outro_end": watch_data.get("outro_end") if watch_data else None,
        "allServers": [{"name": s.get("serverName"), "type": s.get("dataType"), "embed": s.get("dataLink")} for s in servers]
    }


if __name__ == "__main__":
    async def test():
        anilist_id = 20  # Naruto AniList ID
        ep_num = 220
        print(f"Testing ReAnime extraction (SUB & DUB) for AniList ID {anilist_id}, Episode {ep_num}...")
        try:
            watch_data = await handle_watch(anilist_id, "all", ep_num)
            print("\nCombined SUB & DUB streams result:", json.dumps(watch_data, indent=2))
        except Exception as e:
            import traceback
            print("Error during test:", e)
            traceback.print_exc()

    asyncio.run(test())
