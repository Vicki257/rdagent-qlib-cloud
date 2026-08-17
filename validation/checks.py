"""确定性的研究环境检查，被三个地方共用。

    scripts/research_check.py   跑实验前的 ❌ STOP 关卡 / health_check 的研究部分
    validation/validate.py      Validation Gate 的 Gate 1（数据 / 时间安全）
    scripts/run_frozen_test.sh  frozen 测试前的同一套关卡

**共用一份实现是刻意的**：如果 Gate 1 和 health_check 各写一套，
两边迟早会漂移，然后出现「体检说没问题、Gate 说有问题」这种谁也不信谁的局面。

设计原则：
- 能程序化检查的，绝不靠「让 LLM 读一遍代码说看起来没问题」。
- 检查不了的，返回 ``fail`` 并说清为什么检查不了，**不返回 ok**。
  「无法验证」和「验证通过」是两件事，混在一起就是 silent failure。
- 只判「一定是错」的结构性问题，不判「表现好不好」。
"""

from __future__ import annotations

import os
import re
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "validation" / "config.yaml"
STATE_PATH = REPO / "validation" / "current_state.json"
TEMPLATE_REL = "rdagent/scenarios/qlib/experiment/factor_template"
TARGET_FILES = ("conf_baseline.yaml", "conf_combined_factors.yaml")
MODE_MARKER = "# RDAGENT_QLIB_CLOUD_MODE:"
MARKET_MARKER = "# RDAGENT_QLIB_CLOUD_MARKET:"

# provider_uri 路径片段 -> 市场代号。判断「说明文字说的市场」和
# 「实际数据」是不是同一个,靠的就是这张表。新增市场必须更新这里。
PROVIDER_TO_MARKET = (
    ("qlib_data/cn_data", "cn"),
    ("qlib_data/jp_smallcap", "jp"),
)

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def template_dir() -> Path:
    return Path(sysconfig.get_paths()["purelib"]) / TEMPLATE_REL


def load_market_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def read_yaml_facts(path: Path) -> dict[str, Any]:
    """把磁盘上一个 Qlib yaml 里真正生效的关键字段抠出来。"""

    return read_yaml_facts_from_text(path.read_text(encoding="utf-8"), source=str(path))


