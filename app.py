import os
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from anizone_to_custom import process_mal_episode, get_media_by_mal_id
import convertedanimg
import converkichsasanime
import anidbpy
import converted2dhive
import converted_reanime
import anibd
import anikoto
import animenosub
import anineko
import hianime_otakuhg
import hianime_playmongo
import vivibebe_site
import flixcloud
import oktavid
try:
    import vosesx
except ImportError:
    from proxy import vosesx

app = FastAPI(
    title="Multi-Server Anime Stream API",
    description="Render-deployable Stream URL Extractor supporting AniZone, ReAnime, 2DHive, AnimeG, KichsasAnime, AniDB, AniBD, AniKoto, AnimeNoSub, and AniNeko",
    version="3.0.0"
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def mal_to_anilist_id(mal_id: int) -> int:
    try:
        media = get_media_by_mal_id(mal_id)
        return media["id"]
    except Exception as e:
        raise Exception(f"Failed to resolve AniList ID from MAL ID {mal_id}: {e}")


@app.get("/", response_class=HTMLResponse)
async def render_webpage():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Multi-Server Anime Stream Extractor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07090e;
      --card-bg: rgba(18, 22, 33, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
      --accent-glow: rgba(99, 102, 241, 0.35);
      --text: #f3f4f6;
      --subtext: #9ca3af;
      --code-bg: #0d1117;
      --success: #10b981;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background-color: var(--bg);
      background-image: 
        radial-gradient(at 10% 10%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
        radial-gradient(at 90% 90%, rgba(168, 85, 247, 0.12) 0px, transparent 50%);
      color: var(--text);
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      padding: 40px 20px;
    }

    .container {
      max-width: 960px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }

    header { text-align: center; margin-bottom: 8px; }

    .badge {
      display: inline-block;
      padding: 6px 14px;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #818cf8;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 12px;
    }

    header h1 {
      font-size: 2.5rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: var(--accent-gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 8px;
    }

    header p { color: var(--subtext); font-size: 1rem; }

    .card {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 28px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
    }

    .server-selector {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 10px;
      margin-bottom: 20px;
    }

    .server-btn {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--card-border);
      color: var(--subtext);
      padding: 10px 12px;
      border-radius: 10px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s ease;
    }

    .server-btn:hover {
      background: rgba(99, 102, 241, 0.15);
      border-color: #6366f1;
      color: #fff;
    }

    .server-btn.active {
      background: var(--accent-gradient);
      border-color: transparent;
      color: #fff;
      box-shadow: 0 4px 12px var(--accent-glow);
    }

    .input-grid {
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 16px;
      align-items: flex-end;
    }

    @media (max-width: 640px) {
      .input-grid { grid-template-columns: 1fr; }
    }

    .form-group { display: flex; flex-direction: column; gap: 8px; }
    .form-group label { font-size: 0.85rem; font-weight: 600; color: #d1d5db; }

    input {
      background: rgba(10, 14, 23, 0.8);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 12px 16px;
      color: #fff;
      font-size: 0.95rem;
      outline: none;
      transition: all 0.2s ease;
    }

    input:focus {
      border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
    }

    .btn {
      background: var(--accent-gradient);
      color: white;
      border: none;
      border-radius: 10px;
      padding: 12px 24px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      height: 46px;
      box-shadow: 0 4px 15px var(--accent-glow);
      transition: transform 0.15s ease, opacity 0.15s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }

    .btn:hover { opacity: 0.92; transform: translateY(-1px); }
    .btn:active { transform: translateY(0); }

    .presets {
      display: flex;
      gap: 8px;
      margin-top: 16px;
      flex-wrap: wrap;
      align-items: center;
    }

    .preset-title { font-size: 0.8rem; color: var(--subtext); margin-right: 4px; }

    .chip {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--card-border);
      color: #e5e7eb;
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 0.78rem;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .chip:hover {
      background: rgba(99, 102, 241, 0.2);
      border-color: #6366f1;
    }

    .results-card { display: none; }

    .meta-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 16px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
    }

    .anime-title { font-size: 1.25rem; font-weight: 700; color: #fff; }

    .url-box {
      background: var(--code-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }

    .url-text {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      color: #34d399;
      word-break: break-all;
    }

    .btn-copy {
      background: rgba(255, 255, 255, 0.08);
      border: none;
      color: #fff;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.75rem;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.2s ease;
    }

    .btn-copy:hover { background: rgba(255, 255, 255, 0.18); }

    pre {
      background: var(--code-bg);
      padding: 16px;
      border-radius: 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      color: #93c5fd;
      overflow-x: auto;
      max-height: 400px;
    }

    .tabs {
      display: flex;
      gap: 12px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }

    .tab {
      padding: 8px 16px;
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--subtext);
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }

    .tab.active { color: #6366f1; border-bottom-color: #6366f1; }

    .tab-content { display: none; }
    .tab-content.active { display: block; }

    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--success);
      color: white;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      display: none;
      box-shadow: 0 10px 20px rgba(0,0,0,0.3);
      z-index: 1000;
    }

    .loader {
      width: 18px;
      height: 18px;
      border: 2px solid #ffffff;
      border-bottom-color: transparent;
      border-radius: 50%;
      display: inline-block;
      animation: rotation 1s linear infinite;
    }

    @keyframes rotation {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="badge">Multi-Server Anime Extractor v3.0</div>
      <h1>Direct HLS & MP4 Stream Extractor</h1>
      <p>Select a server engine and enter MAL ID & Episode Number to extract high-speed video streams</p>
    </header>

    <div class="card">
      <label style="font-size: 0.85rem; font-weight: 600; color: #d1d5db; display: block; margin-bottom: 8px;">Choose Server Engine:</label>
      <div class="server-selector">
        <div class="server-btn active" onclick="selectServer('anizone', this)">AniZone</div>
        <div class="server-btn" onclick="selectServer('vivibebe', this)">ViviBebe</div>
        <div class="server-btn" onclick="selectServer('otakuhg', this)">OtakuHG</div>
        <div class="server-btn" onclick="selectServer('oktavid', this)">OktaVid</div>
        <div class="server-btn" onclick="selectServer('playmongo', this)">PlayMongo</div>
        <div class="server-btn" onclick="selectServer('flixcloud', this)">FlixCloud</div>
        <div class="server-btn" onclick="selectServer('voe', this)">VOE.sx</div>
        <div class="server-btn" onclick="selectServer('reanime', this)">ReAnime</div>
        <div class="server-btn" onclick="selectServer('2dhive', this)">2DHive</div>
        <div class="server-btn" onclick="selectServer('anibd', this)">AniBD</div>
        <div class="server-btn" onclick="selectServer('anikoto', this)">AniKoto</div>
        <div class="server-btn" onclick="selectServer('animenosub', this)">AnimeNoSub</div>
        <div class="server-btn" onclick="selectServer('anineko', this)">AniNeko</div>
        <div class="server-btn" onclick="selectServer('animeg', this)">AnimeG</div>
        <div class="server-btn" onclick="selectServer('kichsas', this)">Kichsas</div>
        <div class="server-btn" onclick="selectServer('anidb', this)">AniDB</div>
        <div class="server-btn" onclick="selectServer('all', this)">All Servers</div>
      </div>

      <div class="input-grid" id="malInputGrid">
        <div class="form-group" id="malGroup">
          <label for="malId">MyAnimeList ID (MAL ID)</label>
          <input type="number" id="malId" value="21" placeholder="e.g. 21">
        </div>
        <div class="form-group" id="epGroup">
          <label for="epNum">Episode Number</label>
          <input type="number" id="epNum" value="1" placeholder="e.g. 1">
        </div>
        <div class="form-group" id="voeGroup" style="display:none; grid-column: 1 / span 2;">
          <label for="voeUrl">VOE Embed Link / URL</label>
          <input type="text" id="voeUrl" value="https://voe.sx/e/80z1tpfbkgyc" placeholder="e.g. https://voe.sx/e/80z1tpfbkgyc">
        </div>
        <div class="form-group" id="otakuvidGroup" style="display:none; grid-column: 1 / span 2; align-items: center; flex-direction: row; gap: 8px;">
          <input type="checkbox" id="includeOtakuvid" style="width: auto; cursor: pointer;">
          <label for="includeOtakuvid" style="cursor: pointer; color: #e5e7eb; font-size: 0.85rem;">Include OtakuVid / EarnVids streams (otakuvid.online)</label>
        </div>
        <button class="btn" id="btnFetch">
          <span id="btnText">Extract Streams</span>
          <span id="btnSpinner" style="display:none;"><span class="loader"></span></span>
        </button>
      </div>

      <div class="presets">
        <span class="preset-title">Quick Presets:</span>
        <div class="chip" onclick="setPreset(60425, 1)">MAL 60425 Ep 1</div>
        <div class="chip" onclick="setVoePreset('https://voe.sx/e/80z1tpfbkgyc')">VOE: 80z1tpfbkgyc</div>
        <div class="chip" onclick="setPreset(21, 1)">One Piece Ep 1</div>
        <div class="chip" onclick="setPreset(20, 220)">Naruto Ep 220</div>
        <div class="chip" onclick="setPreset(1735, 1)">Naruto Shippuden Ep 1</div>
        <div class="chip" onclick="setPreset(30276, 1)">One Punch Man Ep 1</div>
      </div>
    </div>

    <div class="card results-card" id="resultsCard">
      <div class="meta-bar">
        <div>
          <div class="anime-title" id="resTitle">Anime Title</div>
          <div style="font-size: 0.8rem; color: var(--subtext); margin-top: 4px;" id="resSub">Stream Output</div>
        </div>
      </div>

      <div class="tabs">
        <div class="tab active" onclick="switchTab('streamsTab', this)">Formatted Streams</div>
        <div class="tab" onclick="switchTab('jsonTab', this)">Raw JSON Response</div>
      </div>

      <div class="tab-content active" id="streamsTab">
        <div class="url-list" id="streamsList"></div>
      </div>

      <div class="tab-content" id="jsonTab">
        <pre class="json-box" id="jsonBox">{}</pre>
      </div>
    </div>
  </div>

  <div class="toast" id="toast">Copied to clipboard!</div>

  <script>
    let selectedServer = 'anizone';

    function selectServer(srv, el) {
      selectedServer = srv;
      document.querySelectorAll('.server-btn').forEach(b => b.classList.remove('active'));
      el.classList.add('active');
      if (srv === 'voe') {
        document.getElementById('malGroup').style.display = 'none';
        document.getElementById('epGroup').style.display = 'none';
        document.getElementById('voeGroup').style.display = 'flex';
        document.getElementById('otakuvidGroup').style.display = 'none';
      } else {
        document.getElementById('malGroup').style.display = 'flex';
        document.getElementById('epGroup').style.display = 'flex';
        document.getElementById('voeGroup').style.display = 'none';
        document.getElementById('otakuvidGroup').style.display = srv === 'otakuhg' ? 'flex' : 'none';
      }
    }

    function setPreset(malId, ep) {
      const srvBtn = document.querySelector('.server-btn');
      if (srvBtn) selectServer('anizone', srvBtn);
      document.getElementById('malId').value = malId;
      document.getElementById('epNum').value = ep;
      document.getElementById('btnFetch').click();
    }

    function setVoePreset(url) {
      const voeBtn = Array.from(document.querySelectorAll('.server-btn')).find(b => b.textContent.includes('VOE'));
      if (voeBtn) selectServer('voe', voeBtn);
      document.getElementById('voeUrl').value = url;
      document.getElementById('btnFetch').click();
    }

    function switchTab(tabId, tabEl) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tabEl.classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }

    function copyText(text) {
      navigator.clipboard.writeText(text);
      showToast("URL copied to clipboard!");
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      toast.textContent = msg;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 2000);
    }

    const btn = document.getElementById('btnFetch');
    const btnText = document.getElementById('btnText');
    const btnSpinner = document.getElementById('btnSpinner');
    const resultsCard = document.getElementById('resultsCard');

    btn.onclick = async () => {
      let reqUrl = '';
      if (selectedServer === 'voe') {
        const vUrl = document.getElementById('voeUrl').value.trim();
        if (!vUrl) { alert("Please enter a VOE URL."); return; }
        reqUrl = `/voe/extract?url=${encodeURIComponent(vUrl)}`;
      } else if (selectedServer === 'otakuhg') {
        const malId = document.getElementById('malId').value.trim();
        const ep = document.getElementById('epNum').value.trim();
        const incOv = document.getElementById('includeOtakuvid').checked;
        if (!malId || !ep) { alert("Please enter both MAL ID and Episode number."); return; }
        reqUrl = `/otakuhg/${malId}/${ep}?include_otakuvid=${incOv}`;
      } else {
        const malId = document.getElementById('malId').value.trim();
        const ep = document.getElementById('epNum').value.trim();
        if (!malId || !ep) { alert("Please enter both MAL ID and Episode number."); return; }
        reqUrl = `/${selectedServer}/${malId}/${ep}`;
      }

      btnText.style.display = 'none';
      btnSpinner.style.display = 'inline-block';
      btn.disabled = true;

      try {
        const res = await fetch(reqUrl);
        const data = await res.json();

        if (data.status === "error" || data.detail) {
          throw new Error(data.detail || data.message || "Failed to extract streams");
        }

        if (selectedServer === 'voe') {
          document.getElementById('resTitle').textContent = `VOE Extractor Stream`;
          document.getElementById('resSub').textContent = `Input URL: ${data.voeUrl || 'VOE Stream'}`;
        } else {
          const malId = document.getElementById('malId').value.trim();
          const ep = document.getElementById('epNum').value.trim();
          document.getElementById('resTitle').textContent = `MAL ID ${malId} - Episode ${ep}`;
          document.getElementById('resSub').textContent = `Server Engine: ${selectedServer.toUpperCase()}`;
        }

        const streamsList = document.getElementById('streamsList');
        streamsList.innerHTML = '';

        let streams = [];
        if (Array.isArray(data.results)) {
          data.results.forEach(resItem => {
            if (resItem.links) {
              Object.keys(resItem.links).forEach(linkKey => {
                streams.push({ server: `OtakuHG ${linkKey.toUpperCase()} (${resItem.tag || 'Stream'})`, url: resItem.links[linkKey] });
              });
            } else if (resItem.master_url) {
              streams.push({ server: `OtakuHG (${resItem.tag || 'Master'})`, url: resItem.master_url });
            }
            if (resItem.variants) {
              resItem.variants.forEach(v => {
                streams.push({ server: `OtakuHG Track (${v.resolution} @ ${v.bandwidth})`, url: v.url });
              });
            }
          });
        } else if (data.results && data.results.all) {
          Object.keys(data.results.all).forEach(linkKey => {
            streams.push({ server: `OtakuHG ${linkKey.toUpperCase()}`, url: data.results.all[linkKey] });
          });
          if (data.results.variants) {
            data.results.variants.forEach(v => {
              streams.push({ server: `OtakuHG Track (${v.resolution} @ ${v.bandwidth})`, url: v.url });
            });
          }
        } else if (data.results && data.results.stream_url) {
          streams.push({ server: 'Direct HLS', url: data.results.stream_url });
          if (data.results.preview_image) {
            streams.push({ server: 'Preview Image', url: data.results.preview_image });
          }
          if (data.results.streams) streams.push(...data.results.streams);
        } else if (data.results && data.results.streams) {
          streams = data.results.streams;
        } else if (data.streams) {
          streams = data.streams;
        } else if (selectedServer === 'all' && data.results) {
          Object.keys(data.results).forEach(srv => {
            const srvData = data.results[srv];
            if (srvData && srvData.stream_url) {
              streams.push({ server: `${srv.toUpperCase()} HLS`, url: srvData.stream_url });
            }
            if (srvData && srvData.streams) {
              streams.push(...srvData.streams);
            } else if (srvData && srvData.results && srvData.results.streams) {
              streams.push(...srvData.results.streams);
            }
          });
        }

        if (streams.length > 0) {
          streams.forEach((st, idx) => {
            const div = document.createElement('div');
            div.className = 'url-box';
            div.innerHTML = `
              <div>
                <strong style="font-size:0.8rem; color:#fff;">${st.server || st.name || 'Stream Track'} ${st.quality ? '('+st.quality+')' : ''}</strong>
                <div class="url-text" id="streamUrl_${idx}">${st.url}</div>
              </div>
              <button class="btn-copy" onclick="copyText('${st.url}')">Copy</button>
            `;
            streamsList.appendChild(div);
          });
        } else {
          streamsList.innerHTML = '<p style="color:var(--subtext);">No direct stream URLs extracted for this episode.</p>';
        }

        const jsonBox = document.getElementById('jsonBox') || document.getElementById('jsonOutput');
        if (jsonBox) jsonBox.textContent = JSON.stringify(data, null, 2);
        resultsCard.style.display = 'block';
        resultsCard.scrollIntoView({ behavior: 'smooth' });

      } catch (err) {
        alert("Extraction Error: " + err.message);
      } finally {
        btnText.style.display = 'inline';
        btnSpinner.style.display = 'none';
        btn.disabled = false;
      }
    };
  </script>
</body>
</html>"""


@app.get("/voe/extract")
@app.get("/voe/{voe_id}")
@app.get("/voe")
async def extract_voe_stream(voe_id: str = None, url: str = Query(None)):
    """VOE Server stream extractor."""
    target_url = url or voe_id or "https://voe.sx/e/80z1tpfbkgyc"
    target_url = target_url.strip()
    if not target_url.startswith("http"):
        target_url = f"https://voe.sx/e/{target_url}"
    try:
        direct_link = vosesx.get_direct_link_from_voe(target_url)
        preview_image = None
        try:
            preview_image = vosesx.get_preview_image_link_from_voe(target_url)
        except Exception:
            pass

        return {
            "status": "success",
            "server": "VOE",
            "voeUrl": target_url,
            "results": {
                "stream_url": direct_link,
                "preview_image": preview_image,
                "streams": [
                    {
                        "server": "VOE Direct HLS",
                        "url": direct_link,
                        "quality": "Direct M3U8",
                        "type": "hls"
                    }
                ]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anizone/{mal_id}/{ep_num}")
async def get_anizone_streams(mal_id: int, ep_num: int):
    """AniZone Server stream extractor with rotating proxies."""
    try:
        data = process_mal_episode(mal_id, ep_num)
        return {"status": "success", "server": "AniZone", "malId": mal_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/reanime/{mal_id}/{ep_num}")
async def get_reanime_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """ReAnime Server stream extractor with WASM & cryptography decryption + rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await converted_reanime.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "ReAnime", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/2dhive/{mal_id}/{ep_num}")
async def get_2dhive_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """2DHive Server stream extractor with AES-GCM BabaStream resolver & rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await converted2dhive.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "2DHive", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anibd/{mal_id}/{ep_num}")
async def get_anibd_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """AniBD Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await anibd.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AniBD", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anikoto/{mal_id}/{ep_num}")
async def get_anikoto_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """AniKoto Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await anikoto.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AniKoto", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/animenosub/{mal_id}/{ep_num}")
async def get_animenosub_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """AnimeNoSub Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await animenosub.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AnimeNoSub", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anineko/{mal_id}/{ep_num}")
async def get_anineko_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """AniNeko Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await anineko.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AniNeko", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/animeg/{mal_id}/{ep_num}")
async def get_animeg_streams(mal_id: int, ep_num: int, audio: str = Query("all")):
    """AnimeG Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await convertedanimg.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AnimeG", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kichsas/{mal_id}/{ep_num}")
