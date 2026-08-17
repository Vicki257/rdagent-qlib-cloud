#!/usr/bin/env python3
"""Validation Gate —— 独立、确定性地判断一轮实验的结果能不能信。

## 职责边界

    RD-Agent      负责「想」（提假设、写因子）
    Qlib          负责「算」（训练、回测）
    Validation Gate 负责「判断能不能信」   ← 本文件
    knowledge_map 负责「人理解学到了什么」

**PASS / FAIL 不由 RD-Agent 决定。** RD-Agent 自己的 `HypothesisFeedback.decision`
只是它的意见，会被原样记录下来，但不参与判定。本文件只读 Qlib 的真实结果
和配置文件，全部判定都是确定性的（同样输入必然同样输出），不调用任何 LLM。

## 四组检查

    Gate 1  数据 / 时间安全      结构性错误 → FAIL
    Gate 2  因子本身有没有信息    第一版只记录，不判定
    Gate 3  有没有增量价值        baseline vs baseline+新因子 → 无增量则 FAIL
    Gate 4  稳定性               按年切片 → 全靠单一年份撑起来则 FAIL

第一版刻意不设 `IC > 0.03` 这类武断阈值。只有「一定是错」的东西才 FAIL，
「好不好」交给人看 knowledge_map。原则：宁可结果少，也不要产生假的量化结论。

## 用法

    python validation/validate.py --log-dir log/2026-08-16_06-35-38-526479
    python validation/validate.py --log-dir log/... --loop Loop_0
    python validation/validate.py --log-dir log/... --quiet     # 只写文件不打印

输出写到 `<log-dir>/<Loop_N>/validation.json`，格式：

    {"status": "PASS"|"FAIL", "reasons": [...], "metrics": {...}}

退出码：PASS=0，FAIL=1，无法判定=2。
"""

from __future__ import annotations