def read_yaml_facts_from_text(text: str, *, source: str = "<text>") -> dict[str, Any]:
    """同上，但从字符串读 —— 用来检查**当时那一轮自己存下来的** config。

    这条路径是 Gate 1 能正确回溯验证历史实验的关键：RD-Agent 把跑那一轮时
    实际用的 yaml 原文存进了 runner result 的
    ``experiment_workspace.file_dict``。如果 Gate 1 只看当下磁盘上的配置，
    那么隔了几天、切过市场之后再验一遍旧实验，就会拿今天的环境去判昨天的
    结果，得出一堆假的 FAIL。

    刻意用正则读而不是 yaml.safe_load：官方模板大量用 ``&anchor`` / ``*alias``，
    safe_load 之后别名会被展开成值，就看不出「这里引用的是那个锚点」，
    而我们要检查的恰恰是原文里写的是什么。
    """

    def grab(pattern: str, group: int = 1) -> str | None:
        match = re.search(pattern, text, flags=re.MULTILINE)
        return match.group(group).strip() if match else None

    def grab_pair(pattern: str) -> list[str] | None:
        raw = grab(pattern)
        if not raw:
            return None
        parts = [item.strip().strip('"').strip("'") for item in raw.strip("[]").split(",")]
        return parts if len(parts) == 2 else None

    benchmark_raw = grab(r"^benchmark:\s*&benchmark\s*(.*)$")
    benchmark_codes = None
    if benchmark_raw and benchmark_raw.startswith("["):
        benchmark_codes = [
            item.strip().strip('"').strip("'")
            for item in benchmark_raw.strip("[]").split(",")
            if item.strip()
        ]

    # 回测窗口用 8 空格缩进定位(port_analysis_config.backtest 下面),
    # 和 data_handler_config 顶层的 start_time/end_time 区分开。
    return {
        "path": source,
        "mode": grab(rf"^{re.escape(MODE_MARKER)}\s*(\S+)"),
        "market_key": grab(rf"^{re.escape(MARKET_MARKER)}\s*(\S+)"),
        "provider_uri": grab(r'^\s*provider_uri:\s*"(.*?)"'),
        "region": grab(r"^\s*region:\s*(\S+)"),
        "qlib_market": grab(r"^market:\s*&market\s*(\S+)"),
        "benchmark_raw": benchmark_raw,
        "benchmark_codes": benchmark_codes,
        "handler_start": grab(r"^\s{4}start_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "handler_end": grab(r"^\s{4}end_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "fit_start": grab(r"^\s*fit_start_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "fit_end": grab(r"^\s*fit_end_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "backtest_start": grab(r"^\s{8}start_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "backtest_end": grab(r"^\s{8}end_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "train": grab_pair(r"^\s*train:\s*(\[.*?\])"),
        "valid": grab_pair(r"^\s*valid:\s*(\[.*?\])"),
        "test": grab_pair(r"^\s*test:\s*(\[.*?\])"),
        "limit_threshold": grab(r"^\s*limit_threshold:\s*(\S+)"),
        "labels": _extract_labels(text),
    }


def _extract_labels(text: str) -> list[str]:
    """把 label 表达式抠出来，两种写法都要覆盖。

    conf_baseline.yaml 是一行：
        label: ["Ref($close, -2) / Ref($close, -1) - 1"]

    conf_combined_factors.yaml 走 NestedDataLoader，label 是嵌套列表，
    表达式在**后面几行**：
        label:
            - ["Ref($close, -2)/Ref($close, -1) - 1"]
            - ["LABEL0"]

    只用单行正则会漏掉后者，而漏掉的后果是判 FAIL（因为「无法验证」不算通过），
    看起来像 bug 其实是检查本身写窄了。所以这里先定位每个 label: 键，
    再在它后面一小段范围里找带 Ref( 的引号字符串。
    """

    labels: list[str] = []
    for match in re.finditer(r"^\s*label:\s*(.*)$", text, flags=re.MULTILINE):
        # 从 label: 这一行开始，往后看一小段（足够覆盖嵌套列表，又不会跨到
        # 下一个无关的配置块）。
        window = text[match.start() : match.start() + 400]
        # 遇到下一个键就停，避免把 feature 块里的表达式也算成标签 ——
        # 特征用 Ref($close, 1)（过去）是完全正常的，标签用才是错。
        # 缩进不能限定：在 NestedDataLoader 里 feature: 缩进有 20+ 空格。
        stop = re.search(
            r"\n\s*(feature|data_loader|infer_processors|learn_processors|task|"
            r"dataloader_l|kwargs|class):",
            window,
        )
        if stop:
            window = window[: stop.start()]
        labels += [
            quoted
            for quoted in re.findall(r'"([^"]*Ref\(\$[^"]*)"', window)
            if quoted not in labels
        ]
    return labels


def provider_facts(provider_uri: str) -> dict[str, Any]:
    """直接读 Qlib 数据目录的纯文本文件,不 import qlib。

    这样这套检查可以在 ``rdagent`` 环境里跑(那里没装 qlib),
    不需要为了体检去激活 ``rdagent4qlib``。
    """

    root = Path(provider_uri).expanduser()
    facts: dict[str, Any] = {"root": str(root), "exists": root.is_dir()}
    if not facts["exists"]:
        return facts

    calendar = root / "calendars" / "day.txt"
    if calendar.exists():
        days = [line.strip() for line in calendar.read_text().splitlines() if line.strip()]
        facts["calendar_days"] = len(days)
        facts["calendar_start"] = days[0][:10] if days else None
        facts["calendar_end"] = days[-1][:10] if days else None
        facts["calendar"] = [day[:10] for day in days]

    instruments_dir = root / "instruments"
    if instruments_dir.is_dir():
        facts["instrument_files"] = sorted(path.name for path in instruments_dir.glob("*.txt"))
        all_file = instruments_dir / "all.txt"
        if all_file.exists():
            rows = [line.split() for line in all_file.read_text().splitlines() if line.strip()]
            facts["instrument_count"] = len(rows)
            facts["instruments"] = [row[0] for row in rows]
            facts["instruments_with_late_start"] = sum(
                1 for row in rows if len(row) > 1 and row[1][:10] > facts.get("calendar_start", "")
            )
            facts["instruments_with_early_end"] = sum(
                1 for row in rows if len(row) > 2 and row[2][:10] < facts.get("calendar_end", "")
            )
    return facts


def market_from_provider(provider_uri: str) -> str | None:
    for needle, market in PROVIDER_TO_MARKET:
        if needle in provider_uri:
            return market
    return None


# ---------------------------------------------------------------------------
# 具体检查
# ---------------------------------------------------------------------------


def check_config_applied(facts: list[dict[str, Any]]) -> list[Check]:
    """两个 yaml 必须都带标记、且模式/市场一致。"""

    checks: list[Check] = []
    modes = {fact["mode"] for fact in facts}
    markets = {fact["market_key"] for fact in facts}

    if None in modes or None in markets:
        checks.append(
            Check(
                "配置已由 apply_market_config 应用",
                FAIL,
                "有 yaml 缺少 RDAGENT_QLIB_CLOUD_MODE / MARKET 标记，说明它没经过 "
                "apply_market_config.py（可能是手改的，或者 RD-Agent 升级覆盖了）。"
                "跑 `python scripts/apply_market_config.py --market <cn|jp> --mode research` 重新应用。",
                {"modes": sorted(str(m) for m in modes)},
            )
        )
        return checks

    if len(modes) != 1 or len(markets) != 1:
        checks.append(
            Check(
                "两个 yaml 的模式/市场一致",
                FAIL,
                f"conf_baseline 和 conf_combined_factors 不一致：modes={sorted(modes)} "
                f"markets={sorted(markets)}。这会导致 baseline 和新因子跑在不同配置上，"
                "两边的数字根本不可比。",
                {"modes": sorted(modes), "markets": sorted(markets)},
            )
        )
    else:
        checks.append(
            Check(
                "两个 yaml 的模式/市场一致",
                OK,
                f"mode={modes.pop()} market={markets.pop()}",
            )
        )
    return checks


def check_market_label_matches_provider(
    fact: dict[str, Any], config: dict[str, Any]
) -> list[Check]:
    """P1-5 的核心:「说明文字说的市场」必须等于「provider_uri 的市场」。

    这就是 README 里记的那个真实踩过的坑:切了日股数据但报告还显示 CSI300。
    这里检查三方一致:yaml 里的市场标记 / provider_uri 路径 / 环境变量里
    讲给 LLM 听的说明文字。
    """

    checks: list[Check] = []
    provider = fact["provider_uri"] or ""
    declared = fact["market_key"]
    derived = market_from_provider(provider)

    if derived is None:
        checks.append(
            Check(
                "provider_uri 能识别出市场",
                FAIL,
                f"provider_uri={provider!r} 不在已知市场表 PROVIDER_TO_MARKET 里。"
                "新增市场必须同时更新 validation/checks.py 的这张表，"
                "否则「市场一致性」这条检查会失效（宁可报错，不要静默放过）。",
                {"provider_uri": provider},
            )
        )
    elif derived != declared:
        checks.append(
            Check(
                "市场说明 vs provider_uri",
                FAIL,
                f"❌ 错位：yaml 声明市场={declared}，但 provider_uri={provider} "
                f"实际是 {derived} 的数据。这正是会「用 JP 数据却以为在研究 CSI300」"
                "的那种错位，结果数字毫无意义。",
                {"declared": declared, "derived": derived, "provider_uri": provider},
            )
        )
    else:
        checks.append(
            Check("市场说明 vs provider_uri", OK, f"都是 {derived}（{provider}）")
        )

    # 环境变量是 RD-Agent 真正讲给 LLM、也显示在网页报告 Config 表格里的文字。
    env_name = os.environ.get("RD_AGENT_MARKET_NAME")
    expected_display = config.get("display_name")
    if env_name is None:
        checks.append(
            Check(
                "RD_AGENT_MARKET_NAME 已设置",
                WARN if declared == "cn" else FAIL,
                "环境变量 RD_AGENT_MARKET_NAME 没设。CN 用官方默认文字尚可接受，"
                "但 JP 模式下 RD-Agent 会拿默认的 'CSI300 / 2008-2020' 去描述日股数据。"
                "用 `source scripts/switch_market.sh <cn|jp>` 设置（必须 source）。",
            )
        )
    elif expected_display and expected_display.split(" ")[0] not in env_name:
        checks.append(
            Check(
                "RD_AGENT_MARKET_NAME 与配置一致",
                FAIL,
                f"❌ 错位：环境变量说 {env_name!r}，配置里这个市场叫 {expected_display!r}。",
                {"env": env_name, "expected": expected_display},
            )
        )
    else:
        checks.append(Check("RD_AGENT_MARKET_NAME 与配置一致", OK, env_name))
    return checks


def check_provider_data(fact: dict[str, Any], config: dict[str, Any]) -> list[Check]:
    """数据目录真的存在、market 文件存在、并且实测日历和 config.yaml 对得上。"""

    checks: list[Check] = []
    provider = fact["provider_uri"] or ""
    facts = provider_facts(provider)

    if not facts.get("exists"):
        checks.append(
            Check(
                "Qlib 数据目录存在",
                FAIL,
                f"{facts['root']} 不存在。这份数据还没灌进来（见 README 第 5 节）。",
                facts,
            )
        )
        return checks

    checks.append(
        Check(
            "Qlib 数据目录存在",
            OK,
            f"{facts['root']}：{facts.get('instrument_count', '?')} 只股票，"
            f"{facts.get('calendar_days', '?')} 个交易日 "
            f"{facts.get('calendar_start')} .. {facts.get('calendar_end')}",
            facts,
        )
    )

    # market 指向的 instruments 文件必须存在,否则 Qlib 会拿到空股票池。
    market_name = fact["qlib_market"]
    available = facts.get("instrument_files", [])
    if market_name and f"{market_name}.txt" not in available:
        checks.append(
            Check(
                "market 对应的 instruments 文件存在",
                FAIL,
                f"❌ market={market_name} 但 {facts['root']}/instruments/ 里只有 "
                f"{available}。Qlib 会拿到空股票池 —— 这正是 JP 模式下 "
                "market 一直写着 csi300 的问题。",
                {"market": market_name, "available": available},
            )
        )
    else:
        checks.append(
            Check("market 对应的 instruments 文件存在", OK, f"{market_name}.txt")
        )

    # config.yaml 里的 data_available 是设计切分的依据。如果它和真实日历
    # 不一致,说明数据换过而切分没跟着重新设计 —— 必须挡住。
    declared = config.get("data_available")
    actual = [facts.get("calendar_start"), facts.get("calendar_end")]
    if declared and list(declared) != actual:
        checks.append(
            Check(
                "config.yaml 的 data_available 与实测日历一致",
                FAIL,
                f"❌ config.yaml 写的是 {declared}，实测日历是 {actual}。"
                "数据换过但切分没重新设计 —— 现在的 Train/Validation/Frozen Test "
                "边界可能已经没有意义了。改 validation/config.yaml 后重新应用。",
                {"declared": declared, "actual": actual},
            )
        )
    else:
        checks.append(
            Check("config.yaml 的 data_available 与实测日历一致", OK, str(actual))
        )
    return checks


def check_benchmark(fact: dict[str, Any]) -> list[Check]:
    """基准必须是明确的:真实指数代码,或者可重复计算的等权组合。"""

    provider = fact["provider_uri"] or ""
    facts = provider_facts(provider)
    known = set(facts.get("instruments") or [])
    codes = fact["benchmark_codes"]
    raw = fact["benchmark_raw"]

    if codes:
        missing = [code for code in codes if known and code not in known]
        if missing:
            return [
                Check(
                    "benchmark 可解析",
                    FAIL,
                    f"等权基准里有 {len(missing)} 个代码不在 instruments/all.txt 里，"
                    f"例如 {missing[:5]}。Qlib 会直接报 benchmark does not exist。",
                    {"missing": missing[:20]},
                )
            ]
        return [
            Check(
                "benchmark 可解析",
                OK,
                f"等权市场组合，{len(codes)} 只成分（Qlib 对 list 的语义是"
                "「列表内股票的日均涨跌」，可重复计算，不是随便挑的一只股票）",
                {"benchmark_kind": "equal_weight", "n": len(codes)},
            )
        ]

    if not raw:
        return [Check("benchmark 可解析", FAIL, "yaml 里读不到 benchmark。")]
    if known and raw not in known:
        return [
            Check(
                "benchmark 可解析",
                FAIL,
                f"❌ benchmark={raw} 不在这份数据的 instruments/all.txt 里。"
                "这正是「JP 数据配 SH000300」那种错配。",
                {"benchmark": raw},
            )
        ]
    return [Check("benchmark 可解析", OK, f"指数代码 {raw}")]


def check_splits(fact: dict[str, Any], config: dict[str, Any], mode: str) -> list[Check]:
    """三段切分:段内顺序、段间重叠、是否越界、当前模式的 test 段对不对。"""

    checks: list[Check] = []
    splits = config["splits"]
    low, high = config["data_available"]

    order = ["train", "validation", "research_oos", "frozen_test"]
    overlaps = []
    for first, second in zip(order, order[1:]):
        if splits[first][1] >= splits[second][0]:
            overlaps.append(
                f"{first}({splits[first][0]}..{splits[first][1]}) 与 "
                f"{second}({splits[second][0]}..{splits[second][1]}) 重叠"
            )
    checks.append(
        Check(
            "Train / Validation / Research OOS / Frozen Test 互不重叠",
            FAIL if overlaps else OK,
            ("❌ " + "；".join(overlaps)) if overlaps else "四段严格递增、无重叠",
            {"splits": splits},
        )
    )

    outside = [
        f"{name}({splits[name][0]}..{splits[name][1]}) 超出数据范围 {low}..{high}"
        for name in order
        if splits[name][0] < low or splits[name][1] > high
    ]
    checks.append(
        Check(
            "切分不越出数据实际范围",
            FAIL if outside else OK,
            ("❌ " + "；".join(outside)) if outside else f"全部落在 {low}..{high} 内",
        )
    )

    # 归一化拟合窗口必须严格等于 train,否则处理器会偷看验证/测试段。
    if fact.get("fit_start") is not None:
        expected = splits["train"]
        got = [fact["fit_start"], fact["fit_end"]]
        checks.append(
            Check(
                "归一化拟合窗口 == train",
                OK if got == list(expected) else FAIL,
                f"fit={got} train={list(expected)}"
                + ("" if got == list(expected) else " ← ❌ 归一化会偷看未来"),
            )
        )

    # 当前生效的 test 段必须正好等于本模式该用的那一段。
    expected_key = "research_oos" if mode == "research" else "frozen_test"
    expected = [str(value) for value in splits[expected_key]]
    got = fact["test"]
    checks.append(
        Check(
            f"生效的 test 段 == {expected_key}",
            OK if got == expected else FAIL,
            f"test={got} 期望={expected}"
            + ("" if got == expected else f" ← ❌ 模式是 {mode} 却不是 {expected_key}"),
        )
    )

    # research 模式下,取数窗口必须止步于 research_oos 末尾。
    # 这是「RD-Agent 物理上碰不到 Frozen Test」的硬保证:数据根本没被加载。
    if mode == "research":
        frozen_start = str(splits["frozen_test"][0])
        handler_end = fact.get("handler_end")
        backtest_end = fact.get("backtest_end")
        leaks = []
        if handler_end and handler_end >= frozen_start:
            leaks.append(f"data_handler end_time={handler_end} 已经进入 frozen 区间")
        if backtest_end and backtest_end >= frozen_start:
            leaks.append(f"backtest end_time={backtest_end} 已经进入 frozen 区间")
        checks.append(
            Check(
                "research 模式下取数窗口止步于 Frozen Test 之前",
                FAIL if leaks else OK,
                ("❌ " + "；".join(leaks))
                if leaks
                else f"取数止于 {handler_end}，Frozen Test 从 {frozen_start} 起，"
                "Qlib 根本不会加载那段数据",
            )
        )
    return checks


def check_label_horizon(fact: dict[str, Any]) -> list[Check]:
    """标签必须只用严格未来的价格,不能用因子日当天或之前的。

    Qlib 的 ``Ref($close, -k)`` 是「往后 k 天」。官方默认标签
    ``Ref($close, -2) / Ref($close, -1) - 1`` 用的是 t+1 买、t+2 卖,
    两个都是未来,正确。如果出现 ``Ref($close, 0)`` 或正的偏移,
    就是拿当天/过去的价格当标签,等于直接看答案。
    """

    labels = [label for label in fact.get("labels") or [] if "Ref" in label or "$" in label]
    if not labels:
        return [
            Check(
                "标签只用未来价格",
                FAIL,
                "在 yaml 里没找到 label 表达式，无法验证因子日和收益标签有没有错位。"
                "「无法验证」不等于「验证通过」，所以这里判 FAIL。"
                "如果模板结构变了，更新 validation/checks.py 的 label 正则。",
            )
        ]

    problems = []
    for label in labels:
        offsets = [int(value) for value in re.findall(r"Ref\(\$\w+,\s*(-?\d+)\)", label)]
        if not offsets:
            problems.append(f"{label!r} 里没有 Ref 偏移，无法判断时间方向")
            continue
        bad = [offset for offset in offsets if offset >= 0]
        if bad:
            problems.append(f"{label!r} 用到了非未来偏移 {bad}（0 或正数 = 当天/过去）")
    return [
        Check(
            "标签只用未来价格",
            FAIL if problems else OK,
            ("❌ " + "；".join(problems))
            if problems
            else f"{len(labels)} 个标签表达式的 Ref 偏移全为负（严格未来）",
            {"labels": labels},
        )
    ]


def check_factor_source_data(fact: dict[str, Any]) -> list[Check]:
    """因子源数据 daily_pv.h5 必须和 provider_uri 是同一个市场。

    这是 2026-08-17 发现的第二个会静默产生假数字的错配:
    RD-Agent 把 Qlib 行情导出成 git_ignore_folder/factor_implementation_source_data/
    daily_pv.h5,因子代码全部基于它计算。这个文件**会被缓存**,切换 provider
    之后不会自动重新生成。实测当时的状态是:

        daily_pv.h5   6075 只股票, 2008-12-29 .. 2026-08-14   ← CN
        provider_uri  jp_smallcap_300, 300 只, 2022-01-04 ..   ← JP

    也就是「因子在 A 股数据上算,回测在日股数据上跑」。两边股票代码体系
    完全不同,合并后基本全是 NaN,却不会报错。必须挡住。
    """

    source = REPO / "git_ignore_folder" / "factor_implementation_source_data" / "daily_pv.h5"
    if not source.exists():
        return [
            Check(
                "因子源数据与 provider_uri 同市场",
                OK,
                f"{source.name} 还不存在（RD-Agent 第一次跑时会生成），无需检查",
            )
        ]

    try:
        import pandas as pd

        frame = pd.read_hdf(source)
    except Exception as exc:  # noqa: BLE001
        return [
            Check(
                "因子源数据与 provider_uri 同市场",
                FAIL,
                f"读不出 {source}：{type(exc).__name__}: {exc}。"
                "「无法验证」不等于「验证通过」，所以判 FAIL。",
            )
        ]

    dates = frame.index.get_level_values(0)
    instruments = set(map(str, frame.index.get_level_values(1).unique()))
    provider = provider_facts(fact["provider_uri"] or "")
    expected = set(provider.get("instruments") or [])
    source_range = (str(dates.min())[:10], str(dates.max())[:10])
    provider_range = (provider.get("calendar_start"), provider.get("calendar_end"))

    data = {
        "daily_pv_path": str(source),
        "daily_pv_instruments": len(instruments),
        "daily_pv_range": list(source_range),
        "provider_instruments": len(expected),
        "provider_range": list(provider_range),
    }

    if not expected:
        return [
            Check(
                "因子源数据与 provider_uri 同市场",
                FAIL,
                "读不到 provider 的 instruments/all.txt，无法比对。判 FAIL。",
                data,
            )
        ]

    overlap = len(instruments & expected)
    share = overlap / len(expected)
    data["overlap"] = overlap
    data["overlap_share"] = round(share, 4)

    if share < 0.5:
        return [
            Check(
                "因子源数据与 provider_uri 同市场",
                FAIL,
                f"❌ 错配：因子源数据 daily_pv.h5 有 {len(instruments)} 只股票 "
                f"({source_range[0]}..{source_range[1]})，与 provider_uri 的 "
                f"{len(expected)} 只 ({provider_range[0]}..{provider_range[1]}) "
                f"只重叠 {overlap} 只（{share:.1%}）。"
                "说明因子是在另一个市场的数据上算的，合并后基本全是 NaN 却不报错。"
                "删掉 git_ignore_folder/factor_implementation_source_data/ 让 RD-Agent "
                "按当前 provider 重新生成。",
                data,
            )
        ]
    return [
        Check(
            "因子源数据与 provider_uri 同市场",
            OK,
            f"重叠 {overlap}/{len(expected)} 只（{share:.1%}），"
            f"日期 {source_range[0]}..{source_range[1]}",
            data,
        )
    ]


def check_patches() -> list[Check]:
    """P2-6:两个 patch 必须真的生效,失效就 fail fast。

    最危险的情况不是 patch 报错,而是 RD-Agent 升级后 patch 静默没打上,
    程序照样能跑,但实际已经退回官方默认逻辑 ——
    ``patch_market_switch.py`` 没生效意味着说明文字又变回写死的 CSI300,
    ``patch_generate_py.py`` 没生效意味着 generate.py 那个 KeyError 崩溃回来了。
    """

    purelib = Path(sysconfig.get_paths()["purelib"])
    expectations = (
        (
            "patch_market_switch(prompts.yaml)",
            purelib / "rdagent/scenarios/qlib/experiment/prompts.yaml",
            'market_name | default("CSI300", true)',
            "说明文字会退回写死的 CSI300 / 2008-2020，与实际数据错位且察觉不到",
        ),
        (
            "patch_market_switch(factor_experiment.py)",
            purelib / "rdagent/scenarios/qlib/experiment/factor_experiment.py",
            'os.environ.get("RD_AGENT_MARKET_NAME")',
            "说明文字不再读环境变量，switch_market.sh 的市场描述会失效",
        ),
        (
            "patch_generate_py(generate.py)",
            purelib
            / "rdagent/scenarios/qlib/experiment/factor_data_template/generate.py",
            "PATCHED (rdagent-qlib-cloud, 2026-08-16)",
            "generate.py 的选股池/取数窗口错位 bug 会回来（KeyError 崩溃）",
        ),
    )

    checks: list[Check] = []
    for name, path, needle, consequence in expectations:
        if not path.exists():
            checks.append(
                Check(
                    name,
                    FAIL,
                    f"目标文件不存在：{path}。RD-Agent 版本可能变了，"
                    "patch 的落点需要人工重新核对。",
                )
            )
            continue
        if needle in path.read_text(encoding="utf-8"):
            checks.append(Check(name, OK, "patch 已生效"))
        else:
            checks.append(
                Check(
                    name,
                    FAIL,
                    f"❌ patch 没生效（在 {path.name} 里找不到预期标记）。"
                    f"后果：{consequence}。"
                    "重新执行 `python .devcontainer/patch_market_switch.py` / "
                    "`python .devcontainer/patch_generate_py.py`，"
                    "如果还是不行说明上游代码结构变了，必须人工核对后再跑实验。",
                )
            )
    return checks


def run_recorded_config_checks(config_text: str) -> tuple[list[Check], dict[str, Any]]:
    """检查**某一轮当时自己存下来的** Qlib config，用于回溯验证。

    只做「从配置本身就能判断对错」的检查：市场与 provider 是否一致、切分是否
    重叠/越界、归一化窗口是否偷看未来、标签是否只用未来价格、research 模式下
    取数窗口有没有伸进 Frozen Test。

    这里**不**检查 patch 是否生效、数据目录是否存在 —— 那些是「现在的环境」
    的属性，回溯验证一轮几天前的实验时，今天的环境说明不了当时的情况。
    那部分由 run_environment_checks() 单独报告，标注为「当前环境」。
    """

    checks: list[Check] = []
    fact = read_yaml_facts_from_text(config_text, source="<该轮自己记录的 config>")
    provider = fact["provider_uri"] or ""
    derived = market_from_provider(provider)
    declared = fact["market_key"]

    if derived is None:
        checks.append(
            Check(
                "该轮 provider_uri 能识别出市场",
                FAIL,
                f"该轮记录的 provider_uri={provider!r} 不在已知市场表里，无法判断"
                "市场一致性。「无法验证」不等于「验证通过」，判 FAIL。",
                {"provider_uri": provider},
            )
        )
        return checks, {"recorded": fact}

    if declared is None:
        # 2026-08-17 之前跑的实验没有这个标记（那时候还没有 apply_market_config）。
        # 不能因此判 FAIL —— 那是历史事实，不是错误；但要说清楚少了什么。
        checks.append(
            Check(
                "该轮配置带市场标记",
                WARN,
                f"该轮的 config 没有 RDAGENT_QLIB_CLOUD_MARKET 标记（2026-08-17 引入 "
                f"apply_market_config.py 之前跑的实验都没有）。从 provider_uri 推断"
                f"市场为 {derived}。",
                {"derived": derived},
            )
        )
    elif declared != derived:
        checks.append(
            Check(
                "该轮市场标记 vs provider_uri",
                FAIL,
                f"❌ 该轮记录的配置本身就错位：标记市场={declared}，"
                f"provider_uri={provider} 实际是 {derived}。这一轮的数字无意义。",
                {"declared": declared, "derived": derived},
            )
        )
    else:
        checks.append(Check("该轮市场标记 vs provider_uri", OK, f"都是 {derived}"))

    market_key = declared or derived
    config_root = load_market_config()
    market_config = config_root["markets"].get(market_key)
    if market_config is None:
        checks.append(
            Check(
                "该轮市场在 validation/config.yaml 里有定义",
                FAIL,
                f"该轮市场 {market_key!r} 在 validation/config.yaml 里找不到定义，"
                "没法对照切分。",
            )
        )
        return checks, {"recorded": fact, "market": market_key}

    mode = fact["mode"] or "research"
    checks += check_splits(fact, market_config, mode)
    checks += check_label_horizon(fact)
    checks += check_benchmark_recorded(fact, market_config)

    recorded = {
        "market": market_key,
        "mode": mode,
        "provider_uri": provider,
        "qlib_market": fact["qlib_market"],
        "benchmark": (
            "equal_weight_universe({}只)".format(len(fact["benchmark_codes"]))
            if fact["benchmark_codes"]
            else fact["benchmark_raw"]
        ),
        "train": fact["train"],
        "valid": fact["valid"],
        "test": fact["test"],
        "handler_range": [fact["handler_start"], fact["handler_end"]],
        "backtest_range": [fact["backtest_start"], fact["backtest_end"]],
        "limit_threshold": fact["limit_threshold"],
        "frozen_test_used": mode == "frozen",
        "known_risks": market_config.get("known_risks", {}),
        "config_split_reference": market_config["splits"],
    }
    return checks, recorded


def check_benchmark_recorded(
    fact: dict[str, Any], market_config: dict[str, Any]
) -> list[Check]:
    """只从配置本身判断基准合不合规，不去查数据目录（回溯验证时数据可能已经换了）。

    禁止的情况是「随便找一只股票当基准」。判据：要么是等权组合（list），
    要么是一个不在这份数据成分股里的**指数**代码。如果 benchmark 是单个代码
    而且它就是本市场的一只普通成分股，那就是被禁止的那种占位做法。
    """

    codes = fact["benchmark_codes"]
    raw = fact["benchmark_raw"]
    if codes:
        return [
            Check(
                "该轮 benchmark 是明确可重复的",
                OK,
                f"等权市场组合，{len(codes)} 只成分",
            )
        ]
    if not raw:
        return [Check("该轮 benchmark 是明确可重复的", FAIL, "配置里读不到 benchmark。")]

    expected = market_config.get("benchmark")
    if isinstance(expected, str) and raw == expected:
        return [Check("该轮 benchmark 是明确可重复的", OK, f"真实指数 {raw}")]

    provider = fact["provider_uri"] or ""
    facts = provider_facts(provider)
    known = set(facts.get("instruments") or [])
    if known and raw in known:
        return [
            Check(
                "该轮 benchmark 是明确可重复的",
                FAIL,
                f"❌ benchmark={raw} 是这个股票池里的一只普通成分股，"
                "也就是「随便找一只股票当基准」那种占位做法，禁止用于产出结论。"
                "改用等权市场组合（validation/config.yaml 里的 "
                "benchmark.kind: equal_weight_universe）。",
                {"benchmark": raw},
            )
        ]
    return [
        Check(
            "该轮 benchmark 是明确可重复的",
            OK if known else WARN,
            f"benchmark={raw}"
            + ("（不是成分股，按指数处理）" if known else "（数据目录已不可查，无法进一步核实）"),
        )
    ]


def run_environment_checks(*, require_mode: str | None = None) -> tuple[list[Check], dict[str, Any]]:
    """跑完整一套环境检查。返回 (检查结果, 环境事实)。"""

    checks: list[Check] = []
    directory = template_dir()
    if not directory.is_dir():
        return (
            [
                Check(
                    "RD-Agent Qlib 模板目录存在",
                    FAIL,
                    f"找不到 {directory}。确认在 conda 环境 rdagent 里。",
                )
            ],
            {},
        )

    facts = []
    for name in TARGET_FILES:
        path = directory / name
        if not path.exists():
            checks.append(Check(f"{name} 存在", FAIL, f"找不到 {path}"))
        else:
            facts.append(read_yaml_facts(path))
    if not facts:
        return checks, {}

    checks += check_config_applied(facts)
    primary = facts[0]
    mode = primary["mode"]
    market_key = primary["market_key"]

    if require_mode and mode != require_mode:
        checks.append(
            Check(
                f"当前必须是 {require_mode} 模式",
                FAIL,
                f"❌ STOP：当前生效模式是 {mode!r}，但这条命令要求 {require_mode!r}。"
                + (
                    "普通实验循环绝对不允许在 frozen 模式下跑 —— 那会让 RD-Agent "
                    "看到 Frozen Test 的结果，Frozen Test 就此作废。"
                    "先跑 `python scripts/apply_market_config.py --market "
                    f"{market_key or '<cn|jp>'} --mode research` 切回去。"
                    if require_mode == "research"
                    else ""
                ),
            )
        )

    config_root = load_market_config()
    market_config = config_root["markets"].get(market_key)
    if market_config is None:
        checks.append(
            Check(
                "市场在 validation/config.yaml 里有定义",
                FAIL,
                f"yaml 标记的市场是 {market_key!r}，但 validation/config.yaml 里没有它。",
            )
        )
        return checks, {"mode": mode, "market": market_key}

    checks += check_market_label_matches_provider(primary, market_config)
    checks += check_provider_data(primary, market_config)
    checks += check_benchmark(primary)
    checks += check_splits(primary, market_config, mode or "research")
    checks += check_label_horizon(primary)
    checks += check_factor_source_data(primary)
    checks += check_patches()

    environment = {
        "mode": mode,
        "market": market_key,
        "display_name": market_config.get("display_name"),
        "provider_uri": primary["provider_uri"],
        "qlib_market": primary["qlib_market"],
        "region": primary["region"],
        "benchmark": (
            f"equal_weight_universe({len(primary['benchmark_codes'])}只)"
            if primary["benchmark_codes"]
            else primary["benchmark_raw"]
        ),
        "train": market_config["splits"]["train"],
        "validation": market_config["splits"]["validation"],
        "research_oos": market_config["splits"]["research_oos"],
        "frozen_test": market_config["splits"]["frozen_test"],
        "active_test_segment": primary["test"],
        "frozen_test_used": mode == "frozen",
        "limit_threshold": primary["limit_threshold"],
        "known_risks": market_config.get("known_risks", {}),
        "provider_facts": {
            key: value
            for key, value in provider_facts(primary["provider_uri"] or "").items()
            if key not in ("calendar", "instruments")
        },
    }
    return checks, environment
