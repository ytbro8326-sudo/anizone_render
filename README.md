# AniZone Render Stream Extractor

A lightweight, Render-ready Web App & API to extract direct HLS stream URLs and dual-audio tracks from AniZone.to using MAL ID and Episode numbers.

## Features
- Interactive Glassmorphism Web UI
- Direct HLS Stream extraction (`master.m3u8`, quality playlists, English Dub / Sub audio tracks)
- REST API endpoint: `/anizone/{mal_id}/{ep_num}`

## Render Deployment
1. Connect this repo to Render.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `python -m uvicorn app:app --host 0.0.0.0 --port $PORT`
