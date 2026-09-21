"""频道名归一化：把上游五花八门的写法收敛成可比较的 key。

上游同一个频道常见写法：`湖南卫视` / `湖南卫视HD` / `湖南卫视 (1080p)` / `湖南卫视【高清】`。
归一化后都应收敛到同一个 key，才能把它们的线路合并成多线路。

反过来，收敛过头会把两个台并成一个：`CCTV-5` 和 `CCTV-5+`（赛事版）只差一个加号，
旧实现把加号当分隔符删掉，于是 5+ 的线路挂到了 CCTV-5体育 名下，
电视上点「CCTV-5体育」可能播出来的是另一套节目，所以加号现在折成 `plus` 保留。
"""

from __future__ import annotations

import re
import unicodedata

# 括号内容整体丢弃。每种括号自己配对自己，不能写成「任一开括号 … 任一闭括号」：
# 旧写法的开括号集漏了 `{`，于是 `湖南卫视{SD}` 归一化成 `湖南卫视sd`，
# 跟 `湖南卫视` 撞不到一起；跨类型配对（`[高清)`) 也会把两条无关的字黏掉。
_PAREN_RE = re.compile(
    r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]|\{[^{}]*\}"
)
# 只保留汉字、字母、数字
_NON_WORD_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
# 「＋」是频道名的一部分，不是分隔符：CCTV-5+（赛事版）和 CCTV-5 是两个台。
# NFKC 已把全角＋折成半角，这里统一换成可读的稳定 token，免得被 _NON_WORD_RE 吃掉。
_PLUS_RE = re.compile(r"\+")
# 清晰度/制式后缀，从尾部反复剥离
_QUALITY_SUFFIX_RE = re.compile(
    r"(?:超高清|标清|高清|准高清|蓝光|完整版|纯净版|伴音|试验|备用)+$"
    r"|(?:1080p|1080i|720p|480p|360p|576p|2k|4k|8k|fhd|hd|sd|uhd|avs5|50fps|60fps|25fps|50帧|60帧)+$"
)
# 名称里出现的清晰度词（非尾部），如「CCTV1高清综合」
_QUALITY_INLINE_RE = re.compile(r"(?:超高清|标清|高清|准高清|蓝光|1080p|720p|480p|360p|4k|8k)", re.I)


def normalize(name: str) -> str:
    """把频道名收敛成比较用的 key。

    >>> normalize("湖南卫视 (1080p)")
    '湖南卫视'
    >>> normalize("CCTV-1 高清")
    'cctv1'
    >>> normalize("湖南卫视【高清】")
    '湖南卫视'

    括号要自己配对自己 —— 旧写法漏了 `{`，这条就会漏匹配：

    >>> normalize("湖南卫视{SD}") == normalize("湖南卫视")
    True
    >>> normalize("湖南卫视[超清]") == normalize("湖南卫视")
    True

    「＋」是另一个台，不是清晰度尾巴，必须和裸数字区分开：

    >>> normalize("CCTV-5+")
    'cctv5plus'
    >>> normalize("CCTV5＋ 高清") == normalize("CCTV-5+")
    True
    >>> normalize("CCTV-5+") == normalize("CCTV-5")
    False
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).strip().lower()
    s = _PLUS_RE.sub("plus", s)
    s = _PAREN_RE.sub("", s)
    s = _NON_WORD_RE.sub("", s)

    # 尾部清晰度词可能叠加（如「高清超清」），循环剥到不动为止
    while True:
        stripped = _QUALITY_SUFFIX_RE.sub("", s)
        if stripped == s:
            break
        s = stripped

    # 剩下的清晰度词若在中间，也一并去掉（如「cctv1高清综合」）
    s = _QUALITY_INLINE_RE.sub("", s)
    return s.strip()


def quality_hint(name_or_url: str) -> str:
    """从名称或 URL 里猜清晰度标签，用于 P0 阶段的粗略排序（P2 会换成实测码率）。"""
    s = unicodedata.normalize("NFKC", name_or_url).lower()
    if "4k" in s or "2160" in s or "uhd" in s:
        return "4K"
    if "1080" in s or "fhd" in s or "超清" in s or "超高清" in s:
        return "FHD"
    if "720" in s or "hd" in s or "高清" in s:
        return "HD"
    if "标清" in s or "480" in s or "360" in s:
        return "SD"
    return ""
