"""Material fetcher facade for video backgrounds."""

import logging
import re
from pathlib import Path

from .local_assets_service import LocalAssetsService
from .pexels_service import PexelsService
from .pixabay_service import PixabayService

try:
    from ..synthetic_service import generate_images as synthetic_generate
    from ..synthetic_service import is_available as synthetic_available
except Exception:
    synthetic_generate = None
    synthetic_available = lambda: False

try:
    from ..synthetic_video_service import generate_video_clips as synthetic_video_generate
    from ..synthetic_video_service import is_available as synthetic_video_available
except Exception:
    synthetic_video_generate = None
    synthetic_video_available = lambda: False

logger = logging.getLogger(__name__)


KEYWORD_TRANSLATIONS = {
    "体检报告": "medical report",
    "焦虑": "anxiety",
    "健康饮食": "healthy food",
    "燕麦": "oatmeal",
    "糙米": "brown rice",
    "血糖监测": "blood sugar",
    "鸡胸肉": "chicken breast",
    "三文鱼": "salmon",
    "脂肪肝": "liver health",
    "西兰花": "broccoli",
    "黑木耳": "mushroom",
    "低卡料理": "healthy meal",
    "橙子": "orange",
    "蓝莓": "blueberry",
    "杏仁": "almond",
    "冬瓜": "winter melon",
    "肾结石": "health",
    "超市购物": "grocery shopping",
    "程序员": "programmer",
    "电脑屏幕": "computer screen",
    "代码滚动": "coding",
    "音频波形": "audio",
    "耳机": "headphones",
    "进度条": "progress",
    "勾选符号": "checkmark",
    "服务器机房": "server room",
    "成功手势": "success",
    "大拇指": "thumbs up",
    "离开背影": "walking away",
    "下载图标": "download",
    "思维导图": "mind map",
    "打字动作": "typing",
    "拍摄现场": "filming",
    "摄影器材": "camera equipment",
    "灯光布置": "lighting",
    "剪辑软件": "video editing",
    "波形图": "waveform",
    "手指滑动屏幕": "touch screen",
    "成品展示": "showcase",
    "点赞手势": "like",
    "关注按钮": "subscribe",
    "写字特写": "writing",
    "咖啡时光": "coffee",
    "办公场景": "office",
    "思考特写": "thinking",
    "视频创作": "video creation",
    "脚本构思": "writing",
    "健康食材合集": "healthy ingredients",
    "健康餐盘": "healthy plate",
    "剥开橙子": "peeling orange",
    "蓝莓特写": "blueberries",
    "手抓杏仁": "handful almonds",
    "清炒西兰花": "broccoli cooking",
    "凉拌黑木耳": "mushroom salad",
    "冬瓜汤": "soup",
    "鸡胸肉沙拉": "chicken salad",
    "香煎三文鱼": "grilled salmon",
    "肝脏健康": "liver",
    "血糖": "blood sugar",
    "血压": "blood pressure",
    # Finance / news
    "标普": "stock market",
    "美联储": "federal reserve",
    "利率": "interest rate",
    "中国经济": "chinese economy",
    "法国GDP": "france economy",
    "亚太股市": "asia stock market",
    "日经": "nikkei stock",
    "韩元": "korean won",
    "芯片": "semiconductor",
    "英伟达": "nvidia",
    "石油": "oil crude",
    "台积电": "tsmc semiconductor",
    "松下": "electronics factory",
    "土拍": "real estate land auction",
    "覆铜板": "circuit board",
    "GDP": "economy chart",
    "CPI": "inflation chart",
    "股市": "stock trading floor",
    "港股": "hong kong stock",
    "A股": "china stock market",
    "海湾": "oil field",
    "郑州": "city skyline",
    "德国": "german industry",
    "云南": "china business",
    # More finance / macro / world-news terms
    "通胀": "inflation",
    "通货膨胀": "inflation",
    "通缩": "deflation",
    "加息": "interest rate hike",
    "降息": "interest rate cut",
    "关税": "tariffs trade",
    "贸易战": "trade war",
    "出口": "exports",
    "进口": "imports",
    "央行": "central bank",
    "债券": "bonds",
    "黄金": "gold bullion",
    "大宗商品": "commodities",
    "汇率": "currency exchange",
    "人民币": "chinese yuan",
    "美元": "us dollar",
    "欧元": "euro currency",
    "日元": "japanese yen",
    "房地产": "real estate",
    "楼市": "housing market",
    "制造业": "manufacturing",
    "供应链": "supply chain",
    "新能源": "renewable energy",
    "电动车": "electric vehicle",
    "人工智能": "artificial intelligence",
    "科技": "technology",
    "财报": "earnings report",
    "营收": "revenue",
    "利润": "profit",
    "投资者": "investors",
    "指数": "stock index",
    "道琼斯": "dow jones",
    "纳斯达克": "nasdaq",
    "恒生": "hang seng",
    "失业": "unemployment",
    "就业": "jobs",
    "消费": "consumer spending",
    "能源": "energy industry",
    "天然气": "natural gas",
    "白宫": "white house",
    "欧洲": "europe",
    "美国": "united states",
    "日本": "japan",
    "韩国": "south korea",
    "俄罗斯": "russia",
    "乌克兰": "ukraine",
    "中东": "middle east",
    "战争": "war conflict",
    "停火": "ceasefire",
    "选举": "election",
    "总统": "president",
    "峰会": "summit meeting",
    "制裁": "sanctions",
    "加密货币": "cryptocurrency",
    "比特币": "bitcoin",
    "特斯拉": "tesla factory",
    "苹果": "apple technology",
}


