from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.domain.enums import Channel, ChannelPostStatus
from app.domain.models import ChannelAccount, ChannelPost, ScriptBeat, VideoScript
from app.repositories.activity import ActivityLogRepository
from app.repositories.channels import ChannelRepository
from app.repositories.scripts import ScriptRepository

# 账号定位与真实写稿任务一致：面向 AI 应用开发者与效率人群的中文科技内容。
# 种子数据用固定随机种子生成，保证每次初始化结果一致；source 统一标记为 demo。
SEED_VERSION = "2026.10"

ACCOUNT_BLUEPRINT: list[dict[str, str]] = [
    {
        "key": Channel.XIAOHONGSHU.value,
        "display_name": "Agent效率手账",
        "handle": "Agent效率手账",
        "account_type": "图文笔记",
        "followers": "28400",
    },
    {
        "key": Channel.SHIPINHAO.value,
        "display_name": "Agent大模型应用开发",
        "handle": "Agent大模型应用开发",
        "account_type": "中长视频",
        "followers": "15200",
    },
    {
        "key": Channel.DOUYIN.value,
        "display_name": "Agent应用笔记",
        "handle": "Agent应用笔记",
        "account_type": "短视频",
        "followers": "62100",
    },
    {
        "key": Channel.KUAISHOU.value,
        "display_name": "AI应用开发日常",
        "handle": "AI应用开发日常",
        "account_type": "短视频",
        "followers": "18700",
    },
    {
        "key": Channel.WECHAT.value,
        "display_name": "Agent大模型应用开发",
        "handle": "Agent大模型应用开发",
        "account_type": "深度图文",
        "followers": "12400",
    },
]

