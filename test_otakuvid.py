import urllib.request
import re
import json

url = "https://otakuvid.online/embed/jv6woapra6gl"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as res:
        html = res.read().decode("utf-8", errors="ignore")
        print("Status:", res.status)
        print("HTML length:", len(html))

        # Check packed JS
        m = re.search(
            r"eval\(function\(p,a,c,k,e,d\)\{.*?\}"
            r"\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)\)\)",
            html,
            re.DOTALL,
        )
        if m:
            print("Packed JS found!")
            obfuscated, base, count, word_list = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split("|")
            chars = "0123456789abcdefghijklmnopqrstuvwxyz"

            def unbase(n, b):
                if n == 0: return "0"
                res = ""
                while n:
                    res = chars[n % b] + res
                    n //= b
                return res

            lookup = {unbase(i, base): (word_list[i] if i < len(word_list) and word_list[i] else unbase(i, base)) for i in range(count)}
            decoded = re.sub(r"\b\w+\b", lambda match: lookup.get(match.group(0), match.group(0)), obfuscated)
            print("Decoded JS preview:\n", decoded[:1000])
        else:
            print("No packed JS. HTML preview:\n", html[:1000])

except Exception as e:
    print("Error:", e)