# Neutral, news/finance-safe defaults. Never use food/wellness terms here: when a
# Chinese news keyword failed to translate, the old list pulled irrelevant
# "healthy food / vegetables" footage (see task-01-news-materials).
FALLBACK_KEYWORDS = [
    "stock market",
    "world news",
    "economy",
    "business",
    "technology",
    "city skyline",
    "oil industry",
    "finance",
    "breaking news",
]

# Book pipeline (`type=book`): substring -> English. Longer, most-specific keys
# come first so e.g. "泡沫经济" beats "泡沫" and "失去的十年" beats "经济". These
# never replace the global finance fallback for news; they are only consulted on
# the book path (see ``derive_book_search_terms`` / ``book_fallback_keywords``).
#
# Values are **visual-safe**: stock APIs read polysemous finance words literally,
# so 泡沫/泡沫经济 map to concrete city/property imagery instead of ``bubble``
# (which returned soap bubbles / foam). See ``to_visual_search_terms``.
BOOK_KEYWORD_TRANSLATIONS = {
    "安倍经济学": "abenomics",
    "失去的三十年": "japan lost decades",
    "失去的十年": "japan lost decade",
    "广场协议": "plaza accord",
    "泡沫经济": "japan real estate boom",
    "日元升值": "yen appreciation",
    "日本经济": "japan economy",
    "出口导向": "export-led growth",
    "金融危机": "financial crisis",
    "雷曼兄弟": "lehman brothers",
    "半导体": "semiconductor industry",
    "老龄化": "aging population",
    "少子化": "declining birthrate",
    "制造业": "japanese manufacturing",
    "平成": "heisei era japan",
    "泡沫": "japan housing market",
    "日元": "japanese yen",
    "安倍": "shinzo abe",
    "雷曼": "lehman brothers",
    "通缩": "deflation",
    "央行": "bank of japan",
    "日经": "nikkei",
    "东京": "tokyo",
    "股市": "japan stock market",
    "房地产": "japan real estate",
    "出口": "japan exports",
    "失业": "unemployment",
    "汽车": "japanese auto industry",
    "产业": "japanese industry",
    "日本": "japan",
    "经济": "economy",
}

# Last-resort book fallbacks: book/reading imagery is off-domain-neutral and far
# less misleading than a finance montage when a chapter title yields no tokens.
BOOK_FALLBACK_KEYWORDS = ["books", "library", "reading"]

# Polysemous words stock-photo APIs render *literally* (soap bubbles, foam,
# bursting balloons). Economic-history chapters are the worst case: a title like
# 「泡沫经济的崩溃」 used to send ``bubble economy`` to Pexels and the whole video
# locked onto bubble/foam photos. We never emit these for the book path.
_BANNED_VISUAL_RE = re.compile(r"\b(?:bubbl|foam|burst)", re.IGNORECASE)