# 每个渠道一个（标题, 摘要, 分类）内容池；固定顺序 + 固定随机种子 = 确定性输出。
CONTENT_POOL: dict[Channel, list[tuple[str, str, str]]] = {
    Channel.XIAOHONGSHU: [
        (
            "程序员效率翻倍的 6 个 AI 工具，亲测好用✅",
            "从代码补全到文档生成，这 6 个工具我每天都在用，最后一个最惊喜。",
            "效率工具",
        ),
        (
            "Agent 开发入门｜从 0 到 1 搭一个自动写周报的机器人",
            "不用大模型微调，纯 API + 工作流编排，周末两天就能跑起来。",
            "实战教程",
        ),
        (
            "AI 编程助手横评：Claude vs GPT vs DeepSeek",
            "同一个需求喂给三家模型，从准确率、改造成本两个维度拆给你看。",
            "模型评测",
        ),
        (
            "打工人必存的 Prompt 模板，直接抄作业",
            "把岗位 JD 贴进去就能用的结构化模板，试过的都说省时间。",
            "职场成长",
        ),
        (
            "大模型学习路线图，少走半年弯路",
            "先补工程能力还是先补算法？这张图给你一个可执行的顺序。",
            "学习路线",
        ),
        (
            "AI 整理会议纪要的 3 种姿势，第二种最省事",
            "录音转写、要点提取、行动项分派，一条流水线全搞定。",
            "效率工具",
        ),
        (
            "本地跑大模型需要什么配置？一张表看懂",
            "从 7B 到 70B，显存、内存、吞吐的最低要求都帮你算好了。",
            "硬件指南",
        ),
    ],
    Channel.SHIPINHAO: [
        (
            "3 个提升编码效率的 AI 实用技巧",
            "分享我在工作中亲测有效的效率方法，希望对你有帮助。",
            "效率技巧",
        ),
        (
            "Agent 工作流演示：一条命令完成日报",
            "从拉取 Git 记录到生成日报草稿，全程不到一分钟。",
            "产品演示",
        ),
        (
            "大模型 API 接入实操：从密钥到第一次调用",
            "十分钟带你跑通第一个对话接口，附常见报错排查。",
            "实战教程",
        ),
        (
            "用 AI 搭建知识库问答机器人",
            "把团队文档变成随问随答的助手，检索与生成两端都讲清楚。",
            "产品演示",
        ),
        (
            "结构化输出实战：让模型稳定返回 JSON",
            "Schema 约束 + 校验重试，接口再也不用怕模型发挥。",
            "实战教程",
        ),
    ],
    Channel.DOUYIN: [
        (
            "一周 Agent 开发合集｜5 分钟看懂工具调用",
            "简单直接好懂的 Agent 入门，让每一次调用都有迹可循。",
            "实战教程",
        ),
        (
            "3 分钟讲清 MCP：AI 连接万物的 USB-C",
            "协议、服务端、工具发现，一张图说明白。",
            "行业观察",
        ),
        (
            "别再手写 Prompt 模板了，试试结构化输出",
            "字段级约束 + 自动校验，一次通过率提升明显。",
            "效率技巧",
        ),
        (
            "AI 写代码真的靠谱吗？我用 30 个任务测了一周",
            "从单文件脚本到多模块改造，结果比想象中有意思。",
            "模型评测",
        ),
        (
            "DeepSeek 新模型上手：接入避坑指南",
            "鉴权、限流、超时重试，第一次接入最容易踩的坑都在这。",
            "实战教程",
        ),
        (
            "大模型上下文窗口到底怎么算？一条视频讲透",
            "Token 计费、截断策略、记忆分层，看完就能优化你的应用。",
            "行业观察",
        ),
    ],
    Channel.KUAISHOU: [
        (
            "旧笔记本也能跑 AI：县域开发者的 Agent 实测",
            "不换电脑不花钱，开源模型 + 量化方案跑通完整流程。",
            "实战教程",
        ),
        (
            "AI 帮我写卖货文案，是真的能打",
            "把产品参数喂进去，十条文案任挑，附提示词。",
            "效率技巧",
        ),
        (
            "零基础学 AI 编程第一课：环境怎么搭",
            "从安装 Python 到调用第一个模型接口，一步一步来。",
            "学习路线",
        ),
        (
            "小商家用 AI 做周报，同事都以为我加班了",
            "数据表格一贴，总结自动出，方法全部公开。",
            "职场成长",
        ),
        (
            "AI 选品靠谱吗？我拿 200 个商品试了试",
            "销量预测和评论分析两条路，都有能落地的做法。",
            "行业观察",
        ),
    ],
    Channel.WECHAT: [
        (
            "Jev 模型：Agent 的结构化判断层",
            "用“分诊台”类比讲清 state、Choice 与 Score 的协作机制。",
            "深度文章",
        ),
        (
            "别再找 DeepSeek Harness：把 DeepSeek 接入 Agent Harness 的正确方式",
            "官方 dsh 与自建装配的四根接线，一次讲清接入路径。",
            "深度文章",
        ),
        (
            "Claude Opus 5.5 动手实测：Agent 开发者视角",
            "基于官方一手资料，评测定位、定价与工具调用表现。",
            "深度文章",
        ),
        (
            "大模型上下文管理实战：从拼接工程到记忆分层",
            "上下文预算、压缩策略与检索协同的三层架构。",
            "深度文章",
        ),
        (
            "Agent 评测怎么做：从手感驱动到指标驱动",
            "任务成功率、工具调用准确率与回归集的搭建方法。",
            "深度文章",
        ),
        (
            "小团队如何搭建 LLM 网关：成本、限流与可观测",
            "一套自研网关的选型记录，附压测数据。",
            "深度文章",
        ),
    ],
}

# 渠道内容形态与默认发布时段
CHANNEL_FORMAT: dict[Channel, dict[str, object]] = {
    Channel.XIAOHONGSHU: {"content_type": "图文笔记", "hours": (11, 21), "per_day": (2, 3)},
    Channel.SHIPINHAO: {"content_type": "产品视频", "hours": (10, 19), "per_day": (1, 2)},
    Channel.DOUYIN: {"content_type": "短视频", "hours": (12, 20), "per_day": (2, 3)},
    Channel.KUAISHOU: {"content_type": "短视频", "hours": (9, 20), "per_day": (1, 2)},
    Channel.WECHAT: {"content_type": "深度文章", "hours": (7, 9), "per_day": (0, 1)},
}

# 各渠道浏览量区间（较低值, 较高值），点赞/评论/分享按比例派生
VIEW_RANGE: dict[Channel, tuple[int, int]] = {
    Channel.XIAOHONGSHU: (4_200, 30_000),
    Channel.SHIPINHAO: (6_000, 36_000),
    Channel.DOUYIN: (15_000, 82_000),
    Channel.KUAISHOU: (3_500, 21_000),
    Channel.WECHAT: (2_400, 15_800),
}

