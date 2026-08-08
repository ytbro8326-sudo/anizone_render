import re
import random
import time
import httpx
from proxies import PROXIES

embed_url = "https://playmogo.com/e/i2oifvy9edjn"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

print("Testing direct connection first...")
proxy_list = [None] + PROXIES

for p in proxy_list:
    p_name = p if p else "Direct (no proxy)"
    print(f"\n--- Trying {p_name} ---")
    try:
        kwargs = {"timeout": 10.0, "follow_redirects": True, "verify": False}
        if p:
            kwargs["proxy"] = p
            
        with httpx.Client(**kwargs) as client:
            resp = client.get(embed_url, headers=headers)
            print("Status:", resp.status_code, "Final URL:", resp.url)
            html = resp.text
            
            match_pass = re.search(r"\$\.get\('([^']*\/pass_md5\/[^']*)'", html)
            if match_pass:
                pass_path = match_pass.group(1)
                token_m = re.search(r"token=([a-zA-Z0-9]+)", html)
                token = token_m.group(1) if token_m else ""
                print("✓ PASS MD5 FOUND! Path:", pass_path, "Token:", token)

                final_base = f"{resp.url.scheme}://{resp.url.netloc}"
                pass_url = pass_path if pass_path.startswith("http") else f"{final_base}{pass_path}"
                
                m_headers = dict(headers)
                m_headers["Referer"] = str(resp.url)
                m_headers["X-Requested-With"] = "XMLHttpRequest"
                
                m_resp = client.get(pass_url, headers=m_headers)
                v_base = m_resp.text.strip()
                print("Video Base:", v_base)
                
                rand_str = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", k=10))
                expiry = int(time.time() * 1000)
                final_link = f"{v_base}{rand_str}?token={token}&expiry={expiry}"
                print("✓ SUCCESSFUL DIRECT LINK:\n", final_link)
                break
            else:
                print("❌ pass_md5 not found in HTML (Length:", len(html), ")")
    except Exception as e:
        print("❌ Error with", p_name, ":", e)
