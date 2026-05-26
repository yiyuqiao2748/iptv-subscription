"""
IPTV Auto-Subscription Configuration
=====================================
Domestic (China) focused IPTV source aggregation, testing, and M3U generation.
Priority: Hunan channels > CCTV > Satellite TV > Local ground channels
No foreign channels.
"""

import os
import sys

# PyInstaller 打包后，__file__ 指向临时解压目录
# 可写目录应为 exe 所在目录
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ============================================================
# BRAND
# ============================================================
BRAND_NAME = "小柚TV"
BRAND_VERSION = "1.0.0"

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
    # === PRIMARY: vbskycn IPTV — 550+ verified China-direct channels ===
    # Self-hosted verification server, domestic direct access, EPG + logos
    "https://live.zbds.top/tv/iptv4.m3u",

    # === SUPPLEMENTARY: curated Chinese aggregators (via jsDelivr CDN) ===
    # YueChan — comprehensive, good Chinese naming
    "https://cdn.jsdelivr.net/gh/YueChan/Live@main/IPTV.m3u",
    # Kimentanm — APTV compatible source
    "https://cdn.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u",
    # BurningC4 — IPv4 focused, clean names
    "https://cdn.jsdelivr.net/gh/BurningC4/Chinese-IPTV@master/TV-IPV4.m3u",
    # YanG-1989 — well-maintained Chinese playlist
    "https://cdn.jsdelivr.net/gh/YanG-1989/m3u@main/Gather.m3u",
    # iptv-org China subset
    "https://cdn.jsdelivr.net/gh/iptv-org/iptv@master/streams/cn.m3u",
    # tianunusual — Hunan-focused, 165+ channels via IPv6
    "https://cdn.jsdelivr.net/gh/tianunusual/IPTV@main/IPTv.m3u",

    # === MASSIVE AGGREGATOR: xisohi/CHINA-IPTV — 1300+ channels ===
    # TV/live.txt — 汇总各省直播源，按频道名+分类组织
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/TV/live.txt",
    # TV/sources.txt — 汇总源地址列表
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/TV/sources.txt",

    # === PROVINCE MULTICAST: xisohi — 按省份运营商分类 ===
    # 湖南电信 (Hunan Telecom)
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/Multicast/hunan/telecom.txt",
    # 广东电信 (Guangdong Telecom)
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/Multicast/guangdong/telecom.txt",
    # 上海电信 (Shanghai Telecom)
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/Multicast/shanghai/telecom.txt",
    # 浙江电信 (Zhejiang Telecom)
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/Multicast/zhejiang/telecom.txt",
    # 四川移动 (Sichuan Mobile)
    "https://cdn.jsdelivr.net/gh/xisohi/CHINA-IPTV@main/Multicast/sichuan/mobile.txt",

    # === MAOWEI: spider-iptv — 酒店源 + 组播源 ===
    # 湖南电信组播
    "https://cdn.jsdelivr.net/gh/maowei1125/spider-iptv@main/source/multicast/%E6%B9%96%E5%8D%97-%E7%94%B5%E4%BF%A1-239.1.0.m3u",
    # 广东电信组播
    "https://cdn.jsdelivr.net/gh/maowei1125/spider-iptv@main/source/multicast/%E5%B9%BF%E4%B8%9C-%E7%94%B5%E4%BF%A1-239.77.0.m3u",
    # 江苏电信组播
    "https://cdn.jsdelivr.net/gh/maowei1125/spider-iptv@main/source/multicast/%E6%B1%9F%E8%8B%8F-%E7%94%B5%E4%BF%A1-239.49.8.m3u",
    # 浙江电信组播
    "https://cdn.jsdelivr.net/gh/maowei1125/spider-iptv@main/source/multicast/%E6%B5%99%E6%B1%9F-%E7%94%B5%E4%BF%A1-233.50.200.m3u",
    # 上海酒店源
    "https://cdn.jsdelivr.net/gh/maowei1125/spider-iptv@main/source/hotels/%E4%B8%8A%E6%B5%B7%E5%B8%82.m3u",
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
MAX_SEGMENT_DURATION = 6    # max HLS segment duration in seconds (higher = more latency)

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
# Chinese / Pinyin / English / EPG name patterns
# Checked in order: CCTV > Hunan > Kids > Sports > Satellite > Local > Other
# ============================================================
CATEGORY_KEYWORDS = {
    "📺 央视频道": [
        # CCTV numbered (all naming variants)
        "CCTV-", "CCTV ", "CCTV1", "CCTV2", "CCTV3", "CCTV4", "CCTV5",
        "CCTV6", "CCTV7", "CCTV8", "CCTV9", "CCTV10",
        "CCTV11", "CCTV12", "CCTV13", "CCTV14", "CCTV15",
        "CCTV16", "CCTV17",
        "CCTV 综合", "CCTV 财经", "CCTV 综艺", "CCTV 中文",
        "CCTV 体育", "CCTV 电影", "CCTV 军事", "CCTV 电视剧",
        "CCTV 纪录", "CCTV 科教", "CCTV 戏曲", "CCTV 社会",
        "CCTV 新闻", "CCTV 少儿", "CCTV 音乐", "CCTV 奥林匹",
        "CCTV 农业", "CCTV 国防",
        # Chinese
        "央视", "中央", "央视频道", "中国教育",
        # EPG variants
        "CGTN", "CETV", "CETV-", "CCTV4K",
        # Full Chinese names
        "综合频道", "财经频道", "综艺频道", "中文国际",
        "体育频道", "电影频道", "国防军事", "电视剧频道",
        "纪录频道", "科教频道", "戏曲频道", "社会与法",
        "新闻频道", "少儿频道", "音乐频道", "奥林匹克",
        "农业农村",
    ],
    "🏠 湖南频道": [
        # 上星 (Chinese)
        "湖南卫视", "湖南经视", "金鹰纪实", "金鹰卡通",
        # 地面 (Chinese)
        "湖南都市", "湖南娱乐", "湖南电视剧", "湖南电影",
        "爱晚", "快乐购", "茶频道", "快乐垂钓",
        "湖南卫视国际", "湖南国际",
        # 长沙
        "长沙新闻", "长沙政法", "长沙女性", "长沙公共",
        "长沙台", "长沙", "长沙经贸", "长沙地铁",
        # 湖南各地市
        "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德",
        "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西",
        # Pinyin / English
        "Hunan", "HNTV", "芒果", "HNWS", "HNJS", "HNDS",
        "HNYL", "HNGG", "HNGJ", "JYKT", "JYJS", "KLQD", "KLCU",
        "TeaPD", "TEA",
    ],
    "👶 少儿卡通": [
        # Chinese
        "少儿", "卡通", "动漫", "儿童", "亲子",
        # Pinyin / English
        "Kids", "Toon", "Cartoon", "Baby", "Child",
        # Specific channels
        "CCTV-14", "CCTV14",
        "金鹰卡通", "卡酷", "炫动", "优漫",
        "CN卡通", "CN ",
    ],
    "⚽ 体育频道": [
        # Chinese
        "体育", "运动", "足球", "篮球", "高尔夫", "赛车", "搏击",
        "电竞", "游戏",
        # Pinyin / English
        "Sport", "NBA", "ESPN", "F1", "Golf", "Tennis", "Fight",
        "Game", "Gaming",
        # Specific
        "CCTV-5", "CCTV5", "CCTV-16", "CCTV16",
        "北京体育", "上海体育", "广东体育",
        "风云足球", "高尔夫网球",
    ],
    "📡 卫视频道": [
        # ---- Chinese province 卫视 (non-Hunan, Hunan matched above) ----
        "北京卫视", "上海卫视", "东方卫视", "天津卫视", "重庆卫视",
        "广东卫视", "浙江卫视", "江苏卫视", "四川卫视", "安徽卫视",
        "湖北卫视", "河南卫视", "山东卫视", "福建卫视", "深圳卫视",
        "河北卫视", "山西卫视", "陕西卫视", "吉林卫视", "辽宁卫视",
        "黑龙江卫视", "内蒙古卫视", "云南卫视", "海南卫视",
        "广西卫视", "贵州卫视", "青海卫视", "宁夏卫视", "甘肃卫视",
        "新疆卫视", "西藏卫视", "厦门卫视", "三沙卫视", "兵团卫视",
        "延边卫视", "东南卫视", "江西卫视", "旅游卫视",
        # ---- Pinyin / English province satellite ----
        "BJTV", "SHTV", "Tianjin", "Chongqing",
        "Guangdong", "Zhejiang", "Jiangsu", "Sichuan", "Anhui",
        "Hubei", "Henan", "Shandong", "Fujian", "Shenzhen",
        "Hebei", "Shanxi", "Shaanxi", "Jilin", "Liaoning",
        "Heilongjiang", "InnerMongolia", "Yunnan", "Hainan",
        "Guangxi", "Guizhou", "Qinghai", "Ningxia", "Gansu",
        "Xinjiang", "Tibet", "Xizang", "Xiamen", "Jiangxi",
        # Pinyin patterns
        "Weishi", "SAT TV", "Satellite",
        # ---- Hong Kong / Macau / Taiwan ----
        "凤凰中文", "凤凰资讯", "凤凰香港", "凤凰卫视",
        "翡翠台", "明珠台", "TVB", "ATV",
        "澳门", "台湾", "中视", "华视", "民视", "台视",
        "Phoenix", "Jade", "Pearl",
    ],
    "🗺 地方频道": [
        # ---- Province ground channels (Chinese) ----
        "北京台", "上海台", "天津台", "重庆台",
        "广东台", "浙江台", "江苏台", "四川台", "安徽台", "湖北台",
        "河南台", "山东台", "福建台", "深圳台", "河北台", "山西台",
        "陕西台", "吉林台", "辽宁台", "黑龙江台",
        "内蒙古台", "云南台", "海南台", "广西台", "贵州台",
        "青海台", "宁夏台", "甘肃台", "新疆台", "西藏台",
        "厦门台", "三沙台", "兵团", "延边", "江西台",
        # ---- Province name + channel type ----
        "北京频道", "上海频道", "天津频道",
        # ---- City names (Chinese) ----
        "苏州", "杭州", "南京", "成都", "武汉", "西安",
        "广州", "青岛", "大连", "宁波", "郑州",
        "济南", "沈阳", "哈尔滨", "昆明", "贵阳", "兰州",
        "西宁", "银川", "南宁", "太原", "拉萨",
        # ---- Pinyin city/region ----
        "Beijing ", "Shanghai ", "Tianjin ",
        "Guangzhou", "Shenzhen", "Suzhou", "Hangzhou",
        "Nanjing", "Chengdu", "Wuhan", "Xi'an",
        "Qingdao", "Dalian", "Ningbo", "Zhengzhou",
        "Jinan", "Shenyang", "Harbin", "Kunming",
        # ---- Public / News / Life / etc. ----
        "都市频道", "公共频道", "生活频道",
        "经济频道", "法制", "科教", "文旅",
        "交通", "移动", "地铁",
    ],
    "📰 新闻资讯": [
        # Chinese
        "新闻", "资讯", "时事", "时政", "法治在线",
        "新闻综合", "新闻频道", "综合新闻",
        # English / Pinyin
        "News", "Press",
        # Specific
        "中国蓝新闻", "第一现场",
    ],
    "🎬 影视剧场": [
        # Chinese - movies
        "电影", "影院", "影迷", "影视",
        "CHC", "chc",
        "动作电影", "动作影院", "家庭影院", "影视频道",
        "星空电影", "光影", "星影",
        # Chinese - drama
        "剧场", "剧集", "电视剧",
        "热播", "古装", "武侠", "军旅",
        # English
        "Movie", "Cinema", "Film", "Drama", "Theater",
        "AMC",
    ],
    "🎵 音乐娱乐": [
        # Chinese
        "音乐", "娱乐", "综艺", "相声", "小品",
        "KTV", "ktv", "MV", "MV音乐",
        # English
        "Music", "Entertainment", "Variety",
        # Specific
        "AMC音乐", "音乐现场", "音乐欣赏",
    ],
    "🎮 游戏电竞": [
        # Platforms
        "B站", "斗鱼", "虎牙", "抖音", "快手",
        # Chinese
        "游戏", "电竞", "直播",
        # English
        "Gaming", "Esport", "Game",
        # Specific games
        "王者荣耀", "英雄联盟", "绝地求生", "DOTA", "FIFA",
        "CS ", "CS2", "穿越火线", "和平精英", "我的世界",
        "原神", "梦幻西游", "永劫无间", "第五人格",
        "街霸", "跑跑卡丁车", "使命召唤", "QQ飞车",
        "无畏契约", "火影忍者", "云顶之弈",
    ],
    "🛒 购物频道": [
        # Chinese
        "购物", "优选", "商城", "居家购物",
        "星空购物", "家有购物",
        # English
        "Shop", "Shopping", "QVC",
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