FAIL_REASONS = [
    "封面审核未通过，修改后可重新提交",
    "发布接口超时，请检查网络后重试",
    "标题触发平台敏感词检测，建议改写后重试",
]

SCHEDULE_BLUEPRINT: list[tuple[int, int, Channel, str, str]] = [
    # (当天偏移, 小时, 渠道, 内容形态, 计划标题)
    (0, 10, Channel.WECHAT, "深度文章", "行业观察文章：多智能体协作的工程化落地"),
    (0, 14, Channel.SHIPINHAO, "产品视频", "产品视频：Agent 工作流新功能演示"),
    (0, 16, Channel.XIAOHONGSHU, "图文笔记", "图文笔记：本周 AI 工具合集整理"),
    (0, 19, Channel.DOUYIN, "短视频", "短视频：60 秒讲清结构化输出"),
    (1, 10, Channel.WECHAT, "深度文章", "深度文章：Agent 评测指标体系"),
    (2, 15, Channel.KUAISHOU, "短视频", "短视频：零基础环境搭建第二课"),
]

DEMO_SCRIPTS: list[dict[str, object]] = [
    {
        "title": "3 个提升编码效率的 AI 实用技巧",
        "topic": "AI 编码效率技巧",
        "channel": Channel.SHIPINHAO,
        "duration_seconds": 75,
        "audience": "关注 AI 效率的开发者",
        "hook": "每天写 8 小时代码，这三招至少帮你省下一小时。",
        "beats": [
            {
                "time_range": "00:00-00:08",
                "shot": "工位实拍，屏幕上是排队等待运行的测试",
                "voiceover": "每天写 8 小时代码，这三招至少帮你省下一小时。",
                "on_screen_text": "省 1 小时/天",
            },
            {
                "time_range": "00:08-00:30",
                "shot": "屏幕录制：用 AI 补全样板代码",
                "voiceover": "第一招，把重复的样板代码交给 AI 补全，你只负责审查关键逻辑。",
                "on_screen_text": "技巧一：样板代码自动化",
            },
            {
                "time_range": "00:30-00:52",
                "shot": "屏幕录制：让 AI 生成单元测试",
                "voiceover": "第二招，写完函数立刻让 AI 生成单元测试，边界条件它比你细心。",
                "on_screen_text": "技巧二：测试先行",
            },
            {
                "time_range": "00:52-01:05",
                "shot": "屏幕录制：错误日志粘贴给 AI 分析",
                "voiceover": "第三招，报错日志直接丢给 AI 定位，配合堆栈信息一次说清。",
                "on_screen_text": "技巧三：日志问诊",
            },
            {
                "time_range": "01:05-01:15",
                "shot": "回到工位，合上笔记本",
                "voiceover": "工具是死的，流程是活的。关注我，下周演示完整的 Agent 工作流。",
                "on_screen_text": "关注看下期",
            },
        ],
        "ending": "关注我，每周三个真实可复用的 AI 开发技巧。",
        "cover_idea": "深色键盘特写 + 大字标题“省下1小时”",
        "hashtags": ["AI编程", "效率工具", "程序员日常"],
        "article_angle": "展开成公众号实操长文：三个技巧各自的适用边界、常见误用与工具清单。",
    },
    {
        "title": "60 秒讲清 MCP 协议",
        "topic": "MCP 协议入门",
        "channel": Channel.DOUYIN,
        "duration_seconds": 60,
        "audience": "对 AI 应用感兴趣的普通用户",
        "hook": "AI 怎么读你的文件、查你的数据库？答案就三个字母。",
        "beats": [
            {
                "time_range": "00:00-00:06",
                "shot": "手机竖屏，手指敲桌面",
                "voiceover": "AI 怎么读你的文件、查你的数据库？答案就三个字母。",
                "on_screen_text": "MCP",
            },
            {
                "time_range": "00:06-00:22",
                "shot": "动画：USB-C 接口插入不同设备",
                "voiceover": (
                    "MCP 就像 AI 世界的 USB-C：一头是模型，"
                    "另一头是文件、数据库、网页，插上就能用。"
                ),
                "on_screen_text": "AI 的 USB-C",
            },
            {
                "time_range": "00:22-00:40",
                "shot": "动画：工具列表滚动",
                "voiceover": "服务端把能力登记成工具清单，模型自己决定什么时候调用，参数自动填好。",
                "on_screen_text": "工具自动发现",
            },
            {
                "time_range": "00:40-00:54",
                "shot": "实拍：对话框输入问题，AI 调用日历工具",
                "voiceover": "比如问一句“我下周忙不忙”，它自己查日历再回答你。",
                "on_screen_text": "自动调用",
            },
            {
                "time_range": "00:54-01:00",
                "shot": "结尾定格：频道名",
                "voiceover": "关注我，下期手把手写一个 MCP 服务端。",
                "on_screen_text": "关注不迷路",
            },
        ],
        "ending": "关注我，下期手把手写一个 MCP 服务端。",
        "cover_idea": "大字“MCP”+ USB-C 接口特写",
        "hashtags": ["MCP", "AI科普", "大模型"],
        "article_angle": "扩写成公众号科普文：MCP 与 Function Calling 的差异、安全边界与选型建议。",
    },
]


