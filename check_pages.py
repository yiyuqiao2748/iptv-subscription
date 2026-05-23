import requests

urls = [
    "https://yiyuqiao2748.github.io/iptv-subscription/iptv.m3u",
    "https://raw.githubusercontent.com/yiyuqiao2748/iptv-subscription/master/iptv.m3u",
]
for url in urls:
    try:
        r = requests.get(url, timeout=10)
        print(f"URL: {url}")
        print(f"  Status: {r.status_code}")
        print(f"  Content-Type: {r.headers.get('content-type')}")
        print(f"  Size: {len(r.text)} bytes")
        first = r.text.splitlines()[0] if r.text else "EMPTY"
        print(f"  First line: {first[:80]}")
    except Exception as e:
        print(f"URL: {url}")
        print(f"  ERROR: {e}")
    print()
