# 📡 IPTV Auto-Subscription

Automated IPTV live-stream aggregation pipeline with web dashboard. Scans public M3U sources, tests stream connectivity, filters dead/foreign channels, and serves a clean M3U playlist for APTV / VLC / any IPTV player.

**Domestic China focus** — CCTV 1-17 · Hunan full coverage · 31 provincial SAT · local ground channels.

## Features

- **Multi-source scanning** — 22 verified M3U sources + GitHub Hunan search
- **Smart dedup** — URL dedup + fuzzy name grouping, keeps multiple sources for priority channels
- **Async connectivity testing** — 50 concurrent stream tests with bandwidth measurement
- **Auto-categorization** — 湖南 / 央视 / 卫视 / 地方 / 其他 groups
- **Fallback injection** — Curated stable URLs for 30+ must-have channels
- **Web dashboard** — Search, filter by category, copy URLs, manual trigger
- **Auto-update** — Configurable interval (default 6h) with APScheduler
- **Docker support** — Dockerfile + docker-compose.yml included

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run (scan + server + scheduler)
python main.py

# Open dashboard
http://localhost:8899
```

## Usage

```bash
python main.py                    # Full: server + scheduler
python main.py --scan-only        # One-time scan, then exit
python main.py --port 9999        # Custom port
python main.py --interval 2       # Update every 2 hours
python main.py --no-scheduler     # Server only, no auto-update
```

## Subscription

Add to APTV or any IPTV player:

```
http://<your-ip>:8899/iptv.m3u
```

Also available as plain text: `http://<your-ip>:8899/iptv.txt`

## Docker

```bash
docker compose up -d
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /iptv.m3u` | M3U playlist |
| `GET /iptv.txt` | Plain text playlist |
| `GET /api/stats` | Pipeline stats JSON |
| `GET /api/channels` | Channel list with search/filter/pagination |
| `POST /trigger` | Manual pipeline trigger |
| `GET /health` | Health check |

## Project Structure

```
iptv-subscription/
├── main.py           # Entry point + pipeline orchestration
├── scanner.py        # M3U/TXT source fetcher + parser
├── dedup.py          # URL dedup + fuzzy name grouping
├── tester.py         # Async connectivity tester (aiohttp)
├── filter.py         # Dead/foreign filter + category assignment
├── generator.py      # M3U + TXT file generator
├── server.py         # Flask + waitress web server + dashboard
├── scheduler.py      # APScheduler periodic updates
├── config.py         # All configuration
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Categories

- 🏠 Hunan (卫视/经视/都市/各地市)
- 📺 CCTV (CCTV-1 ~ CCTV-17 + CGTN)
- 📡 Satellite (31 provincial 卫视)
- 🗺 Local (city ground channels)
- 📺 Others

## License

MIT