# Visual-safe replacements, most specific stem combination first. Each value is
# a tuple of concrete, on-theme stock phrases; the first 1-2 are picked. Keys are
# stems (e.g. "bubbl") so bubble/bubbles/bubbling are all caught.
BOOK_VISUAL_REPLACEMENTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("bubbl", "burst"), ("tokyo recession", "empty office japan", "unemployment japan")),
    (("land", "price", "bubbl"), ("japan housing market", "tokyo apartments", "japan real estate")),
    (("bubbl", "mania"), ("japan real estate boom", "tokyo skyline 1980s")),
    (
        ("bubbl", "economy"),
        ("japan real estate boom", "tokyo skyline 1980s", "tokyo office buildings"),
    ),
    (("asset", "bubbl"), ("japan housing market", "tokyo apartments", "crowded tokyo streets")),
    (
        ("foam",),
        ("japanese manufacturing", "tokyo industry", "japan factory"),
    ),
    (("burst",), ("tokyo recession", "empty office japan", "economic downturn")),
    (
        ("bubbl",),
        ("japan real estate boom", "tokyo skyline", "tokyo office buildings", "japan economy"),
    ),
)

# Alt-text words that betray a literal soap/foam result; skipped when the chapter
# is economic history and better candidates exist (see ``fetch_book_images``).
# Deliberately narrow ("bath"/"balloon" would drop relevant apartment interiors).
BOOK_AVOID_ALT_TERMS = (
    "bubble",
    "bubbles",
    "foam",
    "soap",
    "shampoo",
)


def _has_stem(text: str, stem: str) -> bool:
    """Whole-word-ish match for a stem so ``bubbl`` catches bubble(s/bling)."""
    return re.search(rf"\b{re.escape(stem)}", text) is not None


def _visual_safe_phrase(text: str) -> list[str]:
    """Rewrite one term into concrete, visual-safe stock language."""
    lower = text.lower()
    if not _BANNED_VISUAL_RE.search(lower):
        return [text]
    for stems, alternatives in BOOK_VISUAL_REPLACEMENTS:
        if all(_has_stem(lower, stem) for stem in stems):
            return list(alternatives[:2])
    # Banned token we do not have a specific combo for: fall back to the broad
    # Japan/city visual rather than ever emitting the banned word.
    return ["tokyo skyline", "japan economy"]


def to_visual_search_terms(terms: list[str]) -> list[str]:
    """Rewrite polysemous tokens into concrete stock-photo search language.

    Used by every ``type=book`` query path (chapter anchors, per-segment queries,
    fetches, cover) so words like ``bubble``/``foam``/``burst`` never reach Pexels
    and return soap bubbles instead of Japan / economy imagery. Concrete,
    already-safe terms pass through untouched.
    """
    return _dedupe(
        [
            safe
            for term in (terms or [])
            for safe in _visual_safe_phrase(str(term or "").strip())
            if safe
        ]
    )


# Canonical material sources: online (stock APIs), local (asset library), synthetic (ComfyUI).
# Accept UI-friendly aliases so "pexels"/"pixabay" do not silently fetch nothing.
SOURCE_ALIASES = {
    "online": "online",
    "pexels": "online",
    "pixabay": "online",
    "stock": "online",
    "local": "local",
    "library": "local",
    "assets": "local",
    "synthetic": "synthetic",
    "comfyui": "synthetic",
    "comfy": "synthetic",
    "ai": "synthetic",
    "synthetic_video": "synthetic_video",
    "syntheticvideo": "synthetic_video",
    "animation": "synthetic_video",
    "comfyui_video": "synthetic_video",
    "both": "both",
    "all": "both",
    "auto": "both",
}
# Synthetic/ComfyUI is paused as a default ship path: it is only used when the
# caller explicitly opts in ("synthetic"/"comfyui"/"ai"). "both"/"all"/"auto"
# and unknown values resolve to real network + local stock only.
DEFAULT_SOURCES = {"online", "local"}
ALL_SOURCES = DEFAULT_SOURCES | {"synthetic", "synthetic_video"}