async def get_kichsas_streams(mal_id: int, ep_num: int, audio: str = Query("sub")):
    """Kichsas Anime Server stream extractor with rotating proxies."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await converkichsasanime.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "KichsasAnime", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anidb/{mal_id}/{ep_num}")
async def get_anidb_streams(mal_id: int, ep_num: int, audio: str = Query("both")):
    """AniDB Server stream extractor (Direct connections, no rotating proxies)."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await anidbpy.handle_watch(anilist_id, audio, ep_num)
        return {"status": "success", "server": "AniDB", "malId": mal_id, "anilistId": anilist_id, "episode": ep_num, "results": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/otakuhg/{mal_id}/{ep_num}")
async def get_otakuhg_streams(mal_id: int, ep_num: int, include_otakuvid: bool = Query(False)):
    """OtakuHG / HiAnime Multi-Dataset stream extractor (Optionally includes OtakuVid / EarnVids)."""
    try:
        data = hianime_otakuhg.get_streams_by_mal_id(mal_id, ep_num, include_otakuvid=include_otakuvid)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/playmongo/{mal_id}/{ep_num}")
async def get_playmongo_streams(mal_id: int, ep_num: int):
    """PlayMongo / Doodstream Multi-Dataset stream extractor."""
    try:
        data = hianime_playmongo.get_playmongo_streams_by_mal_id(mal_id, ep_num)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vivibebe/{mal_id}/{ep_num}")
async def get_vivibebe_streams(mal_id: int, ep_num: int):
    """ViviBebe Multi-Dataset stream extractor."""
    try:
        data = vivibebe_site.get_vivibebe_streams_by_mal_id(mal_id, ep_num)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/oktavid/{mal_id}/{ep_num}")
async def get_oktavid_streams(mal_id: int, ep_num: int):
    """OktaVid / OtakuVid Multi-Dataset stream extractor."""
    try:
        data = oktavid.get_oktavid_streams_by_mal_id(mal_id, ep_num)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/flixcloud/{mal_id}/{ep_num}")
async def get_flixcloud_streams(mal_id: int, ep_num: int):
    """FlixCloud / LunarAnime Stream Extractor with rotating proxies fallback."""
    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        data = await asyncio.to_thread(flixcloud.get_streams_by_anilist_id, anilist_id, ep_num, mal_id)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/all/{mal_id}/{ep_num}")
async def get_all_streams(mal_id: int, ep_num: int):
    """Aggregate streams from all servers (AniZone, OtakuHG, PlayMongo, FlixCloud, ReAnime, 2DHive, AniBD, AniKoto, AnimeNoSub, AniNeko, AnimeG, Kichsas, AniDB)."""
    results = {}

    try:
        results["anizone"] = process_mal_episode(mal_id, ep_num)
    except Exception as e:
        results["anizone"] = {"error": str(e)}

    try:
        anilist_id = await mal_to_anilist_id(mal_id)
        results["flixcloud"] = await asyncio.to_thread(flixcloud.get_streams_by_anilist_id, anilist_id, ep_num, mal_id)
    except Exception as e:
        results["flixcloud"] = {"error": str(e)}

    try:
        results["playmongo"] = hianime_playmongo.get_playmongo_streams_by_mal_id(mal_id, ep_num)
    except Exception as e:
        results["playmongo"] = {"error": str(e)}

    try:
        results["vivibebe"] = vivibebe_site.get_vivibebe_streams_by_mal_id(mal_id, ep_num)
    except Exception as e:
        results["vivibebe"] = {"error": str(e)}

    try:
        results["oktavid"] = oktavid.get_oktavid_streams_by_mal_id(mal_id, ep_num)
    except Exception as e:
        results["oktavid"] = {"error": str(e)}

    try:
        results["otakuhg"] = hianime_otakuhg.get_streams_by_mal_id(mal_id, ep_num)
    except Exception as e:
        results["otakuhg"] = {"error": str(e)}

    try:
        anilist_id = await mal_to_anilist_id(mal_id)
    except Exception as e:
        anilist_id = None

    if anilist_id:
        async def safe_fetch(coro):
            try:
                return await coro
            except Exception as e:
                return {"error": str(e)}

        res_reanime, res_2dhive, res_anibd, res_anikoto, res_nosub, res_neko, res_g, res_kich, res_db = await asyncio.gather(
            safe_fetch(converted_reanime.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(converted2dhive.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(anibd.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(anikoto.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(animenosub.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(anineko.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(convertedanimg.handle_watch(anilist_id, "all", ep_num)),
            safe_fetch(converkichsasanime.handle_watch(anilist_id, "sub", ep_num)),
            safe_fetch(anidbpy.handle_watch(anilist_id, "both", ep_num))
        )

        results["reanime"] = res_reanime
        results["2dhive"] = res_2dhive
        results["anibd"] = res_anibd
        results["anikoto"] = res_anikoto
        results["animenosub"] = res_nosub
        results["anineko"] = res_neko
        results["animeg"] = res_g
        results["kichsas"] = res_kich
        results["anidb"] = res_db

    return {"status": "success", "malId": mal_id, "episode": ep_num, "results": results}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
