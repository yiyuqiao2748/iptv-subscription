============================================================
  📡 IPTV Auto-Subscription Pipeline
  项目介绍 & 使用说明
  更新日期: 2026-05-14
============================================================

一、项目简介
-----------
IPTV 自动订阅管道，扫描公开 M3U 源 → 去重 → 分类 → 生成
干净整洁的国内频道播放列表。专为 APTV 等 IPTV 播放器设计。

频道覆盖:
  - CCTV-1 ~ CCTV-17 全覆盖
  - 湖南频道深度覆盖 (卫视/经视/都市/各地市)
  - 全国 31 省卫视频道
  - 地方地面频道
  - 自动过滤失效源和海外频道

二、订阅链接 (公网可用)
-----------------------
GitHub Pages (推荐):
  https://yiyuqiao2748.github.io/iptv-subscription/iptv.m3u

Raw 直链:
  https://raw.githubusercontent.com/yiyuqiao2748/iptv-subscription/master/iptv.m3u

TXT 纯文本:
  https://yiyuqiao2748.github.io/iptv-subscription/iptv.txt

三、GitHub 仓库
--------------
  https://github.com/yiyuqiao2748/iptv-subscription

四、自动更新机制
---------------
GitHub Actions 每 6 小时自动执行:
  1. 扫描 22 个公开 IPTV 源 + GitHub 搜索湖南源
  2. URL 去重 + 频道名称模糊分组去重
  3. 过滤海外频道、失效源
  4. 自动分类: 湖南 > 央视 > 卫视 > 地方 > 其他
  5. 注入 30+ 必须频道的备用稳定源
  6. 生成 M3U + TXT → 自动部署到 GitHub Pages

手动触发: 仓库页面 → Actions → IPTV Auto Update → Run workflow

五、本地运行
-----------
环境要求: Python 3.11+, pip

安装:
  pip install -r requirements.txt

启动:
  python main.py                         # 完整服务 (服务器 + 每6小时更新)
  python main.py --scan-only             # 只运行一次管道
  python main.py --scan-only --skip-test # 跳过测速 (海外环境用)
  python main.py --port 9999             # 自定义端口
  python main.py --interval 2            # 自定义更新间隔(小时)
  python main.py --no-scheduler          # 服务器模式，不自动更新
  python main.py --debug                 # 调试模式

本地访问:
  Dashboard: http://localhost:8899
  M3U:       http://localhost:8899/iptv.m3u
  TXT:       http://localhost:8899/iptv.txt
  API:       http://localhost:8899/api/stats
              http://localhost:8899/api/channels?q=CCTV&group=📺 央视频道

六、Docker 部署
--------------
  docker compose up -d

七、文件结构
-----------
iptv-subscription/
├── main.py              # 入口 & 管道编排
├── scanner.py           # M3U/TXT 源抓取解析
├── dedup.py             # URL去重 + 模糊名称分组
├── tester.py            # 异步连通性测速 (aiohttp)
├── filter.py            # 失效/海外过滤 + 分类
├── generator.py         # M3U + TXT 生成
├── server.py            # Flask + waitress 服务器
├── scheduler.py         # 定时调度 (APScheduler)
├── config.py            # 所有配置项
├── .github/workflows/   # GitHub Actions 自动更新
├── Dockerfile / docker-compose.yml
└── requirements.txt

八、API 接口
-----------
GET  /iptv.m3u        → M3U 播放列表
GET  /iptv.txt        → TXT 纯文本列表
GET  /api/stats       → 管道统计数据 JSON
GET  /api/channels    → 频道列表 (支持 ?q=&group=&page=&per_page=)
POST /trigger         → 手动触发管道更新
GET  /health          → 健康检查

九、配置说明 (config.py)
-----------------------
KNOWN_SOURCES       → 22 个公开 IPTV 源 URL
FALLBACK_STREAMS    → 30+ 必须频道的备用稳定源
ALWAYS_KEEP_KEYWORDS → 强制保留的关键词
EXCLUDE_KEYWORDS    → 强制排除的关键词 (海外频道)
CATEGORY_KEYWORDS   → 分类关键词规则
TEST_TIMEOUT        → 单流测速超时 (8秒)
TEST_CONCURRENT     → 并发测速数 (50)
HUNAN_MAX_DUPES     → 湖南频道保留备源数 (3)
OTHER_MAX_DUPES     → 其他频道保留备源数 (1)

十、当前状态
-----------
频道总数: 355
分类: 湖南频道 / 央视频道 / 卫视频道 / 地方频道 / 其他频道
更新方式: GitHub Actions 每6小时自动
托管平台: GitHub Pages (免费)