def normalize_sources(source: str | list[str] | None) -> set[str]:
    """Map UI/user source values to a canonical source set.

    "both"/"all"/"auto"/unknown/empty -> default real-stock sources (online+local).
    Explicit "synthetic"/"comfyui"/"ai"/"synthetic_video" opt into generation.
    Accepts comma-separated strings and lists, e.g. "pexels,local".
    """
    if source is None:
        return set(DEFAULT_SOURCES)
    tokens = source if isinstance(source, (list, tuple, set)) else str(source).split(",")
    resolved: set[str] = set()
    wants_defaults = False
    for token in tokens:
        key = str(token).strip().lower()
        if not key:
            continue
        mapped = SOURCE_ALIASES.get(key)
        if mapped == "both":
            wants_defaults = True
            continue
        if mapped:
            resolved.add(mapped)
    if wants_defaults or not resolved:
        resolved |= set(DEFAULT_SOURCES)
    return resolved


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-']*")


def derive_search_terms(keywords: list[str]) -> list[str]:
    """Best-effort English search terms from mixed (often Chinese) keywords.

    Uses the translation map first, then keeps latin tokens (e.g. "GDP", "AI",
    "TSMC") from partially-translated keywords. CJK-only terms without a mapping
    are dropped; the caller falls back to FALLBACK_KEYWORDS when nothing derives.
    Small and dependency-free so it can run per segment without an AI call.
    """
    terms: list[str] = []
    for kw in keywords:
        text = str(kw).strip() if kw is not None else ""
        if not text:
            continue
        mapped = KEYWORD_TRANSLATIONS.get(text)
        if mapped:
            terms.append(mapped)
            continue
        if _CJK_RE.search(text):
            latin = " ".join(_LATIN_TOKEN_RE.findall(text))
            if latin:
                terms.append(latin.lower())
            continue
        terms.append(text.lower())
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    return [t for t in terms if t and not (t in seen or seen.add(t))]


def _book_terms_from_text(text: str) -> list[str]:
    """Substring map a chapter title / keyword to chapter-relevant English.

    Matches are consumed longest-first, so "泡沫经济" wins over "泡沫" and a title
    never emits overlapping duplicates (the old code produced both ``bubble
    economy`` and ``asset bubble`` for 「泡沫经济的崩溃」).
    """
    text = str(text or "")
    if not text:
        return []
    terms: list[str] = []
    remaining = text
    for cjk in sorted(BOOK_KEYWORD_TRANSLATIONS, key=len, reverse=True):
        if cjk and cjk in remaining:
            terms.append(BOOK_KEYWORD_TRANSLATIONS[cjk])
            remaining = remaining.replace(cjk, " ")
    return _dedupe(terms)


def derive_book_search_terms(
    keywords: list[str], chapter_title: str = ""
) -> list[str]:
    """Chapter-relevant English search terms for ``type=book`` material fetches.

    Combines the general mixed keyword translation with a domain dictionary
    matched against the chapter title and each keyword (e.g. 泡沫经济 ->
    ``japan real estate boom``, 日元升值 -> ``yen appreciation``, 雷曼 -> ``lehman
    brothers``). Latin tokens in the title are kept. Unlike the generic
    translation helper, CJK-only terms are mapped by substring instead of being
    silently dropped. Every term is passed through :func:`to_visual_search_terms`
    so polysemous finance words never reach the stock API.
    """
    terms: list[str] = list(derive_search_terms(keywords))
    # Per-segment keyword matches first, then the broader chapter title theme.
    for kw in keywords:
        terms.extend(_book_terms_from_text(str(kw) if kw is not None else ""))
    terms.extend(_book_terms_from_text(chapter_title))
    latin = " ".join(_LATIN_TOKEN_RE.findall(str(chapter_title or "")))
    if latin:
        terms.append(latin.lower())
    # Keyword spelling (e.g. user-supplied English) is also valid.
    for kw in keywords:
        text = str(kw).strip() if kw is not None else ""
        if text and not _CJK_RE.search(text):
            terms.append(text.lower())
    return to_visual_search_terms(_dedupe(terms))


