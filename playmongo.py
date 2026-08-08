import logging
import random
import re
import time
import warnings
from urllib.parse import urljoin, urlparse

from urllib3.exceptions import InsecureRequestWarning

try:
    from curl_cffi.requests import Session as CffiSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    import niquests
    HAS_NIQUESTS = True
except ImportError:
    HAS_NIQUESTS = False

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

warnings.simplefilter("ignore", InsecureRequestWarning)

# -----------------------------
# Constants
# -----------------------------
RANDOM_STRING_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
PASS_MD5_PATTERN = r"\$\.get\('([^']*\/pass_md5\/[^']*)'"
TOKEN_PATTERN = r"token=([a-zA-Z0-9]+)"

# curl_cffi browser impersonation target — mimics Chrome 124 TLS fingerprint
IMPERSONATE = "chrome124"


try:
    from proxies import PROXIES
except ImportError:
    PROXIES = []


# -----------------------------
# Helper Functions
# -----------------------------
def _get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _make_headers(referer, base_url, xhr=False):
    h = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Origin": base_url,
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    }
    if xhr:
        h["Accept"] = "*/*"
        h["X-Requested-With"] = "XMLHttpRequest"
        h["Sec-Fetch-Dest"] = "empty"
        h["Sec-Fetch-Mode"] = "cors"
        h["Sec-Fetch-Site"] = "same-origin"
    else:
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        h["Upgrade-Insecure-Requests"] = "1"
        h["Sec-Fetch-Dest"] = "document"
        h["Sec-Fetch-Mode"] = "navigate"
        h["Sec-Fetch-Site"] = "same-origin"
    return h


def _extract_regex(pattern, content, name, url):
    match = re.search(pattern, content)
    if not match:
        raise ValueError(f"{name} not found in {url}")
    return match.group(1)


def _generate_random_string(length=10):
    return "".join(random.choices(RANDOM_STRING_CHARS, k=length))


def _create_session(proxy=None, impersonate="chrome124"):
    """
    Create a session that bypasses Cloudflare with optional proxy support and browser impersonation.
    """
    if HAS_CURL_CFFI:
        kwargs = {"impersonate": impersonate, "verify": False}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        session = CffiSession(**kwargs)
        return session, True
    elif HAS_NIQUESTS:
        session = niquests.Session()
        session.verify = False
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        return session, False
    else:
        import httpx
        kwargs = {"verify": False, "follow_redirects": True, "timeout": 15.0}
        if proxy:
            kwargs["proxy"] = proxy
        session = httpx.Client(**kwargs)
        return session, False


def _get(session, url, headers, **kwargs):
    """Unified get() that works for curl_cffi, niquests, and httpx sessions."""
    if hasattr(session, "get"):
        return session.get(url, headers=headers, **kwargs)
    return session.get(url, headers=headers, follow_redirects=True, **kwargs)


# -----------------------------
# Main Doodstream Function
# -----------------------------
def get_direct_link_from_doodstream(embed_url):
    """Extract the direct video link from a Doodstream embed URL using proxies.py if needed."""
    if not embed_url:
        raise ValueError("Embed URL cannot be empty")

    logging.info(f"Extracting Doodstream direct link from: {embed_url}")

    proxy_candidates = [None] + list(PROXIES)
    impersonate_targets = ["chrome124", "chrome120", "chrome110"] if HAS_CURL_CFFI else ["default"]
    last_error = None

    for proxy in proxy_candidates:
        for imp in impersonate_targets:
            p_name = f"{proxy} ({imp})" if proxy else f"Direct ({imp})"
            try:
                session, using_cffi = _create_session(proxy=proxy, impersonate=imp if HAS_CURL_CFFI else "chrome124")

                # Step 1: resolve full redirect chain
                resp = _get(session, embed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
                status = getattr(resp, "status_code", getattr(resp, "status", 200))
                if status == 403:
                    raise ValueError(f"403 Forbidden on embed URL via {p_name}")

                final_embed_url = str(getattr(resp, "url", embed_url))
                final_base = _get_base_url(final_embed_url)

                # Step 2: cookie warm-up
                try:
                    _get(session, f"{final_base}/", headers=_make_headers(f"{final_base}/", final_base))
                except Exception:
                    pass

                # Step 3: fetch embed HTML
                embed_resp = _get(
                    session,
                    final_embed_url,
                    headers=_make_headers(f"{final_base}/", final_base),
                )
                status_embed = getattr(embed_resp, "status_code", getattr(embed_resp, "status", 200))
                if status_embed == 403:
                    raise ValueError(f"403 Forbidden on embed HTML page via {p_name}")

                embed_html = getattr(embed_resp, "text", "") or getattr(embed_resp, "content", b"").decode("utf-8", "ignore")

                # Step 4: extract pass_md5 URL and token
                pass_md5_path = _extract_regex(PASS_MD5_PATTERN, embed_html, "pass_md5 URL", final_embed_url)
                pass_md5_url = pass_md5_path if pass_md5_path.startswith("http") else urljoin(final_base, pass_md5_path)
                token = _extract_regex(TOKEN_PATTERN, embed_html, "token", final_embed_url)

                # Step 5: XHR request to pass_md5 endpoint
                md5_resp = _get(
                    session,
                    pass_md5_url,
                    headers=_make_headers(final_embed_url, final_base, xhr=True),
                )
                video_base_url = (getattr(md5_resp, "text", "") or getattr(md5_resp, "content", b"").decode("utf-8", "ignore")).strip()

                if not video_base_url or video_base_url.startswith("<") or "not found" in video_base_url.lower():
                    raise ValueError(f"Invalid video base URL from {pass_md5_url}")

                # Step 6: build direct link
                expiry = int(time.time() * 1000)
                direct_link = f"{video_base_url}{_generate_random_string(10)}?token={token}&expiry={expiry}"

                logging.info(f"Successfully extracted Doodstream direct link via {p_name}")
                return direct_link, final_base

            except Exception as err:
                logging.warning(f"Doodstream extraction failed via {p_name}: {err}")
                last_error = err
                continue

    raise RuntimeError(f"All extraction attempts failed for {embed_url}. Last error: {last_error}")


def get_preview_image_link_from_doodstream(embed_url):
    raise NotImplementedError("Preview image extraction is not implemented yet.")


if __name__ == "__main__":
    import sys
    from hianime_playmongo import get_playmongo_streams_by_mal_id

    mal_input = 60425
    ep_input = 1

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg.startswith("http"):
            # Extract direct URL from Doodstream / PlayMongo URL
            direct_link, final_base = get_direct_link_from_doodstream(arg)
            print("=" * 60)
            print("Direct stream link:", direct_link)
            print("Referer           :", f"{final_base}/")
            print("=" * 60)
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

    get_playmongo_streams_by_mal_id(mal_input, ep_input)