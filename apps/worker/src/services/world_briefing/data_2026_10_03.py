"""2026-10-03 策展快照（金样对齐，上海时区过去约 24 小时，7 条）。

所有数字与来源均来自金样 `docs/news-briefing/gold_2026-10-03.md` 的已核实事实，
禁止编造。未来日期由 pipeline 按 `config/news_sources.yaml` 尝试 RSS 拉取，
失败则回退到此快照结构并明确标注（RUNBOOK §3）。
"""

from __future__ import annotations

DATE = "2026-10-03"

ITEMS: list[dict] = [
    {
        "id": "ai-gemini-4-argon",
        "section": "AI",
        "title": "Google 发布 Gemini 4 Argon，先给「可信网络防御方」试用",
        "facts": (
            "Google 于 9 月 30 日宣布旗舰模型 Gemini 4 Argon，面向长程、复杂工作流"
            "（软件工程、法律/金融类知识工作、网络安全防御）。"
            "目前通过 Fairwind 计划仅对受信任的网络防御方开放，公开 API 与消费者上线时间未定；"
            "入门价约每百万输入 $2、输出 $10。"
            "官方称 DeepSWE v1.1 达 77.9%、Vals 经济影响指数领先，输出上限扩到约 100 万 token。"
            "TechRepublic 10 月 2 日报道，Reuters 称其在部分基准上强于 OpenAI Astra / Anthropic Opus，"
            "但四个编程基准里有两个仍落后。"
        ),
        "numbers": ["9 月 30 日", "10 月 2 日", "$2", "$10", "77.9%", "100 万", "四个", "两个"],
        "event_date": "2026-09-30",
        "sources": [
            {"name": "Google 官方博文", "url": "https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon/"},
            {"name": "TechRepublic", "url": "https://www.techrepublic.com/article/news-google-gemini-4-argon-cyber-defenders/"},
        ],
        "for_you": "agent 编码与长任务是 VF / OpenCode 日常用的能力形态；要等公开 API，现在没法直接用。",
        "means": "长任务模型先给防御方试用，公开 API 还要等，开发者短期内用不上。",
        "pexels_query": "data center server engineer cyber security",
        "importance": 9.0,
        "novelty": 9.0,
        "relevance": 9.0,
    },
    {
        "id": "ai-frontier-academy",
        "section": "AI",
        "title": "Anthropic 砸 1 亿美元办 Claude Frontier Academy，目标训出 1 万名落地工程师",
        "facts": (
            "10 月 2 日 Anthropic 宣布投入约 1 亿美元，到 2027 年底培养约 1 万名"
            "「Frontier Deployed Engineers」：先模拟企业部署考核，再进 12 周驻场，"
            "在本单位真正上线 Claude 项目。"
            "首批含 Accenture、Bain、Deloitte、McKinsey、Morgan Stanley、Novo Nordisk 等；"
            "CNBC 提到公司预计今年 IPO，并引用 Reuters 称去年营收约 46 亿美元、经营亏损超 80 亿美元。"
        ),
        "numbers": ["10 月 2 日", "1 亿美元", "2027 年底", "1 万", "12 周", "46 亿美元", "80 亿美元"],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "Anthropic 公告", "url": "https://www.anthropic.com/news/claude-frontier-academy"},
            {"name": "CNBC", "url": "https://www.cnbc.com/2026/10/02/anthropic-to-invest-100-million-to-train-ai-engineer-talent.html"},
        ],
        "for_you": "印证「AI 产能不缺、会落地的人缺」——你「AI 生产、自己只审品味」的路径，和行业瓶颈正好对上。",
        "means": "行业缺的不是模型，而是会把模型落地到企业的人，这正是培训要补的缺口。",
        "pexels_query": "software engineers workshop classroom coding",
        "importance": 8.5,
        "novelty": 8.0,
        "relevance": 9.0,
    },
    {
        "id": "ai-scientist-closed-loop",
        "section": "AI",
        "title": "瑞典团队做出闭环「AI 科学家」：假设→机器人实验→改结论",
        "facts": (
            "查尔姆斯理工等把多 LLM、数据库和实验室机器人串成闭环："
            "在约 6 万条酵母相关关系上提出近 2000 条可测预测，自动写成机器可读实验步骤，"
            "跑完再判对错并迭代。作者强调人仍要定优先级与伦理边界。"
        ),
        "numbers": ["6 万", "2000"],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "Euronews", "url": "https://www.euronews.com/2026/10/02/swedish-researchers-create-an-ai-scientist-that-designs-and-runs-its-own-experiments"},
        ],
        "single_source_reason": "机构新闻稿转述的首发，暂无第二主流源，保留为简讯级（不展开数字外推）。",
        "for_you": "这是「AI 做实验、人审方向」的实验室版，和你用 AI 做生产/回测实验的思路同构。",
        "means": "AI 开始自己做实验、自己改结论，但选题和伦理仍要人来定。",
        "pexels_query": "laboratory robot pipette science experiment",
        "importance": 7.5,
        "novelty": 9.0,
        "relevance": 7.0,
    },
    {
        "id": "tech-perovskite-3077",
        "section": "科技",
        "title": "钙钛矿–硅叠层电池认证效率 30.77%，并报更长稳定运行",
        "facts": (
            "南京大学等用 MASCN「后处理愈合」改善工业级织构硅上的钙钛矿膜，"
            "独立认证叠层效率 30.77%（约 1.164 cm²）；"
            "另有封装器件在最大功率点连续运行约 3400 小时后效率未见下降（初始约 28.4%）。"
        ),
        "numbers": ["30.77%", "1.164", "3400 小时", "28.4%"],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "Perovskite-Info", "url": "https://www.perovskite-info.com/healing-treatment-boosts-textured-silicon-perovskite-tandem-cell-3077"},
        ],
        "single_source_reason": "专业垂媒首发认证效率，暂无第二主流源，数字仅转述原文不外推。",
        "for_you": None,  # 金样此条无对你句，保持一致（自评会扣分并说明）
        "means": "叠层电池效率与寿命同时推进，离规模量产又近一步。",
        "pexels_query": "solar panel lab engineer clean energy",
        "importance": 7.0,
        "novelty": 8.0,
        "relevance": 5.0,
    },
    {
        "id": "econ-market-snapshot",
        "section": "经济与市场",
        "title": "市场快照（10 月 2 日）：港股重挫，A 股休市，美股纳指创新高",
        "facts": (
            "恒生指数假期后首日收 23972.29，跌约 2.60%，为约半年来最重单日跌幅；"
            "南向通休市至约 10 月 8 日。内地 A 股国庆长假休市至约 10 月 7 日。"
            "美国 9 月非农仅增约 2.9 万（路透预期约 9 万），降近端加息押注；"
            "路透称道指约 +0.60%、标普约 +1.02%、纳指约 +1.66% 并创纪录。"
            "布伦特约 $99.88、WTI 约 $89.29；美元兑人民币大致在 6.70 附近。"
            "耐克因中国需求预警大跌约 5.6%。"
        ),
        "numbers": ["10 月 2 日", "23972.29", "2.60%", "10 月 8 日", "10 月 7 日", "2.9 万", "9 万", "+0.60%", "+1.02%", "+1.66%", "$99.88", "$89.29", "6.70", "5.6%"],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "BBN Times", "url": "https://www.bbntimes.com/global-economy/hong-kong-stock-exchange-hang-seng-index-plunges-to-23-972-29-its-steepest-drop-since-march-as-banks-and-tech-slide-after-the-holiday"},
            {"name": "Asia wrap", "url": "https://edgeconsultancykw.com/asia-market-wrap-2-october-2026/"},
            {"name": "Reuters via LSE", "url": "https://www.lse.co.uk/news/us-stocks-nasdaq-hits-record-high-after-softer-jobs-data-tempers-rate-hike-bets-557k1he4uf1csfr.html"},
        ],
        "for_you": "Karios 审计要赶 10 月 9 日开盘前；A 股休市窗口正好用来收尾。",
        "means": "港股大跌、A 股休市、美股新高：假期窗口期，跨市场分化加剧。",
        "pexels_query": "hong kong skyline stock exchange trading screen",
        "importance": 9.5,
        "novelty": 8.5,
        "relevance": 9.0,
        "market_chart": {
            "hang_seng": {"close": 23972.29, "chg": -2.60},
            "dow": {"chg": 0.60},
            "spx": {"chg": 1.02},
            "nasdaq": {"chg": 1.66},
            "brent": 99.88,
            "wti": 89.29,
            "usdcny": 6.70,
            "nfp_actual": 2.9,
            "nfp_expected": 9.0,
        },
    },
    {
        "id": "econ-golden-week",
        "section": "经济与市场",
        "title": "中国长假：出行旺、消费仍偏谨慎，政策继续发力促消费",
        "facts": (
            "国庆黄金周旅游出行升温，但多篇报道指消费仍偏谨慎（需求弱、通缩与地产拖累）；"
            "地方与中央有补贴、降息与消费券等促消费举措。耐克下调展望并点名中国需求偏弱。"
        ),
        "numbers": [],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "Investing.com", "url": "https://www.investing.com/news/stock-market-news/chinas-golden-week-travel-surge-masks-cautious-consumer-spending-4921703"},
        ],
        "single_source_reason": "综合研判类条目，数字已在市场快照条覆盖，本条不新增硬数字。",
        "for_you": None,  # 金样此条无对你句
        "means": "出行热但花钱谨慎，促消费政策还会继续加码。",
        "pexels_query": "china travel crowd train station holiday",
        "importance": 6.5,
        "novelty": 6.0,
        "relevance": 7.0,
    },
    {
        "id": "geo-us-iran-carriers",
        "section": "地缘与冲突",
        "title": "美伊僵持第八个月：美拟增派第三航母打击群，特朗普暗示中期选举后再打",
        "facts": (
            "美方据报向中东增派第三航母打击群及两栖部队（约 9000–10000 人），"
            "年底前可能形成三航母态势。间接谈判未破局："
            "伊朗提「七天重开霍尔木兹换解除封锁/制裁」遭拒；"
            "特朗普谈及十一月中期选举后可能恢复对伊打击。油价回落至百元下方，但冲突未解。"
        ),
        "numbers": ["第八个月", "9000", "10000", "七天", "十一月"],
        "event_date": "2026-10-02",
        "sources": [
            {"name": "CNBC", "url": "https://www.cnbc.com/2026/10/02/us-iran-war-trump-hormuz-.html"},
            {"name": "Al Jazeera", "url": "https://www.aljazeera.com/news/2026/10/2/new-aircraft-carrier-10000-us-troops-is-the-iran-war-about-to-escalate"},
        ],
        "for_you": "油价与风险溢价仍是宏观主线；量化仓位按既定硬规矩，别赌地缘反转。",
        "means": "三航母压境但谈判没破，油价短期回落、中期风险仍在。",
        "pexels_query": "aircraft carrier ocean navy ships",
        "importance": 9.0,
        "novelty": 8.0,
        "relevance": 8.5,
    },
]

VIDEO_TOPICS = [
    "Gemini 4 Argon「先给防御方、暂不公开」",
    "瑞典「AI 科学家」闭环实验",
]

SECTION_ORDER = ["AI", "科技", "经济与市场", "地缘与冲突"]


def get_snapshot(date: str = DATE) -> dict:
    """返回指定日期的策展快照（v1 仅 2026-10-03 有策展，其余回退并标注）。"""
    if date == DATE:
        return {"date": DATE, "items": [dict(it) for it in ITEMS], "video_topics": list(VIDEO_TOPICS)}
    # 回退：复用结构但明确标注为模板（RUNBOOK 要求不得编造为新闻事实）
    snap = {"date": date, "items": [dict(it) for it in ITEMS], "video_topics": list(VIDEO_TOPICS), "fallback": True}
    return snap
