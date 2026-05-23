import requests, re

urls = [
    ("https://live.zbds.top/tv/iptv4.m3u", "M3U"),
    ("https://live.zbds.top/tv/iptv4.txt", "TXT"),
]
for url, label in urls:
    r = requests.get(url, timeout=15)
    print(f"=== {label} ===")
    print(f"Status: {r.status_code}, Size: {len(r.text)} bytes")
    lines = r.text.splitlines()
    extinf = sum(1 for l in lines if l.startswith("#EXTINF"))
    print(f"Lines: {len(lines)}, EXTINF: {extinf}")
    # Show first lines
    for l in lines[:6]:
        print(f"  {l[:120]}")
    # Show some EXTINF
    print("Sample channels:")
    count = 0
    for l in lines:
        if l.startswith("#EXTINF"):
            print(f"  {l[:120]}")
            count += 1
            if count >= 5:
                break
    # Check groups
    groups = set()
    for l in lines:
        m = re.search(r'group-title="([^"]*)"', l)
        if m:
            groups.add(m.group(1))
    print(f"Groups ({len(groups)}): {sorted(groups)[:15]}...")
    print()