def book_fallback_keywords(
    chapter_title: str = "", keywords: list[str] | None = None
) -> list[str]:
    """Book-specific fallback terms, tied to chapter title/keyword tokens.

    Never returns the global finance/news ``FALLBACK_KEYWORDS``. When the title
    yields nothing domain-specific, neutral book/reading terms are used so the
    book path degrades to relevant-enough imagery (or local/gradient) instead of
    a ``stock market / world news`` montage.
    """
    terms: list[str] = []
    for text in [chapter_title or "", *(keywords or [])]:
        terms.extend(_book_terms_from_text(str(text) if text is not None else ""))
    for generic in BOOK_FALLBACK_KEYWORDS:
        if generic not in terms:
            terms.append(generic)
    return to_visual_search_terms(_dedupe(terms))[:5]


# Terms that are weak on their own: "economy"/"japan"/"business" as a whole
# query returns a random stock montage, which is exactly the topic thrash users
# reported. They are only kept when no narrower term is available.
_GENERIC_BOOK_TERMS = {
    "economy",
    "economic",
    "japan",
    "japanese",
    "business",
    "finance",
    "financial",
    "technology",
    "industry",
    "market",
    "stock",
    "news",
    "world",
    "global",
    "asia",
    "asian",
    "trade",
    "company",
    "companies",
    "world news",
    "stock market",
    "breaking news",
}


def _term_specificity(term: str) -> int:
    """0 for generic fillers, higher for longer/narrower phrases."""
    text = str(term or "").strip().lower()
    if not text:
        return -1
    if text in _GENERIC_BOOK_TERMS:
        return 0
    return max(1, len(text.split()))


def chapter_anchor_terms(chapter_title: str, max_terms: int = 2) -> list[str]:
    """Stable, visual-safe chapter anchor terms, derived once per episode.

    One broad chapter theme visual (plus an optional second concrete term) that
    every segment can share. Never a polysemous word like ``bubble`` — the whole
    point is a *safe* visual that keeps consecutive stills on one coherent theme
    without locking the episode onto a wrong literal.
    """
    terms = _dedupe([t for t in derive_book_search_terms([], chapter_title or "") if t])
    strong = [t for t in terms if _term_specificity(t) > 0]
    return (strong or terms)[:max_terms]


def build_book_segment_query(
    chapter_title: str,
    keywords: list[str] | None,
    anchor: list[str] | None = None,
    max_terms: int = 3,
) -> list[str]:
    """Build one short, visual-safe search query for a book segment.

    Segment-specific concrete visuals lead so each slide reflects its own key
    point; one chapter anchor is added as a light bias (secondary, included
    once) to keep the episode coherent. Generic fillers are dropped when
    narrower terms exist and the total is capped so Pexels gets a focused
    phrase rather than a long OR-like list.
    """
    anchors = [
        t
        for t in _dedupe(list(anchor if anchor is not None else chapter_anchor_terms(chapter_title)))
        if t
    ][:2]
    segment_terms = derive_book_search_terms(
        [str(k) for k in (keywords or []) if k is not None], ""
    )
    specific = [t for t in _dedupe(segment_terms) if t not in anchors]
    narrow = [t for t in specific if _term_specificity(t) > 0]
    weak = [t for t in specific if _term_specificity(t) <= 0]
    primary = narrow if narrow else weak
    # Chapter theme as a secondary bias, never the leading two terms on a slide.
    bias = [a for a in anchors[:1] if a not in primary]
    ordered = _dedupe(primary + bias)
    return (ordered or anchors[:1])[:max_terms]