import argparse
import glob
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validation.checks import (  # noqa: E402
    FAIL,
    OK,
    WARN,
    load_market_config,
    run_environment_checks,
    run_recorded_config_checks,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 读 RD-Agent 的 log pickle
# ---------------------------------------------------------------------------


def newest(loop_dir: Path, relative: str) -> Path | None:
    files = sorted(loop_dir.joinpath(relative).glob("*/*.pkl"))
    return files[-1] if files else None


def all_pickles(loop_dir: Path, relative: str) -> list[Path]:
    return sorted(loop_dir.joinpath(relative).glob("*/*.pkl"))


def load(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            return pickle.load(handle)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 读不出 {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def series_to_dict(series: Any) -> dict[str, float] | None:
    if series is None:
        return None
    try:
        return {str(key): float(value) for key, value in series.items()}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Gate 1：数据 / 时间安全
# ---------------------------------------------------------------------------


def gate1(
    gate_config: dict[str, Any], recorded_config_text: str | None
) -> tuple[list[str], dict[str, Any], list[str]]:
    """复用 validation/checks.py 那套检查（不在这里重写第二份）。

    判定优先用**这一轮自己记录下来的 config**（RD-Agent 把当时用的 yaml 原文
    存在 runner result 的 experiment_workspace.file_dict 里）。理由：如果只看
    当下磁盘上的配置，那么隔几天、切过市场之后回溯验证旧实验，就会拿今天的
    环境去判昨天的结果，产出一堆假 FAIL。

    「当前环境」的检查（patch 有没有生效、数据目录在不在、因子源数据和
    provider 是否同市场）仍然照跑，但只在**没有**记录配置时参与判定；
    有记录配置时它们作为 `environment_now` 附上，供人参考。
    """

    if not gate_config.get("enabled", True):
        return [], {"skipped": True}, []

    env_checks, environment = run_environment_checks()
    env_payload = {
        "environment": environment,
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail}
            for check in env_checks
        ],
    }

    if recorded_config_text:
        checks, recorded = run_recorded_config_checks(recorded_config_text)
        reasons = [f"Gate1 {check.name}：{check.detail}" for check in checks if check.failed]
        warnings = [
            f"Gate1 {check.name}：{check.detail}" for check in checks if check.status == WARN
        ]
        # 当前环境的失败项降级为警告：它描述的是「现在」，不是「当时」。
        warnings += [
            f"Gate1（当前环境，不参与本轮判定）{check.name}：{check.detail}"
            for check in env_checks
            if check.failed
        ]
        metrics = {
            "verdict_source": "该轮自己记录的 config",
            "recorded": recorded,
            "checks": [
                {"name": check.name, "status": check.status, "detail": check.detail}
                for check in checks
            ],
            "environment_now": env_payload,
            "n_failed": len(reasons),
        }
        return reasons, metrics, warnings

    reasons = [f"Gate1 {check.name}：{check.detail}" for check in env_checks if check.failed]
    warnings = [
        f"Gate1 {check.name}：{check.detail}" for check in env_checks if check.status == WARN
    ]
    warnings.append(
        "Gate1 这一轮没有留下自己的 config（多半是跑到回测之前就结束了），"
        "只能用当前环境判定 —— 如果环境后来改过，这个判定不代表当时的情况。"
    )
    metrics = {
        "verdict_source": "当前环境（该轮没有记录 config）",
        "recorded": None,
        **env_payload,
        "n_failed": len(reasons),
    }
    return reasons, metrics, warnings


# ---------------------------------------------------------------------------
# Gate 2：因子本身有没有信息（第一版只记录）
# ---------------------------------------------------------------------------

IC_KEYS = ("IC", "Rank IC", "ICIR", "Rank ICIR")


def gate2(
    current: dict[str, float] | None, gate_config: dict[str, Any]
) -> tuple[list[str], dict[str, Any], list[str]]:
    if not gate_config.get("enabled", True):
        return [], {"skipped": True}, []
    if not current:
        return (
            ["Gate2 拿不到本轮的 Qlib 指标（这一轮没跑到回测，或日志缺失）"],
            {"available": False},
            [],
        )

    metrics: dict[str, Any] = {
        key: current.get(key) for key in IC_KEYS if key in current
    }
    # ICIR = IC 的稳定性（IC 均值 / IC 标准差）。Qlib 已经算好了，不重复造轮子。
    metrics["ic_stability_note"] = (
        "ICIR / Rank ICIR 就是 IC 的稳定性指标（IC 均值 ÷ IC 标准差），Qlib 直接输出。"
    )
    # 分时段 IC 需要逐日预测值。RD-Agent 在 Docker 容器里跑 qrun，只把汇总
    # 指标和回测曲线带出来，**没有持久化 pred.pkl / mlruns**，所以分时段 IC
    # 在当前架构下拿不到。这里显式说明「拿不到」，不用别的东西糊弄成 IC。
    metrics["ic_by_period"] = None
    metrics["ic_by_period_unavailable_reason"] = (
        "RD-Agent 只把 qrun 的汇总指标和回测曲线带出容器，没有持久化逐日预测值"
        "（pred.pkl / mlruns），因此分时段 IC 无法计算。Gate 4 用回测曲线做了"
        "分年的收益/Sharpe/回撤切片，那部分是真实数据。要补分时段 IC，需要先改"
        "让 qrun 把 mlruns 目录拷出容器 —— 属于未解决项，没有伪造。"
    )
    warnings = [
        "Gate2 分时段 IC 不可得（RD-Agent 未持久化逐日预测值），只有整体 IC"
    ]
    return [], metrics, warnings


# ---------------------------------------------------------------------------
# Gate 3：有没有增量价值
# ---------------------------------------------------------------------------


def gate3(
    current: dict[str, float] | None,
    baseline: dict[str, float] | None,
    curves: dict[str, Any],
    gate_config: dict[str, Any],
) -> tuple[list[str], dict[str, Any], list[str]]:
    if not gate_config.get("enabled", True):
        return [], {"skipped": True}, []

    reasons: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not current:
        return (
            ["Gate3 拿不到本轮指标，无法比较"],
            {"available": False},
            [],
        )
    if not baseline:
        message = (
            "Gate3 拿不到 baseline 指标，「新因子 vs 只有 baseline」这个核心比较"
            "做不了。没有对照就没有增量结论。"
        )
        if gate_config.get("require_baseline", True):
            reasons.append(message)
        else:
            warnings.append(message)
        metrics["baseline_available"] = False

    compare = gate_config.get("compare_metrics") or []
    table: dict[str, Any] = {}
    for key in compare:
        left = current.get(key)
        right = (baseline or {}).get(key)
        table[key] = {
            "baseline": right,
            "with_new_factor": left,
            "delta": (left - right) if (left is not None and right is not None) else None,
        }
    metrics["comparison"] = table

    # 换手和成本从两条回测曲线算（曲线里有 turnover / cost 两列，是真实数据）。
    for label, curve in (("baseline", curves.get("baseline")), ("with_new_factor", curves.get("combined"))):
        if curve is None:
            continue
        entry: dict[str, Any] = {}
        if "turnover" in curve:
            entry["mean_daily_turnover"] = float(curve["turnover"].mean())
        if "total_turnover" in curve:
            entry["total_turnover"] = float(curve["total_turnover"].iloc[-1])
        if "cost" in curve:
            entry["mean_daily_cost"] = float(curve["cost"].mean())
        if "total_cost" in curve:
            entry["total_cost"] = float(curve["total_cost"].iloc[-1])
        if entry:
            metrics.setdefault("execution", {})[label] = entry

    # 唯一的硬性判定：Rank IC 必须真的有增量。
    # 用 Rank IC 而不是年化收益，因为年化收益容易被少数右尾赢家支配
    # （这一点在私有仓库的 TOPIX Small 实验里被实测证明过：分组平均收益
    # 和 Rank IC 可以指向相反方向）。Rank IC 稳健得多。
    if gate_config.get("fail_if_no_incremental_rank_ic", True) and baseline:
        threshold = float(gate_config.get("min_rank_ic_improvement", 0.0005))
        left, right = current.get("Rank IC"), baseline.get("Rank IC")
        if left is None or right is None:
            reasons.append("Gate3 两边缺 Rank IC，无法判断增量价值")
        else:
            delta = left - right
            metrics["rank_ic_delta"] = delta
            metrics["rank_ic_threshold"] = threshold
            if delta < threshold:
                reasons.append(
                    f"Gate3 新因子没有带来增量信息：Rank IC {right:.6f} → {left:.6f}"
                    f"（Δ={delta:+.6f}，需要 ≥ {threshold}）。"
                    "新因子自己看起来漂不漂亮不重要，加进现有模型有没有新信息才重要。"
                )
    return reasons, metrics, warnings


# ---------------------------------------------------------------------------
# Gate 4：稳定性（按时间切片）
# ---------------------------------------------------------------------------


def _slice_stats(returns: Any, benchmark: Any = None) -> dict[str, Any]:
    import numpy as np

    series = returns.dropna()
    if len(series) < 5:
        return {"days": int(len(series)), "insufficient": True}
    equity = (1.0 + series).cumprod()
    drawdown = float((equity / equity.cummax() - 1.0).min())
    mean, std = float(series.mean()), float(series.std(ddof=1))
    annual = float((1.0 + mean) ** 252 - 1.0)
    stats = {
        "days": int(len(series)),
        "annualized_return": annual,
        "annualized_vol": float(std * np.sqrt(252)),
        "sharpe": float(mean / std * np.sqrt(252)) if std > 0 else None,
        "max_drawdown": drawdown,
        "cumulative_return": float(equity.iloc[-1] - 1.0),
    }
    if benchmark is not None:
        bench = benchmark.reindex(series.index).dropna()
        if len(bench) >= 5:
            excess = series.reindex(bench.index) - bench
            stats["excess_cumulative_return"] = float((1.0 + excess).prod() - 1.0)
            stats["excess_annualized_return"] = float(
                (1.0 + float(excess.mean())) ** 252 - 1.0
            )
    return stats


def gate4(
    curves: dict[str, Any], gate_config: dict[str, Any]
) -> tuple[list[str], dict[str, Any], list[str]]:
    if not gate_config.get("enabled", True):
        return [], {"skipped": True}, []

    curve = curves.get("combined")
    if curve is None or "return" not in curve:
        return (
            ["Gate4 拿不到回测曲线，无法做稳定性切片"],
            {"available": False},
            [],
        )

    import pandas as pd

    frame = curve.copy()
    frame.index = pd.DatetimeIndex(frame.index)
    returns = frame["return"]
    bench = frame["bench"] if "bench" in frame else None

    by = gate_config.get("slice_by", "year")
    if by == "half_year":
        keys = frame.index.to_period("Q").astype(str).map(
            lambda q: q[:4] + ("H1" if q[-1] in "12" else "H2")
        )
    else:
        keys = frame.index.year.astype(str)

    slices: dict[str, Any] = {}
    for key in sorted(set(keys)):
        mask = keys == key
        slices[str(key)] = _slice_stats(
            returns[mask], bench[mask] if bench is not None else None
        )

    metrics: dict[str, Any] = {
        "slice_by": by,
        "slices": slices,
        "overall": _slice_stats(returns, bench),
        "ic_by_slice": None,
        "ic_by_slice_unavailable_reason": (
            "分时段 IC 需要逐日预测值，RD-Agent 没有持久化（见 Gate 2）。"
            "这里的收益 / Sharpe / 回撤切片来自真实回测曲线。"
        ),
    }

    reasons: list[str] = []
    warnings: list[str] = []
    usable = {
        key: value
        for key, value in slices.items()
        if not value.get("insufficient") and value.get("cumulative_return") is not None
    }
    if len(usable) < 2:
        warnings.append(
            f"Gate4 只有 {len(usable)} 个有效时间切片，样本太短，稳定性结论无意义"
        )
        return reasons, metrics, warnings

    # 核心判定：把贡献最大的那一个切片去掉，整体还剩不剩正收益。
    # 目的就是抓「总体很好，但其实只靠某一年撑起来」这种情况。
    contributions = {key: value["cumulative_return"] for key, value in usable.items()}
    best = max(contributions, key=lambda key: contributions[key])
    total = sum(contributions.values())
    without_best = total - contributions[best]
    metrics["contribution_by_slice"] = contributions
    metrics["largest_contributor"] = best
    metrics["sum_all_slices"] = total
    metrics["sum_excluding_largest"] = without_best
    metrics["positive_slice_share"] = sum(
        1 for value in contributions.values() if value > 0
    ) / len(contributions)

    if gate_config.get("fail_if_single_slice_carries_all", True):
        if total > 0 and without_best <= 0:
            reasons.append(
                f"Gate4 整体正收益完全靠单一时间切片 {best} 撑起来："
                f"全部切片累计 {total:+.4f}，去掉 {best}（贡献 "
                f"{contributions[best]:+.4f}）之后变成 {without_best:+.4f}。"
                "这不是稳定的信号，是一次性事件。"
            )
    return reasons, metrics, warnings


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def collect_curves(loop_dir: Path) -> dict[str, Any]:
    """两条回测曲线：baseline 先跑、combined 后跑，按时间戳排序取。

    RD-Agent 的 runner 依次执行 `qrun conf_baseline.yaml` 和
    `qrun conf_combined_factors.yaml`，每跑完一条就往
    `running/Quantitative Backtesting Chart/` 落一个 pkl，所以按文件名
    （带时间戳）排序，第一个是 baseline，最后一个是加了新因子的。
    只有一个的时候不猜它是哪条，当成 combined 并记下来。
    """

    paths = all_pickles(loop_dir, "running/Quantitative Backtesting Chart")
    frames = [load(path) for path in paths]
    frames = [frame for frame in frames if frame is not None and hasattr(frame, "columns")]
    curves: dict[str, Any] = {"n_curves": len(frames)}
    if len(frames) >= 2:
        curves["baseline"] = frames[0]
        curves["combined"] = frames[-1]
    elif len(frames) == 1:
        curves["combined"] = frames[0]
        curves["only_one_curve"] = True
    return curves


def validate_loop(log_dir: Path, loop_name: str, gate_config: dict[str, Any]) -> dict[str, Any]:
    loop_dir = log_dir / loop_name
    runner = load(newest(loop_dir, "running/runner result"))
    feedback = load(newest(loop_dir, "feedback/feedback"))

    current = series_to_dict(getattr(getattr(runner, "running_info", None), "result", None))
    baseline = None
    based = getattr(runner, "based_experiments", None) or []
    if based:
        baseline = series_to_dict(
            getattr(getattr(based[-1], "running_info", None), "result", None)
        )
    curves = collect_curves(loop_dir)

    # 这一轮当时实际用的 Qlib 配置原文。RD-Agent 把它存进了 runner result 的
    # experiment_workspace.file_dict，所以回溯验证时能拿到「当时」而不是「现在」。
    workspace_files = getattr(
        getattr(runner, "experiment_workspace", None), "file_dict", None
    ) or {}
    recorded_config_text = workspace_files.get("conf_combined_factors.yaml") or workspace_files.get(
        "conf_baseline.yaml"
    )

    reasons: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    for name, runner_fn in (
        (
            "gate1_data_safety",
            lambda: gate1(gate_config.get("gate1_data_safety", {}), recorded_config_text),
        ),
        ("gate2_factor_information", lambda: gate2(current, gate_config.get("gate2_factor_information", {}))),
        (
            "gate3_incremental_value",
            lambda: gate3(current, baseline, curves, gate_config.get("gate3_incremental_value", {})),
        ),
        ("gate4_stability", lambda: gate4(curves, gate_config.get("gate4_stability", {}))),
    ):
        gate_reasons, gate_metrics, gate_warnings = runner_fn()
        reasons += gate_reasons
        warnings += gate_warnings
        metrics[name] = gate_metrics

    metrics["qlib_metrics"] = {"with_new_factor": current, "baseline": baseline}
    # RD-Agent 自己的意见原样记录，但**不参与判定**。
    metrics["rdagent_own_opinion"] = {
        "decision": getattr(feedback, "decision", None),
        "note": "RD-Agent 自己的判定，仅供参考，不参与 Validation Gate 的 PASS/FAIL。",
    }

    gate1_metrics = metrics.get("gate1_data_safety") or {}
    # 优先用该轮记录的配置描述这次实验；没有才退回当前环境。
    environment = gate1_metrics.get("recorded") or gate1_metrics.get("environment") or {}
    return {
        "status": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "warnings": warnings,
        "metrics": metrics,
        "log_dir": str(log_dir.relative_to(REPO)) if log_dir.is_relative_to(REPO) else str(log_dir),
        "loop": loop_name,
        "market": environment.get("market"),
        "mode": environment.get("mode"),
        "frozen_test_used": environment.get("frozen_test_used", False),
        "known_risks": environment.get("known_risks", {}),
        "validated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validator_version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument("--loop", help="只验这一个 Loop_N；默认全部")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    log_dir = args.log_dir if args.log_dir.is_absolute() else REPO / args.log_dir
    if not log_dir.is_dir():
        print(f"找不到 {log_dir}", file=sys.stderr)
        return 2

    gate_config = (load_market_config() or {}).get("gate", {})
    loops = (
        [args.loop]
        if args.loop
        else sorted(
            path.name
            for path in log_dir.iterdir()
            if path.is_dir() and path.name.startswith("Loop_")
        )
    )
    if not loops:
        print(f"{log_dir.name} 里没有 Loop_* 目录（这一轮在建 loop 之前就结束了）")
        return 2

    worst = 0
    for loop_name in loops:
        result = validate_loop(log_dir, loop_name, gate_config)
        target = log_dir / loop_name / "validation.json"
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        if not args.quiet:
            mark = "✅ PASS" if result["status"] == "PASS" else "❌ FAIL"
            print(f"  {loop_name}: {mark}  → {target.relative_to(log_dir)}")
            for reason in result["reasons"]:
                print(f"      FAIL 原因: {reason}")
            for warning in result["warnings"]:
                print(f"      警告: {warning}")
        if result["status"] == "FAIL":
            worst = 1
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
