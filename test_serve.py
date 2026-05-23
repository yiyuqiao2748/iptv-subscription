import requests, sys

url = "http://localhost:8899/iptv.m3u"
r = requests.get(url, timeout=5)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', 'not set')}")
print(f"Size: {len(r.text)} bytes")
content = r.text
lines = content.split("\n")
print(f"Lines: {len(lines)}")
print(f"EXTINF count: {content.count('#EXTINF')}")

# Check format
if not content.startswith("#EXTM3U"):
    print("ERROR: Missing #EXTM3U header")
    sys.exit(1)

# Print first 8 lines
for i, line in enumerate(lines[:8]):
    print(f"  [{i}] {line.strip()}")

# Check a complete entry
for i, line in enumerate(lines):
    if line.startswith("#EXTINF") and i+1 < len(lines):
        url_line = lines[i+1].strip()
        if url_line.startswith("http"):
            print(f"\nFirst entry: {line.strip()}")
            print(f"URL: {url_line[:100]}...")
            break

print("\nFormat looks good!")
