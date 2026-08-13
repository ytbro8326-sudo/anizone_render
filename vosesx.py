import base64
import binascii
import json
import logging
import re
import random
import time
from urllib.parse import urlparse
import httpx

try:
    from proxies import PROXIES
except ImportError:
    PROXIES = [
        "http://dxicdysy:yndikr9coeto@31.59.20.176:6754",
        "http://dxicdysy:yndikr9coeto@31.56.127.193:7684",
        "http://dxicdysy:yndikr9coeto@45.38.107.97:6014",
        "http://dxicdysy:yndikr9coeto@198.105.121.200:6462",
        "http://dxicdysy:yndikr9coeto@64.137.96.74:6641",
        "http://dxicdysy:yndikr9coeto@198.23.243.226:6361",
        "http://dxicdysy:yndikr9coeto@38.154.185.97:6370",
        "http://dxicdysy:yndikr9coeto@84.247.60.125:6095",
        "http://dxicdysy:yndikr9coeto@142.111.67.146:5611",
        "http://dxicdysy:yndikr9coeto@191.96.254.138:6185",
    ]

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# -----------------------------
# Precompiled regex patterns
# -----------------------------
REDIRECT_PATTERN = re.compile(r"https?://[^'\"<>]+")
B64_PATTERN = re.compile(r"var a168c='([^']+)'")
HLS_PATTERN = re.compile(r"'hls': '(?P<hls>[^']+)'")
VOE_SCRIPT_PATTERN = re.compile(
    r'<script type="application/json">\s*"(?:\\.|[^"\\])*"\s*</script>', re.DOTALL
)
JUNK_PARTS = ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]


def fetch_url(url: str, headers: dict = None, method: str = "GET", timeout: float = 15.0) -> httpx.Response:
    """
    Fetch URL using proxies directly from proxies.py (with direct request fallback).
    """
    if headers is None:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    # Shuffle proxies from proxies.py
    proxy_list = list(PROXIES)
    random.shuffle(proxy_list)

    # 1. Iterate through proxies from proxies.py
    for proxy in proxy_list:
        try:
            with httpx.Client(proxy=proxy, timeout=10.0, follow_redirects=True) as client:
                if method.upper() == "HEAD":
                    resp = client.head(url, headers=headers)
                else:
                    resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp
                logger.warning(f"Proxy {proxy} returned HTTP status {resp.status_code}")
        except Exception as err:
            logger.warning(f"Proxy {proxy} request failed: {err}")

    # 2. Direct request fallback if all configured proxies fail
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if method.upper() == "HEAD":
                resp = client.head(url, headers=headers)
            else:
                resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp
    except Exception as err:
        logger.error(f"Direct fallback request failed: {err}")

    raise ValueError(f"Unable to fetch {url} (All proxies from proxies.py and direct request failed).")


# -----------------------------
# Helper decoding functions
# -----------------------------
def shift_letters(input_str: str) -> str:
    """Apply ROT13 cipher to alphabetic characters."""
    result = []
    for c in input_str:
        code = ord(c)
        if 65 <= code <= 90:
            code = (code - 65 + 13) % 26 + 65
        elif 97 <= code <= 122:
            code = (code - 97 + 13) % 26 + 97
        result.append(chr(code))
    return "".join(result)


def replace_junk(input_str: str) -> str:
    """Replace junk patterns with underscores."""
    for part in JUNK_PARTS:
        input_str = input_str.replace(part, "_")
    return input_str


def shift_back(s: str, n: int) -> str:
    """Shift characters back by n positions."""
    return "".join(chr(ord(c) - n) for c in s)


def decode_voe_string(encoded: str) -> dict:
    """Decode VOE encoded string to a JSON object."""
    try:
        step1 = shift_letters(encoded)
        step2 = replace_junk(step1).replace("_", "")
        step3 = base64.b64decode(step2).decode()
        step4 = shift_back(step3, 3)
        step5 = base64.b64decode(step4[::-1]).decode()
        return json.loads(step5)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ValueError(f"Failed to decode VOE string: {err}") from err


def extract_voe_source_from_html(html: str) -> str:
    """Extract VOE video source using regex + decode_voe_string"""
    try:
        script_blocks = re.findall(
            r'<script\s+type=["\']application/json["\']>(.*?)</script>', html, re.DOTALL
        )
        if not script_blocks:
            return None

        for script_block in script_blocks:
            encoded_text = script_block.strip()
            if encoded_text.startswith('"') and encoded_text.endswith('"'):
                encoded_text = encoded_text[1:-1]

            encoded_text = encoded_text.encode().decode("unicode_escape")

            try:
                decoded = decode_voe_string(encoded_text)
                source = decoded.get("source")
                if source:
                    return source
            except ValueError:
                continue

        return None
    except Exception:
        return None


# -----------------------------
# Main VOE functions
# -----------------------------
def get_direct_link_from_voe(embeded_voe_link: str, headers: dict = None, max_retries: int = 3, timeout: float = 30.0) -> str:
    """Get direct VOE video URL using proxies.py proxies."""
    parsed_embed_url = urlparse((embeded_voe_link or "").strip())
    if not parsed_embed_url.scheme or not parsed_embed_url.netloc:
        raise ValueError(f"Invalid VOE URL: {embeded_voe_link!r}")

    resp = fetch_url(embeded_voe_link, headers=headers, timeout=timeout)
    html = resp.text

    source = extract_voe_source_from_html(html)
    if source:
        return source

    redirect_match = REDIRECT_PATTERN.search(html)
    if redirect_match:
        redirect_url = redirect_match.group(0)
        resp = fetch_url(redirect_url, headers=headers, timeout=timeout)
        html = resp.text
        source = extract_voe_source_from_html(html)
        if source:
            return source

    raise ValueError("No VOE video source found in page.")


def get_preview_image_link_from_voe(embeded_voe_link: str, headers: dict = None) -> str:
    """Get VOE preview image URL using proxies.py proxies."""
    parsed_embed_url = urlparse((embeded_voe_link or "").strip())
    if not parsed_embed_url.scheme or not parsed_embed_url.netloc:
        raise ValueError(f"Invalid VOE URL: {embeded_voe_link!r}")

    resp = fetch_url(embeded_voe_link, headers=headers)
    html = resp.text

    redirect_match = REDIRECT_PATTERN.search(html)
    if not redirect_match:
        raise ValueError("No redirect URL found in VOE response.")

    redirect_url = redirect_match.group(0)
    image_url = f"{redirect_url.replace('/e/', '/cache/')}_storyboard_L2.jpg"

    try:
        head_resp = fetch_url(image_url, headers=headers, method="HEAD")
        if "image" not in head_resp.headers.get("Content-Type", ""):
            raise ValueError("Preview image not reachable.")
        return image_url
    except Exception:
        return image_url
