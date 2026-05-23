import requests

url = "https://raw.githubusercontent.com/yiyuqiao2748/iptv-subscription/master/iptv.m3u"
r = requests.get(url, timeout=15)
c = r.text
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Size: {len(c)} bytes")
print(f"EXTINF entries: {c.count('#EXTINF')}")

lines = c.splitlines()
print(f"Total lines: {len(lines)}")
print("First 8 lines:")
for i, l in enumerate(lines[:8]):
    print(f"  [{i}] {l[:100]}")

if not c.startswith("#EXTM3U"):
    print("ERROR: Missing #EXTM3U header!")

print("Last 3 entries:")
print(f"  {lines[-2][:100]}")
print(f"  {lines[-1][:100]}")
print("OK")
