#!/usr/bin/env python3
"""把 validation/config.yaml 里的市场配置真正写进 RD-Agent 安装目录的 Qlib yaml。

## 这个脚本替代了什么

原来 `switch_market.sh jp` 只做一件事：

    sed -i 's|~/.qlib/qlib_data/[a-z_0-9]*"|~/.qlib/qlib_data/jp_smallcap_300"|' ...

只换 provider_uri 一行。`market: csi300`、`benchmark: SH000300`、
`segments: train 2008..2014 / valid 2015..2016 / test 2017..2020`、
`limit_threshold: 0.095`（A股涨跌停）全都留在原地。JP 数据从 2022-01-04
才开始，三段全在数据存在之前，等于 JP 那条线从来没跑出过有意义的数字。

现在改成：所有市场相关字段都从 validation/config.yaml 读，一次性全部写进去，
不可能只改一半。

## 两种模式（这是 Frozen Test 的技术核心）

    --mode research   segments.test = research_oos      RD-Agent 每轮看这个
    --mode frozen     segments.test = frozen_test       只有 run_frozen_test.sh 用

两种模式的 train / validation **完全相同**，只有 test 段不同。所以 frozen
测试评的是同一个模型在一段没被看过的时间上的表现，不是另一个模型。

`--mode frozen` 会在生成的 yaml 顶部写一行显式标记：

    # RDAGENT_QLIB_CLOUD_MODE: frozen

Validation Gate 的 Gate 1 会读这行。普通 loop 如果读到 frozen，直接 FAIL。
这样「普通 loop 有没有碰到 Frozen Test」是**可程序化验证的事实**，
不是靠约定和自觉。

## 用法

    python scripts/apply_market_config.py --market jp --mode research
    python scripts/apply_market_config.py --market jp --mode frozen
    python scripts/apply_market_config.py --show            # 只看当前生效状态
    python scripts/apply_market_config.py --market cn --mode research --print-env

`--print-env` 打印 shell 可以 eval 的 export 语句，给 switch_market.sh 用。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "validation" / "config.yaml"
STATE = REPO / "validation" / "current_state.json"

TEMPLATE_REL = "rdagent/scenarios/qlib/experiment/factor_template"
TARGET_FILES = ("conf_baseline.yaml", "conf_combined_factors.yaml")
MODE_MARKER = "# RDAGENT_QLIB_CLOUD_MODE:"

MODES = ("research", "frozen")


def template_dir() -> Path:
    path = Path(sysconfig.get_paths()["purelib"]) / TEMPLATE_REL
    if not path.is_dir():
        raise SystemExit(
            f"找不到 RD-Agent 的 Qlib 配置模板目录: {path}\n"
            "确认现在在 conda 环境 rdagent 里（不是 rdagent4qlib）。"
        )
    return path


def load_config() -> dict[str, Any]:
    if not CONFIG.exists():
        raise SystemExit(f"找不到 {CONFIG}")
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def resolve_benchmark(spec: Any, provider_uri: str) -> Any:
    """把 benchmark 规格展开成 Qlib 直接能吃的形式。

    字符串原样返回（真实指数代码）。``equal_weight_universe`` 展开成显式的
    股票代码列表 —— Qlib 收到 list 时的语义是「列表内股票的日均涨跌」
    （qlib/backtest/report.py 第 62-64 行），也就是等权市场组合。

    刻意在这里展开而不是留给运行时：生成出来的 yaml 自带完整代码列表，
    以后翻旧实验时基准是什么一目了然，不用去猜当时的股票池长什么样。
    """

    if isinstance(spec, str):
        return spec
    if not isinstance(spec, dict) or spec.get("kind") != "equal_weight_universe":
        raise SystemExit(f"不认识的 benchmark 规格: {spec!r}")

    source = Path(provider_uri).expanduser() / spec.get("source", "instruments/all.txt")
    if not source.exists():
        raise SystemExit(
            f"benchmark 要展开成等权股票池，但找不到 {source}\n"
            "确认这份 Qlib 数据已经灌好（见 README 第 5 节）。"
        )
    codes = []
    for line in source.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts:
            codes.append(parts[0])
    if not codes:
        raise SystemExit(f"{source} 是空的，没法构造等权基准。")
    return sorted(set(codes))


def check_splits(market: str, config: dict[str, Any]) -> list[str]:
    """切分自查：段内顺序、段间重叠、是否超出实测数据范围。

    这里就报错，是为了让「日期写错」在**应用配置的那一刻**就炸，
    而不是等跑完一轮回测拿到一堆没意义的数字才发现。
    """

    problems: list[str] = []
    splits = config["splits"]
    low, high = config["data_available"]

    order = ["train", "validation", "research_oos", "frozen_test"]
    for name in order:
        if name not in splits:
            problems.append(f"{market}.splits 缺少 {name}")
    if problems:
        return problems

    for name in order:
        start, end = splits[name]
        if start > end:
            problems.append(f"{market}.splits.{name} 起止顺序颠倒: {start} > {end}")
        if end < low or start > high:
            problems.append(
                f"{market}.splits.{name} ({start}..{end}) 完全落在数据范围 "
                f"{low}..{high} 之外"
            )
        elif start < low or end > high:
            problems.append(
                f"{market}.splits.{name} ({start}..{end}) 超出数据范围 {low}..{high}"
            )

    for first, second in zip(order, order[1:]):
        if splits[first][1] >= splits[second][0]:
            problems.append(
                f"{market}.splits.{first} 的结束 {splits[first][1]} 不早于 "
                f"{second} 的开始 {splits[second][0]} —— 两段重叠"
            )
    return problems


def apply_to_yaml(
    path: Path,
    market_key: str,
    config: dict[str, Any],
    mode: str,
    benchmark: Any,
) -> dict[str, Any]:
    """就地改写一个 Qlib yaml。

    用文本级的定点替换而不是 yaml.safe_load + dump，是刻意的：官方模板里
    大量使用 `&market` / `*market` 这类 YAML 锚点和别名，round-trip 一次
    锚点全丢，diff 会变得完全没法读，也更容易在不知不觉中改掉别的东西。
    这里每一处替换都用带注释的正则精确定位，改不到就报错，不静默跳过。
    """

    text = path.read_text(encoding="utf-8")
    original = text
    splits = config["splits"]
    test_segment = splits["research_oos" if mode == "research" else "frozen_test"]
    train, validation = splits["train"], splits["validation"]
    data_start = train[0]
    data_end = test_segment[1]
    changed: list[str] = []

    def sub(pattern: str, replacement: str, label: str, *, required: bool = True) -> None:
        nonlocal text
        text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        if count:
            changed.append(f"{label}×{count}")
        elif required:
            raise SystemExit(
                f"{path.name}: 找不到要改的位置「{label}」（正则 {pattern!r}）。\n"
                "很可能 RD-Agent 升级后模板结构变了 —— 停下来人工核对，"
                "不要让它带着旧配置继续跑。"
            )

    sub(
        r'^(\s*provider_uri:\s*)".*?"',
        lambda m: f'{m.group(1)}"{config["provider_uri"]}"',
        "provider_uri",
    )
    sub(r"^(\s*region:\s*)\S+", lambda m: f'{m.group(1)}{config["region"]}', "region")
    sub(
        r"^(market:\s*&market\s*)\S+",
        lambda m: f'{m.group(1)}{config["market"]}',
        "market",
    )

    # benchmark 可能是字符串也可能是列表；列表要写成 YAML 流式序列，
    # 同时保住 `&benchmark` 锚点（下面 port_analysis_config 用 *benchmark 引用它）。
    if isinstance(benchmark, list):
        # 必须加引号:日股代码 13010 不加引号会被 YAML 解析成 **整数**,
        # 而 Qlib 的 D.features 要的是字符串代码,拿到 int 会直接查不到数据。
        # 同一份列表里还混着 167A0 这种天然是字符串的代码,不统一加引号
        # 就会变成 int/str 混合,更难查。
        rendered = "[" + ", ".join('"{}"'.format(code) for code in benchmark) + "]"
    else:
        rendered = str(benchmark)
    sub(
        r"^(benchmark:\s*&benchmark\s*).*$",
        lambda m: f"{m.group(1)}{rendered}",
        "benchmark",
    )

    # data_handler 的取数窗口。start 跟 train 起点对齐，end 跟当前模式的
    # test 终点对齐 —— frozen 模式下必须放宽到 frozen 区间末尾，否则
    # Qlib 根本读不到那段数据，会安静地算出一段空回测。
    sub(
        r"^(\s*start_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{data_start}",
        "handler.start_time",
    )
    sub(
        r"^(\s*end_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{data_end}",
        "handler.end_time",
    )
    # fit_start/fit_end 只有 conf_baseline.yaml 有（Alpha158 的归一化在
    # 这个窗口上拟合）。必须严格等于 train，否则归一化会偷看验证/测试段。
    sub(
        r"^(\s*fit_start_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{train[0]}",
        "handler.fit_start_time",
        required=False,
    )
    sub(
        r"^(\s*fit_end_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{train[1]}",
        "handler.fit_end_time",
        required=False,
    )

    sub(
        r"^(\s*train:\s*)\[.*?\]",
        lambda m: f"{m.group(1)}[{train[0]}, {train[1]}]",
        "segments.train",
    )
    sub(
        r"^(\s*valid:\s*)\[.*?\]",
        lambda m: f"{m.group(1)}[{validation[0]}, {validation[1]}]",
        "segments.valid",
    )
    sub(
        r"^(\s*test:\s*)\[.*?\]",
        lambda m: f"{m.group(1)}[{test_segment[0]}, {test_segment[1]}]",
        "segments.test",
    )

    # 回测窗口跟当前模式的 test 段对齐。原模板写死 2017-01-01..2020-08-01，
    # 这也是之前 JP 模式下回测窗口和数据完全不相交的原因之一。
    sub(
        r"^(\s{8}start_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{test_segment[0]}",
        "backtest.start_time",
        required=False,
    )
    sub(
        r"^(\s{8}end_time:\s*)\d{4}-\d{2}-\d{2}\s*$",
        lambda m: f"{m.group(1)}{test_segment[1]}",
        "backtest.end_time",
        required=False,
    )

    # 涨跌停。null 表示这个市场不模拟涨跌停（日本是阶梯表，表达不了），
    # 直接把整行删掉而不是留一个错的比例值。
    limit = config.get("limit_threshold")
    if limit is None:
        text = re.sub(r"^\s*limit_threshold:.*\n", "", text, flags=re.MULTILINE)
        changed.append("limit_threshold(移除)")
    else:
        sub(
            r"^(\s*limit_threshold:\s*).*$",
            lambda m: f"{m.group(1)}{limit}",
            "limit_threshold",
            required=False,
        )
    for key in ("open_cost", "close_cost", "min_cost"):
        if key in config:
            sub(
                rf"^(\s*{key}:\s*).*$",
                lambda m, v=config[key]: f"{m.group(1)}{v}",
                key,
                required=False,
            )

    header = (
        f"{MODE_MARKER} {mode}\n"
        f"# RDAGENT_QLIB_CLOUD_MARKET: {market_key}\n"
        f"# 本文件由 scripts/apply_market_config.py 从 validation/config.yaml 生成，\n"
        f"# 不要手改 —— 手改会在下一次切换市场时被覆盖，而且 Gate 1 会判定不一致。\n"
    )
    text = re.sub(rf"^{re.escape(MODE_MARKER)}.*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^# RDAGENT_QLIB_CLOUD_MARKET:.*\n", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"^# 本文件由 scripts/apply_market_config\.py.*\n(?:^# 不要手改.*\n)?",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = header + text

    if text != original:
        path.write_text(text, encoding="utf-8")
    return {"file": path.name, "changed": changed}


def read_effective(path: Path) -> dict[str, Any]:
    """把一个 yaml 里真正生效的关键字段读出来，给 --show 和 health_check 用。"""

    text = path.read_text(encoding="utf-8")

    def grab(pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.MULTILINE)
        return match.group(1).strip() if match else None

    benchmark = grab(r"^benchmark:\s*&benchmark\s*(.*)$")
    if benchmark and benchmark.startswith("["):
        count = len([item for item in benchmark.strip("[]").split(",") if item.strip()])
        benchmark = f"<等权组合, {count} 只>"
    return {
        "mode": grab(rf"^{re.escape(MODE_MARKER)}\s*(\S+)"),
        "market_key": grab(r"^# RDAGENT_QLIB_CLOUD_MARKET:\s*(\S+)"),
        "provider_uri": grab(r'^\s*provider_uri:\s*"(.*?)"'),
        "region": grab(r"^\s*region:\s*(\S+)"),
        "market": grab(r"^market:\s*&market\s*(\S+)"),
        "benchmark": benchmark,
        "handler_start": grab(r"^\s*start_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "handler_end": grab(r"^\s*end_time:\s*(\d{4}-\d{2}-\d{2})\s*$"),
        "train": grab(r"^\s*train:\s*(\[.*?\])"),
        "valid": grab(r"^\s*valid:\s*(\[.*?\])"),
        "test": grab(r"^\s*test:\s*(\[.*?\])"),
        "limit_threshold": grab(r"^\s*limit_threshold:\s*(\S+)"),
    }


def show() -> int:
    directory = template_dir()
    print(f"RD-Agent Qlib 配置模板目录: {directory}\n")
    for name in TARGET_FILES:
        path = directory / name
        if not path.exists():
            print(f"{name}: 不存在")
            continue
        print(f"--- {name}")
        for key, value in read_effective(path).items():
            print(f"    {key:16s} = {value}")
        print()
    if STATE.exists():
        print(f"--- validation/current_state.json")
        print(STATE.read_text(encoding="utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--market", choices=("cn", "jp"))
    parser.add_argument("--mode", choices=MODES, default="research")
    parser.add_argument("--show", action="store_true", help="只显示当前生效配置")
    parser.add_argument("--print-env", action="store_true", help="打印 shell export 语句")
    args = parser.parse_args()

    if args.show or not args.market:
        return show()

    config_root = load_config()
    if args.market not in config_root["markets"]:
        raise SystemExit(f"validation/config.yaml 里没有市场 {args.market}")
    market_config = config_root["markets"][args.market]

    problems = check_splits(args.market, market_config)
    if problems:
        print("❌ STOP: validation/config.yaml 的切分定义有问题，拒绝应用：", file=sys.stderr)
        for problem in problems:
            print(f"   - {problem}", file=sys.stderr)
        return 2

    directory = template_dir()
    backup = REPO / "cn_config_backup"
    if args.market == "cn" and all((backup / name).exists() for name in TARGET_FILES):
        # CN 走「先还原官方原件再套配置」，这样官方模板里的锚点、注释、
        # 我们没管到的字段都回到干净状态，不会累积上一次 JP 的残留。
        for name in TARGET_FILES:
            shutil.copy(backup / name, directory / name)

    results = []
    benchmark = resolve_benchmark(market_config["benchmark"], market_config["provider_uri"])
    for name in TARGET_FILES:
        path = directory / name
        if not path.exists():
            raise SystemExit(f"找不到 {path}")
        results.append(apply_to_yaml(path, args.market, market_config, args.mode, benchmark))

    splits = market_config["splits"]
    test_segment = splits["research_oos" if args.mode == "research" else "frozen_test"]
    state = {
        "market": args.market,
        "mode": args.mode,
        "display_name": market_config["display_name"],
        "provider_uri": market_config["provider_uri"],
        "qlib_market": market_config["market"],
        "benchmark": (
            f"equal_weight_universe({len(benchmark)}只)"
            if isinstance(benchmark, list)
            else benchmark
        ),
        "train": splits["train"],
        "validation": splits["validation"],
        "research_oos": splits["research_oos"],
        "frozen_test": splits["frozen_test"],
        "active_test_segment": test_segment,
        "frozen_test_used": args.mode == "frozen",
        "data_available": market_config["data_available"],
        "known_risks": market_config.get("known_risks", {}),
    }
    STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.print_env:
        # RD-Agent 讲给 LLM 听、也显示在网页报告 Config 表格里的说明文字。
        # 由 .devcontainer/patch_market_switch.py 改成读这几个环境变量。
        # 关键点：这里的文字和上面写进 yaml 的日期来自**同一个** splits，
        # 所以不可能再出现「用的是日股数据，AI 以为在研究 CSI300」那种错位。
        label = market_config["display_name"]
        if args.mode == "frozen":
            label += " [FROZEN TEST]"

        def span(pair: list[str]) -> str:
            return "{} to {}".format(pair[0], pair[1])

        exports = {
            "RD_AGENT_MARKET_NAME": label,
            "RD_AGENT_TRAIN_RANGE": span(splits["train"]),
            "RD_AGENT_VALID_RANGE": span(splits["validation"]),
            "RD_AGENT_TEST_RANGE": span(test_segment),
            "RDAGENT_QLIB_CLOUD_MARKET": args.market,
            "RDAGENT_QLIB_CLOUD_MODE": args.mode,
        }
        for name, value in exports.items():
            # ensure_ascii=False：这段文字会被 RD-Agent 讲给 LLM 听、也显示在
            # 网页报告的 Config 表格里，转义成 \uXXXX 会变成一串乱码。
            print("export {}={}".format(name, json.dumps(value, ensure_ascii=False)))
        return 0

    print(f"==> 市场 = {args.market} ({market_config['display_name']})")
    print(f"==> 模式 = {args.mode}")
    print(f"    provider_uri : {market_config['provider_uri']}")
    print(f"    market       : {market_config['market']}")
    print(f"    benchmark    : {state['benchmark']}")
    print(f"    train        : {splits['train'][0]} .. {splits['train'][1]}")
    print(f"    validation   : {splits['validation'][0]} .. {splits['validation'][1]}")
    print(
        f"    test(生效)   : {test_segment[0]} .. {test_segment[1]}"
        f"   ← {'research_oos，RD-Agent 会看到' if args.mode == 'research' else 'FROZEN TEST，RD-Agent 不该看到'}"
    )
    print(f"    frozen_test  : {splits['frozen_test'][0]} .. {splits['frozen_test'][1]}")
    for result in results:
        print(f"    改了 {result['file']}: {', '.join(result['changed'])}")
    print(f"\n状态已写入 {STATE.relative_to(REPO)}")
    if args.mode == "frozen":
        print(
            "\n⚠️  现在是 FROZEN 模式。不要在这个状态下跑 run_one_loop.sh。\n"
            "    跑完 frozen 测试后用 apply_market_config.py --mode research 切回去。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