def _seed_rng() -> random.Random:
    # 固定种子让示例数据每次初始化结果一致；此处不涉及任何安全用途。
    return random.Random(20261024)  # noqa: S311


def _build_accounts() -> list[ChannelAccount]:
    return [
        ChannelAccount(
            key=Channel(item["key"]),  # type: ignore[arg-type]
            display_name=str(item["display_name"]),
            handle=str(item["handle"]),
            account_type=str(item["account_type"]),
            status="active",
            followers=int(item["followers"]),
        )
        for item in ACCOUNT_BLUEPRINT
    ]


def seed_demo_data(
    channels: ChannelRepository,
    scripts: ScriptRepository,
    activity: ActivityLogRepository,
    *,
    now: datetime,
    wechat_account_name: str = "",
) -> None:
    """首启种入一套确定性的多渠道运营数据（source=demo，可随时删除重建）。

    公众号账号名使用系统里配置的真实账号；其余渠道为同一品牌的衍生账号。
    """
    rng = _seed_rng()
    reference = now.astimezone(now.tzinfo) if now.tzinfo else now

    for account in _build_accounts():
        if account.key == Channel.WECHAT and wechat_account_name:
            account.display_name = wechat_account_name
            account.handle = wechat_account_name
        channels.upsert_account(account)

    cursors: dict[Channel, int] = {key: 0 for key in CONTENT_POOL}
    posts: list[ChannelPost] = []

    for offset in range(20, -1, -1):
        day = reference - timedelta(days=offset)
        for channel, spec in CHANNEL_FORMAT.items():
            low, high = spec["per_day"]  # type: ignore[misc]
            if offset > 6 and channel == Channel.WECHAT:
                count = 1 if (offset % 3 == 0) else 0
            else:
                count = rng.randint(low, high)
            for index in range(count):
                pool = CONTENT_POOL[channel]
                title, excerpt, category = pool[cursors[channel] % len(pool)]
                cursors[channel] += 1
                hour_low, hour_high = spec["hours"]  # type: ignore[misc]
                created = day.replace(
                    hour=rng.randint(hour_low, hour_high),
                    minute=rng.choice((5, 15, 20, 30, 40, 45, 50)),
                    second=0,
                    microsecond=0,
                )
                status = ChannelPostStatus.PUBLISHED
                published_at = created if status == ChannelPostStatus.PUBLISHED else None
                views, likes, comments, shares = _derive_metrics(rng, channel, offset)
                posts.append(
                    ChannelPost(
                        channel=channel,
                        content_type=str(spec["content_type"]),
                        title=title,
                        excerpt=excerpt,
                        category=category,
                        status=status,
                        cover_seed=f"{channel.value}-{offset}-{index}",
                        published_at=published_at,
                        views=views,
                        likes=likes,
                        comments=comments,
                        shares=shares,
                        favorites=int(views * rng.uniform(0.004, 0.02)),
                        source="demo",
                        created_at=created,
                        updated_at=created,
                    )
                )

    # 最近 7 天的状态重塑：56 已发布 / 8 待审核 / 12 草稿 / 3 失败 的真实感分布
    recent = [post for post in posts if post.created_at >= reference - timedelta(days=6)]
    recent.sort(key=lambda post: post.created_at, reverse=True)
    failed_idx = {2, 17, 41}
    pending_idx = {5, 9, 13, 22, 27, 31, 36, 44}
    draft_idx = {i for i in range(len(recent)) if i in {0, 3, 6, 8, 11, 15, 19, 24, 29, 33, 38, 43}}
    for index, post in enumerate(recent):
        if index in failed_idx:
            post.status = ChannelPostStatus.FAILED
            post.last_error = FAIL_REASONS[index % len(FAIL_REASONS)]
        elif index in pending_idx:
            post.status = ChannelPostStatus.PENDING_REVIEW
        elif index in draft_idx:
            post.status = ChannelPostStatus.DRAFT
        elif post.status == ChannelPostStatus.DRAFT:
            post.status = ChannelPostStatus.PUBLISHED

    # 上一周（7-13 天前）也铺少量非已发布状态，让发布中心的环比有真实对照。
    previous = [
        post
        for post in posts
        if reference - timedelta(days=13) <= post.created_at < reference - timedelta(days=6)
    ]
    previous.sort(key=lambda post: post.created_at, reverse=True)
    prev_failed_idx = {3, 11}
    prev_pending_idx = {1, 6, 14, 19}
    prev_draft_idx = {0, 4, 8, 15, 22, 28}
    for index, post in enumerate(previous):
        if index in prev_failed_idx:
            post.status = ChannelPostStatus.FAILED
            post.published_at = None
            post.last_error = FAIL_REASONS[(index + 1) % len(FAIL_REASONS)]
        elif index in prev_pending_idx:
            post.status = ChannelPostStatus.PENDING_REVIEW
        elif index in prev_draft_idx:
            post.status = ChannelPostStatus.DRAFT

    # 未成功发布的内容不携带效果数据。
    for post in posts:
        if post.status != ChannelPostStatus.PUBLISHED:
            post.views = post.likes = post.comments = post.shares = post.favorites = 0

    for post in posts:
        if post.status == ChannelPostStatus.FAILED:
            post.published_at = None
    channels.create_posts_bulk(posts, source="demo")

    # 本周发布计划：待发布排期
    for offset, hour, channel, content_type, title in SCHEDULE_BLUEPRINT:
        scheduled = (reference + timedelta(days=offset)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        channels.create_post(
            ChannelPost(
                channel=channel,
                content_type=content_type,
                title=title,
                excerpt="来自本周发布计划的排期内容。",
                category="本周计划",
                status=ChannelPostStatus.SCHEDULED,
                cover_seed=f"plan-{channel.value}-{offset}-{hour}",
                scheduled_at=scheduled,
                source="demo",
                created_at=reference,
                updated_at=reference,
            ),
            source="demo",
        )

    for spec in DEMO_SCRIPTS:
        scripts.create(
            VideoScript(
                title=str(spec["title"]),
                topic=str(spec["topic"]),
                channel=spec["channel"],  # type: ignore[arg-type]
                duration_seconds=int(spec["duration_seconds"]),
                audience=str(spec["audience"]),
                hook=str(spec["hook"]),
                beats=[
                    ScriptBeat.model_validate(item)  # type: ignore[arg-type]
                    for item in spec["beats"]
                ],
                ending=str(spec["ending"]),
                cover_idea=str(spec["cover_idea"]),
                hashtags=list(spec["hashtags"]),  # type: ignore[arg-type]
                article_angle=str(spec["article_angle"]),
                source="demo",
            )
        )

    activity.log(
        "seed",
        "初始化全域渠道示例数据",
        detail=f"5 个渠道账号、发布记录、发布计划与示例脚本（种子版本 {SEED_VERSION}）。",
    )


def _derive_metrics(
    rng: random.Random, channel: Channel, day_offset: int
) -> tuple[int, int, int, int]:
    low, high = VIEW_RANGE[channel]
    # 轻微的近一周上扬趋势，让环比变化有真实来源
    growth = 1.0 + max(0, 6 - day_offset) * 0.012
    views = int(rng.randint(low, high) * growth)
    likes = int(views * rng.uniform(0.02, 0.075))
    comments = int(views * rng.uniform(0.002, 0.012))
    shares = int(views * rng.uniform(0.003, 0.02))
    return views, likes, comments, shares
