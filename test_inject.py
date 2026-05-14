import sys
sys.path.insert(0, '.')
from main import inject_fallback_streams
from scanner import StreamEntry

# Mock ALIVE entries (what comes out of filter)
mock = [
    StreamEntry('CCTV-1', 'http://fake/cctv1', 'test', {}),
    StreamEntry('CCTV-10 (576i)', 'http://fake/cctv10', 'test', {}),
    StreamEntry('CCTV-13 (1080p)', 'http://fake/cctv13', 'test', {}),
    StreamEntry('湖南卫视', 'http://fake/hnws', 'test', {}),
    StreamEntry('湖南国际', 'http://fake/hngj', 'test', {}),
    StreamEntry('长沙新闻 [Geo-blocked]', 'http://fake/csxw', 'test', {}),
    StreamEntry('长沙政法 [Geo-blocked]', 'http://fake/cszf', 'test', {}),
    StreamEntry('长沙经贸 [Geo-blocked]', 'http://fake/csjm', 'test', {}),
    StreamEntry('长沙女性 [Geo-blocked]', 'http://fake/csnx', 'test', {}),
    StreamEntry('长沙地铁移动 [Geo-blocked]', 'http://fake/csdt', 'test', {}),
]

# New behavior: returns ONLY fallback entries
fallback = inject_fallback_streams(mock)
names = [e.name for e in fallback]
print(f'Injected {len(names)} fallback streams:')
for n in sorted(names):
    print(f'  ✓ {n}')

print('\n--- Verify: these should NOT be injected (already exist) ---')
should_not_be = ['CCTV-1', 'CCTV-10', 'CCTV-13', '湖南卫视', '湖南国际']
for check in should_not_be:
    if check in names:
        print(f'  ❌ ERROR: {check} was injected but should NOT be')
    else:
        print(f'  ✓ {check} correctly NOT injected')

print('\n--- Verify: these SHOULD be injected (not in mock) ---')
should_be = ['湖南经视', '湖南都市', '湖南娱乐', '湖南电视剧', '湖南电影',
             '金鹰卡通卫视', '金鹰纪实卫视', '爱晚频道', '快乐购', '茶频道', '快乐垂钓']
for check in should_be:
    found = any(check in n for n in names)
    if found:
        print(f'  ✓ {check} injected')
    else:
        print(f'  ❌ MISSING: {check}')