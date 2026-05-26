"""
Source Scanner
===============
Pulls M3U/TXT playlists from known public IPTV repositories.
Also searches GitHub for Hunan-specific sources.
"""

import re
import json
import logging
import hashlib
from urllib.parse import urlparse

import requests
from config import KNOWN_SOURCES, HUNAN_SEARCH_QUERIES, CACHE_SCAN

logger = logging.getLogger("scanner")

# Regex to extract EXTINF lines: #EXTINF:-1 ... ,ChannelName
RE_EXTINF = re.compile(r'^#EXTINF:\s*-?\d+[^,]*,(.+)$', re.IGNORECASE)
# Regex to extract URLs (http/https/rtmp/rtsp etc.)
RE_URL = re.compile(r'(https?|rtmp|rtsp|mms|rtp|udp)://\S+', re.IGNORECASE)

# Headers to mimic a browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# Sources whose streams are pre-verified (domestic server tested)
TRUSTED_SOURCE_DOMAINS = {"zbds.top", "vbskycn"}

class StreamEntry:
    """Represents a single stream entry with metadata."""

    __slots__ = ("name", "url", "source", "attrs", "trusted")

    def __init__(self, name, url, source, attrs=None, trusted=False):
        self.name = name.strip()
        self.url = url.strip()
        self.source = source
        self.attrs = attrs or {}
        self.trusted = trusted

    def url_hash(self):
        return hashlib.md5(self.url.encode()).hexdigest()

    def __repr__(self):
        return f"StreamEntry({self.name!r}, {self.url[:60]}...)"


