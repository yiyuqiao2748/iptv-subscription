"""
IPTV Auto-Subscription Configuration
=====================================
Domestic (China) focused IPTV source aggregation, testing, and M3U generation.
Priority: Hunan channels > CCTV > Satellite TV > Local ground channels
No foreign channels.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ============================================================
# OUTPUT PATHS
# ============================================================
OUTPUT_M3U = os.path.join(OUTPUT_DIR, "iptv.m3u")
OUTPUT_TXT = os.path.join(OUTPUT_DIR, "iptv.txt")
CACHE_SCAN = os.path.join(CACHE_DIR, "last_scan.json")
CACHE_STATS = os.path.join(CACHE_DIR, "stats.json")

# ============================================================
# HTTP SERVER
# ============================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8899
SUBSCRIPTION_ROUTE = "/iptv.m3u"

# ============================================================
# SCHEDULER
# ============================================================
UPDATE_INTERVAL_HOURS = 6
UPDATE_CRON = None  # if set, overrides interval, e.g. "0 */6 * * *"

# ============================================================
# SOURCE SCANNING - Domestic ONLY (verified active repos 2026-05)
# Priority: vbskycn (tested live) > high-volume aggregators > speciality
# ============================================================
KNOWN_SOURCES = [
    # ---- vbskycn IPTV (tested live sources, China-direct) ----
    # This project runs its own verification server. 550+ verified channels.
    # Primary domain (domestic direct):
    "https://live.zbds.top/tv/iptv4.m3u",
    # TXT format with multiple backup URLs:
    "https://live.zbds.top/tv/iptv4.txt",
    # GitHub raw mirror:
    "https://raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.m3u",
    # IPv6 source:
    "https://live.zbds.top/tv/iptv6.m3u",

    # ---- Primary aggregators (verified active) ----
    # YueChan - comprehensive collection
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
    # Kimentanm aptv source
    "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    # suxuang myIPTV - large collection
    "https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv6.m3u",
    # BurningC4 Chinese-IPTV
    "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
    # YanG-1989 Gather
    "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u",
    # iptv-org China subset (large collection)
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",

    # ---- txt format sources ----
    "https://raw.githubusercontent.com/ssili126/tv/main/itvlist.txt",
    "https://raw.githubusercontent.com/joevess/IPTV/main/sources/iptv_sources.m3u",
]

# ============================================================
# FALLBACK URLS - guaranteed stable sources for must-have channels
# These are manually curated known-working URLs.
# ============================================================
FALLBACK_STREAMS = {
    # ---- CCTV 1-17 ----
    "CCTV-1 综合": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV1HD.m3u8",
        "http://39.134.115.163:8080/PLTV/88888910/224/3221225617/index.m3u8",
    ],
    "CCTV-2 财经": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV2HD.m3u8",
    ],
    "CCTV-3 综艺": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV3HD.m3u8",
    ],
    "CCTV-4 中文国际": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV4HD.m3u8",
    ],
    "CCTV-5 体育": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV5HD.m3u8",
    ],
    "CCTV-5+ 体育赛事": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV5PH.m3u8",
    ],
    "CCTV-6 电影": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV6HD.m3u8",
    ],
    "CCTV-7 国防军事": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV7HD.m3u8",
    ],
    "CCTV-8 电视剧": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV8HD.m3u8",
    ],
    "CCTV-9 纪录": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV9HD.m3u8",
    ],
    "CCTV-10 科教": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV10HD.m3u8",
    ],
    "CCTV-11 戏曲": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV11HD.m3u8",
    ],
    "CCTV-12 社会与法": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV12HD.m3u8",
    ],
    "CCTV-13 新闻": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV13HD.m3u8",
    ],
    "CCTV-14 少儿": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV14HD.m3u8",
    ],
    "CCTV-15 音乐": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV15HD.m3u8",
    ],
    "CCTV-16 奥林匹克": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV16HD.m3u8",
        "http://[2409:8087:7000:20:1000::22]:6060/000000001001/3000000001000002/1.m3u8",
    ],
    "CCTV-17 农业农村": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/cctv/hls/CCTV17HD.m3u8",
    ],
    # ---- 湖南卫视 ----
    "湖南卫视": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNWSHD.m3u8",
        "http://ott.mobaibox.com/hls/hunanSTV.m3u8",
    ],
    "湖南卫视 4K超高清": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNWS4K.m3u8",
    ],
    # ---- 湖南经视 ----
    "湖南经视": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNJSTV.m3u8",
    ],
    # ---- 湖南都市 ----
    "湖南都市": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNDSTV.m3u8",
    ],
    # ---- 湖南娱乐 ----
    "湖南娱乐": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNYLTV.m3u8",
    ],
    # ---- 湖南电视剧 ----
    "湖南电视剧": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNTVDSJ.m3u8",
    ],
    # ---- 湖南电影 ----
    "湖南电影": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNMOVIE.m3u8",
    ],
    # ---- 金鹰卡通卫视 ----
    "金鹰卡通卫视": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/JYKT.m3u8",
    ],
    # ---- 金鹰纪实卫视 ----
    "金鹰纪实卫视": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/JYJS.m3u8",
    ],
    # ---- 湖南公共/爱晚 ----
    "爱晚频道": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNGG.m3u8",
    ],
    # ---- 快乐购 ----
    "快乐购": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/KLTG.m3u8",
    ],
    # ---- 湖南国际频道 ----
    "湖南国际频道": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/HNGJ.m3u8",
    ],
    # ---- 茶频道 ----
    "茶频道": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/TEAPD.m3u8",
    ],
    # ---- 快乐垂钓 ----
    "快乐垂钓": [
        "http://[2409:8087:1a01:df::7005]:80/ottrsp.0.bd6bc28a.rrspsw.OTT/hunan/hls/KLCU.m3u8",
    ],
}

# Extra GitHub search queries for Hunan-specific discovery
HUNAN_SEARCH_QUERIES = [
    "湖南 IPTV m3u",
    "hunan tv m3u8",
    "湖南卫视 m3u",
    "湖南经视 iptv",
    "长沙 IPTV m3u",
    "iptv湖南 source",
    "CCTV-16 iptv",
    "CCTV-17 iptv",
    "金鹰卡通 m3u8",
    "快乐垂钓 m3u8",
]

# ============================================================
# TESTING PARAMETERS
# ============================================================
TEST_TIMEOUT = 8            # seconds per stream (increased for bandwidth test)
TEST_CONCURRENT = 50        # max concurrent connections
TEST_RETRY = 1              # retries per stream
TEST_MIN_BITRATE = 100      # kbps minimum (streams slower than this are rejected)

# ============================================================
# FILTER PARAMETERS
# ============================================================
# Channel names that should always be kept (never filtered)
ALWAYS_KEEP_KEYWORDS = [
    "CCTV", "央视",
    "湖南", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳",
    "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西",
    "卫视", "金鹰", "爱晚", "快乐购", "快乐垂钓", "茶频道",
    "CETV", "CGTN",
]

# Channel names to always EXCLUDE (foreign channels, junk, etc.)
EXCLUDE_KEYWORDS = [
    # Foreign countries - case insensitive match
    "USA", "US ", "UK ", "GB ", "France", "French", "Germany", "German",
    "Spain", "Spanish", "Italy", "Italian", "Japan", "Japanese",
    "Korea", "Korean", "India", "Indian", "Russia", "Russian",
    "Brazil", "Canada", "Australia", "Mexico", "Netherlands",
    "Turkey", "Portugal", "Poland", "Sweden", "Switzerland",
    "Thailand", "Vietnam", "Indonesia", "Malaysia", "Philippines",
    # Foreign networks
    "BBC", "CNN", "NBC", "ABC News", "Fox News", "Sky News", "Bloomberg",
    "Al Jazeera", "Euronews", "France 24", "DW ", "RT ", "NHK",
    "ESPN", "NBA TV", "NFL", "MLB", "NHL",
    "HBO", "Netflix", "Disney+", "Paramount", "Hulu",
    "Discovery", "National Geographic", "Nat Geo",
    "MTV", "VH1", "BET", "Comedy Central",
    "Nickelodeon", "Disney Channel", "Disney Junior",
    # Non-Chinese content markers
    "US |", "UK |", "CA |", "AU |", "JP |", "KR |",
    "XXX", "Adult", "18+", "Erotic",
    # These are safe - NOT excluding: 凤凰 (Phoenix - Chinese), 翡翠 (Jade - Chinese), 明珠 (Pearl - Chinese)
]

# ============================================================
# CATEGORY KEYWORDS for group-title assignment
# ============================================================
CATEGORY_KEYWORDS = {
    "📺 央视频道": [
        "CCTV-", "CCTV ", "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5",
        "CCTV6", "CCTV7", "CCTV8", "CCTV9", "CCTV10",
        "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15",
        "CCTV16", "CCTV17",
        "央视", "CGTN", "CETV", "中国教育",
        "CCTV 综合", "CCTV 财经", "CCTV 综艺", "CCTV 中文",
        "CCTV 体育", "CCTV 电影", "CCTV 军事", "CCTV 电视剧",
        "CCTV 纪录", "CCTV 科教", "CCTV 戏曲", "CCTV 社会",
        "CCTV 新闻", "CCTV 少儿", "CCTV 音乐", "CCTV 奥林匹",
        "CCTV 农业",
    ],
    "🏠 湖南频道": [
        # 上星频道
        "湖南卫视", "湖南经视", "金鹰纪实", "金鹰卡通",
        # 地面频道
        "湖南都市", "湖南娱乐",
        "湖南电视剧", "湖南电影",
        "爱晚", "快乐购",
        "超高清", "4K 超高清",
        # 国际频道
        "湖南卫视国际", "湖南国际",
        # 付费频道
        "茶频道", "快乐垂钓",
        # 长沙市台
        "长沙新闻", "长沙政法", "长沙女性", "长沙公共",
        "长沙台", "长沙",
        # 湖南各地市
        "株洲", "湘潭", "衡阳", "邵阳", "岳阳",
        "常德", "张家界", "益阳", "郴州", "永州",
        "怀化", "娄底", "湘西",
        "Hunan", "HNTV", "芒果",
    ],
    "📡 卫视频道": [
        # Only match non-Hunan 卫视 here (Hunan matched above)
        "北京卫视", "上海卫视", "东方卫视", "天津卫视", "重庆卫视",
        "广东卫视", "浙江卫视", "江苏卫视", "四川卫视", "安徽卫视",
        "湖北卫视", "河南卫视", "山东卫视", "福建卫视", "深圳卫视",
        "河北卫视", "山西卫视", "陕西卫视", "吉林卫视", "辽宁卫视",
        "黑龙江卫视", "内蒙古卫视", "云南卫视", "海南卫视",
        "广西卫视", "贵州卫视", "青海卫视", "宁夏卫视", "甘肃卫视",
        "新疆卫视", "西藏卫视", "厦门卫视",
        "凤凰中文", "凤凰资讯", "凤凰香港",
        "翡翠台", "明珠台",
    ],
    "🗺 地方频道": [
        "北京台", "上海台", "天津台", "重庆台",
        "广东台", "浙江台", "江苏台", "四川台", "安徽台", "湖北台",
        "河南台", "山东台", "福建台", "深圳台", "河北台", "山西台",
        "陕西台", "吉林台", "辽宁台", "黑龙江台",
        "内蒙古台", "云南台", "海南台", "广西台", "贵州台",
        "青海台", "宁夏台", "甘肃台", "新疆台", "西藏台",
        "厦门台", "三沙台", "兵团", "延边",
        # City-level TV stations
        "苏州", "杭州", "南京", "成都", "武汉",
        "西安", "广州", "青岛", "大连", "宁波",
    ],
}

# Fallback group for unmatched channels
DEFAULT_GROUP = "📺 其他频道"

# ============================================================
# HUNAN KEYWORDS (for dedup and keep-extra logic)
# ============================================================
HUNAN_KEYWORDS = CATEGORY_KEYWORDS["🏠 湖南频道"]

# Max duplicate streams to keep per Hunan channel (keep spares)
HUNAN_MAX_DUPES = 3
# Max duplicate streams to keep for other channels
OTHER_MAX_DUPES = 1