class MaterialFetcher:
    """Fetch video/image materials from various sources."""

    def __init__(
        self,
        pexels_api_key: str | None = None,
        pixabay_api_key: str | None = None,
        local_assets_dir: Path | None = None,
        book_mode: bool = False,
        book_title: str | None = None,
    ):
        self.pexels = PexelsService(pexels_api_key)
        self.pixabay = PixabayService(pixabay_api_key)
        self.local = LocalAssetsService(local_assets_dir)
        # Book path: chapter-relevant terms + book-specific fallbacks, never the
        # global finance/news FALLBACK_KEYWORDS.
        self.book_mode = bool(book_mode)
        self.book_title = book_title or ""
        # Whole-task dedupe: a fetcher instance is created once per episode, so
        # these sets guarantee the same still/clip is never reused across
        # segments. ``seen_photo_ids`` is passed to Pexels so it can skip
        # already-used photos and walk further down the ranked list.
        self.seen_photo_ids: set[int] = set()
        self.seen_video_ids: set[int] = set()
        self.seen_media_keys: set[str] = set()

    def _dedupe_paths(self, paths: list[Path]) -> list[Path]:
        """Drop media already used in this task (keyed by source + id filename)."""
        unique: list[Path] = []
        for path in paths:
            key = Path(path).stem
            if key in self.seen_media_keys:
                logger.info(f"Skip duplicate material: {key}")
                continue
            self.seen_media_keys.add(key)
            unique.append(path)
        return unique

    def _derive_terms(self, keywords: list[str]) -> list[str]:
        if self.book_mode:
            return derive_book_search_terms(keywords, self.book_title)
        return derive_search_terms(keywords)

    def _fallback_terms(self, keywords: list[str]) -> list[str]:
        if self.book_mode:
            return book_fallback_keywords(self.book_title, keywords)
        return FALLBACK_KEYWORDS[:3]

    def _translate_keywords(self, keywords: list[str]) -> list[str]:
        """Derive English search terms; never return off-topic food fallbacks."""
        translated = self._derive_terms(keywords)
        known = (
            {**KEYWORD_TRANSLATIONS, **BOOK_KEYWORD_TRANSLATIONS}
            if self.book_mode
            else KEYWORD_TRANSLATIONS
        )
        untranslated = [
            str(kw)
            for kw in keywords
            if kw is not None and _CJK_RE.search(str(kw)) and str(kw) not in known
        ]
        if untranslated:
            logger.info(f"No translation for keywords: {untranslated}")
        if not translated:
            fallbacks = self._fallback_terms(keywords)
            if self.book_mode:
                logger.info(
                    f"No translatable keywords in {keywords}; "
                    f"using book-specific fallbacks: {fallbacks}"
                )
            else:
                logger.info(f"No translatable keywords in {keywords}; using news-safe fallbacks")
            return fallbacks
        if self.book_mode:
            # Traceability: the final English query sent to Pexels/Pixabay.
            logger.info(f"Book English search terms: {translated}")
        return translated

    async def fetch_videos(
        self,
        keywords: list[str],
        count: int = 5,
        source: str = "both",
        orientation: str = "landscape",
    ) -> list[Path]:
        """Fetch video materials based on keywords."""
        videos = []
        sources = normalize_sources(source)
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Pexels video query: {english_keywords} (sources={sorted(sources)})")

        if "online" in sources:
            online_videos = await self.pexels.fetch_videos(
                english_keywords, count, orientation=orientation,
                exclude_ids=self.seen_video_ids,
            )
            videos.extend(online_videos)

            if not videos:
                fallbacks = self._fallback_terms(keywords)
                logger.info(f"No online videos found, trying fallback keywords: {fallbacks}")
                for fallback in fallbacks:
                    logger.info(f"Pexels video fallback query: {fallback}")
                    fallback_videos = await self.pexels.fetch_videos(
                        [fallback], count // 3 + 1, orientation=orientation,
                        exclude_ids=self.seen_video_ids,
                    )
                    videos.extend(fallback_videos)
                    if len(videos) >= count:
                        break

        if "local" in sources:
            local_videos = await self.local.fetch_videos(count)
            videos.extend(local_videos)

        videos = self._dedupe_paths(videos)

        # Synthetic animation (ComfyUI video) — explicit opt-in, slow and heavy
        if not videos and "synthetic_video" in sources and synthetic_video_generate:
            try:
                if synthetic_video_available():
                    prompt = ", ".join(english_keywords)
                    logger.info(f"Synthetic video prompt: {prompt}")
                    vw, vh = (768, 512) if orientation == "landscape" else (512, 768)
                    clips = await synthetic_video_generate([prompt], width=vw, height=vh)
                    if clips:
                        videos.extend(clips)
                        logger.info(f"Synthetic animation generated {len(clips)} clips")
            except Exception as e:
                logger.warning(f"Synthetic animation failed: {e}")

        # Synthetic images fallback — ComfyUI SD3.5 (memory-safe, capped)
        if not videos and "synthetic" in sources and synthetic_generate:
            try:
                if synthetic_available():
                    prompt = " ".join(english_keywords) + ", cinematic, high detail"
                    logger.info(f"Synthetic image prompt: {prompt}")
                    synth = await synthetic_generate([prompt], width=768 if orientation=="landscape" else 576, height=576 if orientation=="landscape" else 768)
                    if synth:
                        videos.extend(synth)
                        logger.info(f"Synthetic generated {len(synth)} videos/images as fallback")
            except Exception as e:
                logger.warning(f"Synthetic fetch failed: {e}")

        return videos[:count]

    async def fetch_images(
        self,
        keywords: list[str],
        count: int = 10,
        source: str = "both",
        orientation: str = "landscape",
    ) -> list[Path]:
        """Fetch image materials based on keywords."""
        images = []
        sources = normalize_sources(source)
        english_keywords = self._translate_keywords(keywords)
        logger.info(f"Pexels image query: {english_keywords} (sources={sorted(sources)})")

        if "online" in sources:
            images.extend(
                await self.pexels.fetch_images(
                    english_keywords, count, orientation=orientation,
                    exclude_ids=self.seen_photo_ids,
                )
            )
            images.extend(await self.pixabay.fetch_images(english_keywords, count))

            if not images:
                fallbacks = self._fallback_terms(keywords)
                logger.info(f"No online images found, trying fallback keywords: {fallbacks}")
                for fallback in fallbacks:
                    logger.info(f"Pexels image fallback query: {fallback}")
                    fallback_images = await self.pexels.fetch_images(
                        [fallback], count // 3 + 1, orientation=orientation,
                        exclude_ids=self.seen_photo_ids,
                    )
                    images.extend(fallback_images)
                    if len(images) >= count:
                        break

        if "local" in sources:
            local_images = await self.local.fetch_images(count)
            images.extend(local_images)

        images = self._dedupe_paths(images)

        if not images and "synthetic" in sources and synthetic_generate:
            try:
                if synthetic_available():
                    prompt = " ".join(english_keywords) + ", cinematic, high detail"
                    logger.info(f"Synthetic image prompt: {prompt}")
                    synth = await synthetic_generate([prompt], width=768 if orientation=="landscape" else 576, height=576 if orientation=="landscape" else 768)
                    if synth:
                        images.extend(synth)
                        logger.info(f"Synthetic generated {len(synth)} images as fallback")
            except Exception as e:
                logger.warning(f"Synthetic fetch failed: {e}")

        return images[:count]

    async def fetch_book_images(
        self,
        query: list[str],
        count: int = 10,
        source: str = "online",
        orientation: str = "portrait",
    ) -> list[Path]:
        """Fetch book stills for one already-derived English query.

        Unlike :meth:`fetch_images` the query is not re-derived here: the caller
        builds one short chapter-anchored phrase per segment
        (``build_book_segment_query``) so consecutive stills stay on theme.
        Duplicates for the whole task are filtered via the shared seen sets.
        The query is still passed through :func:`to_visual_search_terms` as a
        defence in depth, and literal soap/foam results are skipped via alt text.
        """
        query = to_visual_search_terms([str(t) for t in (query or []) if t])
        if not query:
            return []

        images: list[Path] = []
        sources = normalize_sources(source)
        logger.info(f"Book image query: {query} (sources={sorted(sources)})")

        if "online" in sources:
            images.extend(
                await self.pexels.fetch_images(
                    query, count, orientation=orientation,
                    exclude_ids=self.seen_photo_ids,
                    avoid_alt_terms=BOOK_AVOID_ALT_TERMS,
                )
            )
            if self.pixabay.api_key:
                images.extend(await self.pixabay.fetch_images(query, count))

        if "local" in sources:
            images.extend(await self.local.fetch_images(count))

        return self._dedupe_paths(images)[:count]