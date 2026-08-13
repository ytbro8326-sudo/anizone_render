# AniZone Multi-Server Anime Stream Extractor

A high-performance, Render-ready Web Application & REST API to extract direct HLS (`.m3u8`) and MP4 video streams across multiple anime server engines using MAL ID and Episode numbers.

## Features
- **Interactive Modern Web UI**: Instant stream extraction and stream track viewer with copy-to-clipboard functionality.
- **Multi-Server Support**:
  - **AnimeGG** (`animegg.org`): Multi-dataset stream extractor searching across 6 GitHub datasets (`/animegg/{mal_id}/{ep_num}`).
  - **MegaPlay** (`megaplay.buzz`): Direct HLS stream extraction with SUB/DUB quality selection & intro/outro timestamps (`/megaplay/{mal_id}/{ep_num}`).
  - **AniZone**: Direct HLS stream extraction with rotating proxy support.
  - **ViviBebe**: Multi-dataset stream extractor.
  - **OtakuHG / OktaVid / PlayMongo**: HiAnime dataset stream extractors.
  - **FlixCloud / VOE.sx / ReAnime / 2DHive / AniBD / AniKoto / AnimeNoSub / AniNeko / AnimeG / Kichsas / AniDB**.
- **Aggregated Extraction**: Extract streams from all server engines simultaneously using `/all/{mal_id}/{ep_num}`.

## API Endpoints
- `GET /` - Interactive Extractor Web Interface
- `GET /animegg/{mal_id}/{ep_num}` - AnimeGG Extractor
- `GET /megaplay/{mal_id}/{ep_num}` or `/megplay/{mal_id}/{ep_num}` - MegaPlay HLS Extractor
- `GET /anizone/{mal_id}/{ep_num}` - AniZone Extractor
- `GET /all/{mal_id}/{ep_num}` - Aggregate streams from all servers

## Render Deployment
1. Connect this repository to Render.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `python -m uvicorn app:app --host 0.0.0.0 --port $PORT`