def parse_m3u_content(text: str, source_label: str, trusted: bool = False) -> list:
    """
    Parse raw M3U content and return a list of StreamEntry objects.
    Handles both standard M3U and simple TXT (one URL per line).
    """
    entries = []
    lines = text.splitlines()
    current_name = None
    current_attrs = {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue

        # EXTINF line
        extinf_match = RE_EXTINF.match(line)
        if extinf_match:
            current_name = extinf_match.group(1).strip()
            current_attrs = {}
            # Parse optional attributes (group-title, tvg-name, tvg-logo, etc.)
            raw = extinf_match.group(0)
            attr_parts = raw.split(" ", 1)
            for part in attr_parts:
                if "=" in part:
                    kv = part.split("=", 1)
                    current_attrs[kv[0]] = kv[1].strip('"')
            continue

        # URL line
        if RE_URL.match(line):
            url = line.strip()
            name = current_name or extract_name_from_url(url)
            entries.append(StreamEntry(name=name, url=url, source=source_label, attrs=current_attrs, trusted=trusted))
            current_name = None
            current_attrs = {}
            continue

        # Some formats use tvg-name= in EXTINF
        if "tvg-name=" in line.lower():
            tvg_match = re.search(r'tvg-name="([^"]*)"', line, re.IGNORECASE)
            if tvg_match:
                current_name = tvg_match.group(1).strip()

    # If no EXTINF lines at all, treat every line with a URL as a raw entry
    if not entries:
        for line in lines:
            line = line.strip()
            if RE_URL.match(line):
                name = extract_name_from_url(line)
                entries.append(StreamEntry(name=name, url=line, source=source_label, trusted=trusted))

    return entries


def parse_txt_content(text: str, source_label: str, trusted: bool = False) -> list:
    """Parse simple TXT format: one URL per line, or 'name,url' per line."""
    entries = []
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line and RE_URL.search(line):
            parts = line.split(",", 1)
            name = parts[0].strip()
            url = parts[1].strip()
            if RE_URL.match(url):
                entries.append(StreamEntry(name=name, url=url, source=source_label, trusted=trusted))
        elif RE_URL.match(line):
            name = extract_name_from_url(line)
            entries.append(StreamEntry(name=name, url=line, source=source_label, trusted=trusted))
    return entries


def extract_name_from_url(url: str) -> str:
    """Guess a channel name from the URL path."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        parts = path.split("/")
        last = parts[-1]
        # Remove file extension
        name = re.sub(r'\.\w+$', '', last)
        name = name.replace("_", " ").replace("-", " ")
        return name
    return "Unknown"


def fetch_source(url: str, timeout: int = 15) -> list:
    """
    Fetch and parse a single source URL.
    Returns list of StreamEntry objects (empty if failed).
    """
    try:
        logger.debug(f"Fetching source: {url}")
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text

        # Detect format
        is_m3u = "#EXTM3U" in text[:100] or "#EXTINF" in text[:200]
        source_label = url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1] if "/" in url else url

        # Mark trusted sources (pre-verified by their own servers)
        trusted = any(d in url for d in TRUSTED_SOURCE_DOMAINS)

        if is_m3u:
            entries = parse_m3u_content(text, source_label, trusted)
        else:
            entries = parse_txt_content(text, source_label, trusted)

        logger.info(f"  [{source_label}] -> {len(entries)} streams")
        return entries

    except requests.RequestException as e:
        logger.warning(f"  [!] Failed to fetch {url}: {e}")
        return []
    except Exception as e:
        logger.error(f"  [!!] Error parsing {url}: {e}")
        return []


def _get_repo_m3u_files(repo_full_name: str, default_branch: str) -> list:
    """
    Use GitHub Trees API to find actual M3U/TXT files in a repo.
    Returns list of raw GitHub URLs for files that exist.
    """
    urls = []
    try:
        tree_url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{default_branch}?recursive=1"
        headers = HEADERS.copy()
        headers["Accept"] = "application/vnd.github+json"
        resp = requests.get(tree_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return urls
        tree = resp.json().get("tree", [])
        for item in tree:
            if item["type"] != "blob":
                continue
            path = item["path"]
            if path.lower().endswith((".m3u", ".m3u8", ".txt")):
                # Only include files that look like IPTV playlists
                if any(kw in path.lower() for kw in ["iptv", "tv", "live", "m3u", "channel", "hunan", "cctv", "china"]):
                    raw_url = f"https://cdn.jsdelivr.net/gh/{repo_full_name}@{default_branch}/{path}"
                    urls.append(raw_url)
    except Exception as e:
        logger.debug(f"  Trees API error for {repo_full_name}: {e}")
    return urls


def search_github_hunan() -> list:
    """
    Use GitHub's REST API to search for repos containing Hunan IPTV sources.
    Uses Trees API to find actual files (no blind guessing).
    """
    discovered_urls = []
    headers = HEADERS.copy()
    headers["Accept"] = "application/vnd.github+json"
    seen_repos = set()

    for query in HUNAN_SEARCH_QUERIES:
        try:
            api_url = f"https://api.github.com/search/repositories?q={query}&sort=updated&per_page=5"
            resp = requests.get(api_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.debug(f"  GitHub search '{query}' returned {resp.status_code}")
                continue
            data = resp.json()
            found = 0
            for repo in data.get("items", []):
                repo_full_name = repo["full_name"]
                if repo_full_name in seen_repos:
                    continue
                seen_repos.add(repo_full_name)
                default_branch = repo.get("default_branch", "main")
                file_urls = _get_repo_m3u_files(repo_full_name, default_branch)
                for u in file_urls:
                    if u not in discovered_urls:
                        discovered_urls.append(u)
                        found += 1
            logger.info(f"  GitHub search '{query}' -> {found} files found ({len(discovered_urls)} total)")
        except Exception as e:
            logger.debug(f"  GitHub search error for '{query}': {e}")

    return discovered_urls


def scan_all_sources() -> list:
    """
    Scan all known sources + GitHub-discovered Hunan sources.
    Returns a deduplicated list of StreamEntry objects.
    """
    logger.info("=" * 60)
    logger.info("STEP 1: SCANNING IPTV SOURCES")
    logger.info("=" * 60)

    all_entries: list[StreamEntry] = []
    seen_urls = set()

    # 1. Known sources
    logger.info(f"Scanning {len(KNOWN_SOURCES)} known sources...")
    for url in KNOWN_SOURCES:
        entries = fetch_source(url)
        for entry in entries:
            url_key = entry.url_hash()
            if url_key not in seen_urls:
                seen_urls.add(url_key)
                all_entries.append(entry)

    # 2. Hunan-specific GitHub search
    logger.info("Searching GitHub for Hunan-specific sources...")
    hunan_urls = search_github_hunan()
    logger.info(f"  Found {len(hunan_urls)} additional Hunan source URLs")

    for url in hunan_urls:
        entries = fetch_source(url)
        for entry in entries:
            url_key = entry.url_hash()
            if url_key not in seen_urls:
                seen_urls.add(url_key)
                all_entries.append(entry)

    # 3. Save cache
    cache_data = {
        "count": len(all_entries),
        "urls": [e.url for e in all_entries],
        "names": [e.name for e in all_entries],
        "sources": [e.source for e in all_entries],
    }
    try:
        with open(CACHE_SCAN, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"Could not save scan cache: {e}")

    logger.info(f"Total raw streams collected: {len(all_entries)}")
    return all_entries