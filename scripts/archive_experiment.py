#!/usr/bin/env python3
"""把 log/ 里的一轮实验抽成少量核心证据文件,让它能进 Git、活得比 Codespace 久。

## 为什么需要这个

真正的 source of truth 现在是 Codespace 容器里的 `log/<时间戳>/`,全是 pickle,
只能靠 `rdagent` 的类反序列化。Codespace 一旦被删(超过 30 天没碰,或手动删),
完整实验日志、RD-Agent 的思考历史、中间结果、生成的因子代码会一起没掉。
`reports/` 里的 PDF 是快照,自己的 README 都写明「不是权威数据源」。

这个脚本每轮结束抽出**未来研究真正需要的证据**,几百 KB 而不是几百 MB:

    experiments/EXP-0001/
      hypothesis.md      RD-Agent 提出的假设 + 它的理由
      factor.py          它实际写出来、跑通了的因子代码
      config.yaml        Qlib 真正用的配置(含 provider_uri / 训练验证测试区间)
      metrics.json       这轮的指标 + 上一个 SOTA 的指标 + 花了多少钱多少时间
      conclusion.md      RD-Agent 自己的判定、观察、和它打算下一轮做什么
      backtest_curve.csv 逐日净值/换手/成本曲线(算回撤、画图用)
      MANIFEST.json      来源日志路径、抽取时间、缺了哪些件

runtime 垃圾(debug_tpl / debug_llm / evolving code 的每一次试错 / settings pkl)
一律不抽。要看那些还是得开 Codespace 用 `rdagent ui`,但那些不是「几周后回来
继续研究」需要的东西。

## 公开 / 私有分流(重要,不要改掉)

`rdagent-qlib-cloud` 是 **Public** 仓库。日股那条线的数字是 J-Quants 授权数据的
衍生物,按 `knowledge_map/AI交接手册.md` 的规定不能进公开仓库。所以本脚本按每轮
**实际用的 `provider_uri`** 分流(读的是那一轮存下来的 config,不是抽取时的环境
变量——环境变量可能早就变了):

    ~/.qlib/qlib_data/cn_data       -> experiments/          进 Git
    ~/.qlib/qlib_data/jp_smallcap*  -> experiments_private/   .gitignore 掉
    认不出来的                       -> experiments_private/   按最保守的处理

`experiments_private/` 要靠 `gh codespace cp` 拉回 Mac 的 `~/jquants`,命令由脚本
自己打出来。**新增市场时必须回来更新 `MARKET_ROUTING`**,不然新市场会被当成私有
(这是故意的:漏判成私有只是麻烦,漏判成公开是泄露)。

## 用法(在 Codespace 里,conda 环境 rdagent)

    python scripts/archive_experiment.py                 # 抽最新一个 log 目录的所有 loop
    python scripts/archive_experiment.py --all           # 回填全部历史 log 目录
    python scripts/archive_experiment.py --log-dir log/2026-08-16_06-35-38-526479
    python scripts/archive_experiment.py --all --commit --push   # 抽完自动提交并推送

编号靠 `experiments/REGISTRY.json` 里的 (log 目录, Loop_N) -> EXP-NNNN 映射,
所以重复跑不会重编号、不会产生重复目录,只会覆盖同一个 EXP 的内容。
"""

from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # noqa: F401  (间接需要:反序列化回测曲线 DataFrame)

REPO = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO / "experiments"
PRIVATE_DIR = REPO / "experiments_private"
REGISTRY = PUBLIC_DIR / "REGISTRY.json"

# provider_uri 片段 -> (市场代号, 是否可以进公开仓库)
MARKET_ROUTING: list[tuple[str, str, bool]] = [
    ("qlib_data/cn_data", "cn", True),
    ("qlib_data/jp_smallcap", "jp", False),
]

# 只抽这些;其余目录都是 runtime 垃圾
ARTIFACTS = {
    "hypothesis": "direct_exp_gen/hypothesis generation",
    "tasks": "direct_exp_gen/experiment generation",
    "code": "coding/coder result",
    "runner": "running/runner result",
    "chart": "running/Quantitative Backtesting Chart",
    "feedback": "feedback/feedback",
}


def newest_pickle(directory: Path) -> Path | None:
    """RD-Agent 每个 artifact 目录是 <pid>/<时间戳>.pkl,同名可能有多份,取最新。"""

    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*/*.pkl"))
    return files[-1] if files else None


def load(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            return pickle.load(handle)
    except Exception as exc:  # noqa: BLE001 - 一个坏 pkl 不该让整轮抽取失败
        print(f"    ! 读不出 {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def attr(obj: Any, name: str, default: Any = None) -> Any:
    """防御性取属性:rdagent 升版本改了字段名时,只丢那一个字段,不整体崩。"""

    return getattr(obj, name, default) if obj is not None else default


def scalar(value: Any) -> Any:
    """把 numpy / pandas / datetime 标量转成能进 JSON 的东西。"""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    for method in ("item", "isoformat"):
        if hasattr(value, method):
            try:
                return getattr(value, method)()
            except Exception:  # noqa: BLE001
                pass
    return str(value)


def series_to_dict(series: Any) -> dict[str, Any] | None:
    if series is None:
        return None
    try:
        return {str(key): scalar(value) for key, value in series.items()}
    except Exception:  # noqa: BLE001
        return None


def route_market(config_text: str | None) -> tuple[str, bool]:
    """从这一轮存下来的 config 判断市场;认不出来一律按私有处理。"""

    if config_text:
        for needle, market, public in MARKET_ROUTING:
            if needle in config_text:
                return market, public
    return "unknown", False


def collect_costs(loop_dir: Path) -> dict[str, Any]:
    """把这一轮所有阶段的 token 花费和墙上时间汇总。"""

    costs = [load(path) for path in sorted(loop_dir.glob("*/token_cost/*/*.pkl"))]
    costs += [load(path) for path in sorted(loop_dir.glob("*/*/token_cost/*/*.pkl"))]
    costs = [item for item in costs if isinstance(item, dict)]
    times = [load(path) for path in sorted(loop_dir.glob("*/time_info/*/*.pkl"))]
    times = [item for item in times if isinstance(item, dict)]

    starts = [item["start_time"] for item in times if item.get("start_time")]
    ends = [item["end_time"] for item in times if item.get("end_time")]
    wall = None
    if starts and ends:
        wall = round((max(ends) - min(starts)).total_seconds(), 1)

    return {
        "llm_calls": len(costs),
        "models": sorted({str(item.get("model")) for item in costs if item.get("model")}),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in costs),
        "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in costs),
        "usd_cost_this_loop": round(sum(float(item.get("cost") or 0.0) for item in costs), 6),
        "usd_accumulated_max": round(
            max((float(item.get("accumulated_cost") or 0.0) for item in costs), default=0.0), 6
        ),
        "wall_clock_seconds": wall,
        "started_utc": scalar(min(starts)) if starts else None,
        "ended_utc": scalar(max(ends)) if ends else None,
    }


def extract(loop_dir: Path) -> dict[str, Any]:
    """读一个 Loop_N 目录,返回抽出来的内容和缺件清单。"""

    found: dict[str, Any] = {}
    missing: list[str] = []
    for key, relative in ARTIFACTS.items():
        path = newest_pickle(loop_dir / relative)
        obj = load(path)
        if obj is None:
            missing.append(relative)
        found[key] = obj
        found[f"{key}_source"] = str(path.relative_to(loop_dir)) if path else None
    found["missing"] = missing
    found["costs"] = collect_costs(loop_dir)
    # Validation Gate 的结果由 validate.py 写在 loop 目录里。
    # 存档时把它一起搬走，这样 experiments/ 是自洽的：
    # 「测了什么 + 通过没通过」在同一个地方，不用回去翻 log/。
    verdict = loop_dir / "validation.json"
    if verdict.exists():
        try:
            found["validation"] = json.loads(verdict.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"    ! validation.json 读不出: {exc}", file=sys.stderr)
            found["validation"] = None
    else:
        found["validation"] = None
    return found


def render_hypothesis(data: dict[str, Any], exp_id: str) -> str:
    hypothesis = data.get("hypothesis")
    tasks = data.get("tasks") or []
    lines = [
        f"# {exp_id} · 假设",
        "",
        "> 这是 RD-Agent 自己提出的假设,原文照抄,没有润色。",
        "",
        "## 假设",
        "",
        str(attr(hypothesis, "hypothesis", "（这一轮没走到提假设,或日志缺失）")),
        "",
        "## 它给的理由",
        "",
        str(attr(hypothesis, "reason", "（无）")),
        "",
    ]
    for extra in ("concise_observation", "concise_justification", "concise_knowledge"):
        value = attr(hypothesis, extra)
        if value:
            lines += [f"## {extra}", "", str(value), ""]

    if tasks:
        lines += ["## 拆成了几个因子任务", ""]
        for index, task in enumerate(tasks, start=1):
            lines += [
                f"### {index}. `{attr(task, 'factor_name', attr(task, 'name', '?'))}`",
                "",
                str(attr(task, "description", "")),
                "",
                "公式：",
                "",
                "```latex",
                str(attr(task, "factor_formulation", "")),
                "```",
                "",
            ]
            variables = attr(task, "variables")
            if isinstance(variables, dict) and variables:
                lines += ["变量：", ""]
                lines += [f"- `{name}`: {meaning}" for name, meaning in variables.items()]
                lines += [""]
    return "\n".join(lines)


def render_factor_code(data: dict[str, Any], exp_id: str) -> str:
    workspaces = data.get("code") or []
    header = [
        '"""',
        f"{exp_id} · RD-Agent 生成并跑通的因子代码（原样保存，未改动）。",
        "",
        "多个因子按 `# ===== 因子: <名字> =====` 分段。每一段就是 RD-Agent 在自己的",
        "工作目录里那份 factor.py 的完整内容。",
        '"""',
        "",
    ]
    if not workspaces:
        return "\n".join(header + ["# （这一轮没有产出因子代码，或日志缺失）", ""])

    blocks: list[str] = []
    for workspace in workspaces:
        task = attr(workspace, "target_task")
        name = attr(task, "factor_name", attr(task, "name", "unnamed"))
        files = attr(workspace, "file_dict") or {}
        code = files.get("factor.py")
        if code is None and files:
            code = next(iter(files.values()))
        blocks += [
            f"# {'=' * 74}",
            f"# ===== 因子: {name} =====",
            f"# 公式: {attr(task, 'factor_formulation', '')}",
            f"# {'=' * 74}",
            "",
            str(code) if code else "# （这个因子没有留下代码）",
            "",
            "",
        ]
    return "\n".join(header + blocks)


def render_conclusion(data: dict[str, Any], exp_id: str, metrics: dict[str, Any]) -> str:
    feedback = data.get("feedback")
    decision = attr(feedback, "decision")
    verdict = {True: "接受（判定为新 SOTA）", False: "否决", None: "没走到给结论这一步"}[
        decision if decision in (True, False) else None
    ]
    lines = [
        f"# {exp_id} · 结论",
        "",
        f"**RD-Agent 的判定**：{verdict}",
        "",
        "> 以下全部是 RD-Agent 自己写的原文，不是我的解读。",
        "> ⚠️ 它的判定只看 Qlib 的纸面指标，**没有**过成本敏感性和隐藏样本外校验",
        "> （见 `../../../jquants/qlib_bridge/RELIABILITY_PLAN.md` 第 3 条）。",
        "",
        "## 它观察到什么",
        "",
        str(attr(feedback, "observations", "（无）")),
        "",
        "## 它怎么评价这个假设",
        "",
        str(attr(feedback, "hypothesis_evaluation", "（无）")),
        "",
        "## 它给的理由",
        "",
        str(attr(feedback, "reason", "（无）")),
        "",
        "## 它打算下一轮做什么",
        "",
        str(attr(feedback, "new_hypothesis", "（无）")),
        "",
    ]
    exception = attr(feedback, "exception")
    if exception:
        lines += ["## 这一轮报的异常", "", "```", str(exception), "```", ""]

    current = metrics.get("this_loop") or {}
    sota = metrics.get("previous_sota") or {}
    if current:
        lines += [
            "## 关键指标（数字来自 `metrics.json`）",
            "",
            "| 指标 | 这一轮 | 上一个 SOTA |",
            "|---|---|---|",
        ]
        for key in (
            "IC",
            "Rank IC",
            "ICIR",
            "Rank ICIR",
            "1day.excess_return_with_cost.annualized_return",
            "1day.excess_return_with_cost.max_drawdown",
            "1day.excess_return_with_cost.information_ratio",
        ):
            if key in current:
                left = current.get(key)
                right = sota.get(key, "—")
                left_text = f"{left:.6f}" if isinstance(left, float) else str(left)
                right_text = f"{right:.6f}" if isinstance(right, float) else str(right)
                lines.append(f"| `{key}` | {left_text} | {right_text} |")
        lines.append("")
    return "\n".join(lines)


def write_experiment(
    target: Path,
    exp_id: str,
    key: str,
    loop_dir: Path,
    data: dict[str, Any],
    market: str,
    public: bool,
) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    runner = data.get("runner")
    workspace_files = attr(attr(runner, "experiment_workspace"), "file_dict") or {}

    based = attr(runner, "based_experiments") or []
    sota_metrics = None
    if based:
        sota_metrics = series_to_dict(attr(attr(based[-1], "running_info"), "result"))

    metrics = {
        "experiment_id": exp_id,
        "market": market,
        "this_loop": series_to_dict(attr(attr(runner, "running_info"), "result")),
        "previous_sota": sota_metrics,
        "factor_names": [
            str(attr(attr(workspace, "target_task"), "factor_name", "?"))
            for workspace in (data.get("code") or [])
        ],
        "rdagent_decision": scalar(attr(data.get("feedback"), "decision")),
        "rdagent_decision_note": (
            "这是 RD-Agent 自己的意见，**不是** Validation Gate 的判定。"
            "权威判定看 validation.json 的 status。"
        ),
        "resources": data["costs"],
    }

    # Validation Gate 的结果。run_one_loop.sh 会在存档之前先跑 validate.py，
    # 所以正常流程下这个文件一定存在；单独回填历史实验时可能没有。
    validation = data.get("validation")
    (target / "validation.json").write_text(
        json.dumps(
            validation
            or {
                "status": "NOT_VALIDATED",
                "reasons": [
                    "这一轮没有 Validation Gate 结果。跑 "
                    f"`python validation/validate.py --log-dir {loop_dir.parent.name}` 生成。"
                ],
                "metrics": {},
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    (target / "hypothesis.md").write_text(
        render_hypothesis(data, exp_id), encoding="utf-8"
    )
    (target / "factor.py").write_text(render_factor_code(data, exp_id), encoding="utf-8")
    (target / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "conclusion.md").write_text(
        render_conclusion(data, exp_id, metrics), encoding="utf-8"
    )

    # metadata.json：以后 Codespace 被删了，仅凭这一个文件也要能说清
    # 「当时测了什么、用的哪段数据、通过没通过、为什么」。
    recorded = ((validation or {}).get("metrics") or {}).get("gate1_data_safety") or {}
    recorded_env = recorded.get("recorded") or {}
    metadata = {
        "experiment_id": exp_id,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market": market,
        "public": public,
        "mode": recorded_env.get("mode"),
        # Frozen Test 单独标记。研究循环产出的实验一律 false；
        # true 只可能来自 scripts/run_frozen_test.sh（它写 frozen_test/ 子目录）。
        "frozen_test_used": bool(recorded_env.get("frozen_test_used", False)),
        "data_range": recorded_env.get("handler_range"),
        "train_range": recorded_env.get("train"),
        "validation_range": recorded_env.get("valid"),
        "active_test_range": recorded_env.get("test"),
        "split_reference": recorded_env.get("config_split_reference"),
        "provider_uri": recorded_env.get("provider_uri"),
        "qlib_market": recorded_env.get("qlib_market"),
        "benchmark": recorded_env.get("benchmark"),
        "limit_threshold": recorded_env.get("limit_threshold"),
        "factor_names": metrics["factor_names"],
        "validation_status": (validation or {}).get("status", "NOT_VALIDATED"),
        "validation_reasons": (validation or {}).get("reasons", []),
        "validation_warnings": (validation or {}).get("warnings", []),
        "rdagent_decision": metrics["rdagent_decision"],
        "next_direction": str(attr(data.get("feedback"), "new_hypothesis", "") or ""),
        "rdagent_log_path": str(loop_dir.relative_to(REPO)),
        # 已知可信性缺陷跟着每一条实验记录走。这样以后翻到一个「表现很好」的
        # 结论时，同一个文件里就写着它是在什么缺陷下跑出来的，
        # 不会出现「数字记住了、前提忘了」。
        "known_risks": recorded_env.get("known_risks", {}),
    }
    (target / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    written = [
        "metadata.json",
        "hypothesis.md",
        "factor.py",
        "metrics.json",
        "validation.json",
        "conclusion.md",
    ]
    # config.yaml 用的是「真正产出这些指标的那份」;baseline 一起留着方便对照。
    for filename, destination in (
        ("conf_combined_factors.yaml", "config.yaml"),
        ("conf_baseline.yaml", "config_baseline.yaml"),
    ):
        if filename in workspace_files:
            (target / destination).write_text(str(workspace_files[filename]), encoding="utf-8")
            written.append(destination)

    chart = data.get("chart")
    if chart is not None and hasattr(chart, "to_csv"):
        chart.to_csv(target / "backtest_curve.csv")
        written.append("backtest_curve.csv")

    manifest = {
        "experiment_id": exp_id,
        "registry_key": key,
        "market": market,
        "public": public,
        "status": "complete" if not data["missing"] else "partial",
        "missing_artifacts": data["missing"],
        "source_log_dir": str(loop_dir.relative_to(REPO)),
        "source_pickles": {
            name: data.get(f"{name}_source") for name in ARTIFACTS
        },
        "extracted_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extracted_from_git_commit": git_head(),
        "files_written": written,
        "note": (
            "这是从 log/ 抽出来的核心证据,不是完整日志。完整 RD-Agent 思考历史"
            "(每一次 LLM 调用、每一次代码试错)仍然只在 Codespace 的 log/ 里,"
            "Codespace 删了就没了 —— 这是有意的取舍:只保存未来研究需要的证据。"
        ),
    }
    (target / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def load_registry() -> dict[str, Any]:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"next_id": 1, "entries": {}}


def save_registry(registry: dict[str, Any]) -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_index(registry: dict[str, Any]) -> None:
    lines = [
        "# 实验索引",
        "",
        "由 `scripts/archive_experiment.py` 自动生成，不要手改。",
        "",
        "`log/` 在 Codespace 里，删掉就没了；这张表和它引用的目录是能活下来的那部分。",
        "私有市场（日股）的条目在 `experiments_private/`，不在这个公开仓库里，",
        "只在这里留一行记录说明它存在过。",
        "",
        "**Gate** 列是 Validation Gate 的独立判定，**RD** 列是 RD-Agent 自己的意见。"
        "两者不一致是正常的 —— Gate 判的是「能不能信」，RD-Agent 判的是「它觉得好不好」。"
        "以 Gate 为准。",
        "",
        "| EXP | 市场 | 存档 | **Gate** | RD | Frozen | IC | Rank IC | 年化(含成本) | 最大回撤 | 来源 log |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for exp_id in sorted(registry["entries"]):
        entry = registry["entries"][exp_id]
        summary = entry.get("summary") or {}

        def show(key: str) -> str:
            value = summary.get(key)
            return f"{value:.6f}" if isinstance(value, float) else "—"

        decision = entry.get("decision")
        verdict = {True: "接受", False: "否决"}.get(decision, "—")
        gate = entry.get("validation_status") or "未验证"
        gate_mark = {"PASS": "✅ PASS", "FAIL": "❌ FAIL"}.get(gate, f"➖ {gate}")
        frozen = "是" if entry.get("frozen_test_used") else "否"
        location = exp_id if entry.get("public") else f"（私有）{exp_id}"
        lines.append(
            f"| {location} | {entry.get('market', '?')} | {entry.get('status', '?')} | "
            f"{gate_mark} | {verdict} | {frozen} | {show('IC')} | {show('Rank IC')} | "
            f"{show('1day.excess_return_with_cost.annualized_return')} | "
            f"{show('1day.excess_return_with_cost.max_drawdown')} | "
            f"`{entry.get('source_log_dir', '?')}` |"
        )
    lines += [
        "",
        "## 每个 EXP 目录里有什么",
        "",
        "| 文件 | 内容 |",
        "|---|---|",
        "| `metadata.json` | 实验ID / 时间 / 市场 / 数据范围 / Train・Validation・Test 范围 / "
        "因子名 / **Gate 判定与失败原因** / RD-Agent 意见 / 下一步方向 / "
        "`frozen_test_used` / 已知可信性缺陷 / 对应 log 路径 |",
        "| `validation.json` | Validation Gate 四组检查的完整结果 |",
        "| `hypothesis.md` | RD-Agent 提的假设、理由、拆成的因子任务和公式 |",
        "| `factor.py` | 它写出来并跑通的因子代码，原样保存 |",
        "| `config.yaml` | Qlib 真正用的配置（含 `provider_uri` 和训练/验证/测试区间） |",
        "| `config_baseline.yaml` | 同一轮的基线配置，用来对照 |",
        "| `metrics.json` | 本轮指标 + 上一个 SOTA 指标 + token 花费 + 墙上时间 |",
        "| `conclusion.md` | RD-Agent 自己的判定/观察/下一步，附关键指标对比表 |",
        "| `backtest_curve.csv` | 逐日净值、换手、成本曲线 |",
        "| `MANIFEST.json` | 来源日志路径、抽取时间、**缺了哪些件** |",
        "",
    ]
    (PUBLIC_DIR / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def archive_log_dir(log_dir: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    loops = sorted(
        (path for path in log_dir.iterdir() if path.is_dir() and path.name.startswith("Loop_")),
        key=lambda path: int(path.name.split("_")[1]) if path.name.split("_")[1].isdigit() else 0,
    )
    if not loops:
        print(f"  {log_dir.name}: 没有 Loop_* 目录（这一轮在建 loop 之前就死了），跳过")
        return []

    results: list[dict[str, Any]] = []
    for loop_dir in loops:
        key = f"{log_dir.name}/{loop_dir.name}"
        entry = registry["entries"].get(_lookup_id(registry, key))
        if entry is None:
            exp_id = f"EXP-{registry['next_id']:04d}"
            registry["next_id"] += 1
        else:
            exp_id = entry["experiment_id"]

        data = extract(loop_dir)
        runner = data.get("runner")
        workspace_files = attr(attr(runner, "experiment_workspace"), "file_dict") or {}
        config_text = str(workspace_files.get("conf_combined_factors.yaml") or "") + str(
            workspace_files.get("conf_baseline.yaml") or ""
        )
        market, public = route_market(config_text or None)

        root = PUBLIC_DIR if public else PRIVATE_DIR
        manifest = write_experiment(
            root / exp_id, exp_id, key, loop_dir, data, market, public
        )

        metrics = series_to_dict(attr(attr(runner, "running_info"), "result")) or {}
        registry["entries"][exp_id] = {
            "experiment_id": exp_id,
            "registry_key": key,
            "market": market,
            "public": public,
            "status": manifest["status"],
            "missing_artifacts": manifest["missing_artifacts"],
            "decision": scalar(attr(data.get("feedback"), "decision")),
            "validation_status": (data.get("validation") or {}).get("status", "NOT_VALIDATED"),
            "frozen_test_used": bool(
                (
                    ((data.get("validation") or {}).get("metrics") or {})
                    .get("gate1_data_safety", {})
                    .get("recorded")
                    or {}
                ).get("frozen_test_used", False)
            ),
            "source_log_dir": str(loop_dir.relative_to(REPO)),
            "extracted_utc": manifest["extracted_utc"],
            "summary": {
                key_name: metrics.get(key_name)
                for key_name in (
                    "IC",
                    "Rank IC",
                    "1day.excess_return_with_cost.annualized_return",
                    "1day.excess_return_with_cost.max_drawdown",
                )
            },
        }
        where = "experiments" if public else "experiments_private（不进 Git）"
        flag = "" if manifest["status"] == "complete" else f"  ⚠ partial，缺 {data['missing']}"
        print(f"  {key} -> {where}/{exp_id}  市场={market}{flag}")
        results.append(manifest)
    return results


def _lookup_id(registry: dict[str, Any], key: str) -> str | None:
    for exp_id, entry in registry["entries"].items():
        if entry.get("registry_key") == key:
            return exp_id
    return None


def git_commit_and_push(*, push: bool) -> None:
    """只提交公开目录。私有目录靠 .gitignore 挡住,这里再显式限定一次范围。"""

    paths = [str(PUBLIC_DIR.relative_to(REPO))]
    subprocess.run(["git", "-C", str(REPO), "add", "--"] + paths, check=True)
    staged = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--cached", "--name-only", "--"] + paths,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not staged:
        print("没有新的公开实验产出，不提交。")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        f"archive: extract experiment evidence from log/ ({stamp})\n\n"
        "由 scripts/archive_experiment.py 自动生成。只含公开市场（cn）的核心证据；\n"
        "日股（jp）的产出留在 experiments_private/，不进这个公开仓库。"
    )
    subprocess.run(["git", "-C", str(REPO), "commit", "-m", message], check=True)
    print("已提交。")
    if push:
        subprocess.run(["git", "-C", str(REPO), "push"], check=True)
        print("已推送到 GitHub —— 到这一步实验记忆才真正不怕 Codespace 被删。")
    else:
        print(
            "⚠️ 只提交了、没推送。提交还在容器里，Codespace 删了照样没。"
            "加 --push 或手动 git push。"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--log-root", type=Path, default=REPO / "log")
    parser.add_argument("--log-dir", type=Path, help="只抽这一个 log 目录")
    parser.add_argument("--all", action="store_true", help="回填全部历史 log 目录")
    parser.add_argument("--commit", action="store_true", help="抽完 git commit（只含公开目录）")
    parser.add_argument("--push", action="store_true", help="commit 之后 git push")
    args = parser.parse_args()

    if args.log_dir:
        log_dirs = [args.log_dir if args.log_dir.is_absolute() else REPO / args.log_dir]
    else:
        if not args.log_root.is_dir():
            print(f"找不到 log 目录: {args.log_root}", file=sys.stderr)
            return 1
        candidates = sorted(path for path in args.log_root.iterdir() if path.is_dir())
        if not candidates:
            print("log/ 下面还没有任何实验目录。")
            return 0
        log_dirs = candidates if args.all else candidates[-1:]

    registry = load_registry()
    total = 0
    for log_dir in log_dirs:
        print(f"读 {log_dir.name}")
        total += len(archive_log_dir(log_dir, registry))
    save_registry(registry)
    write_index(registry)
    print(f"\n共抽出 {total} 个 loop。索引: {(PUBLIC_DIR / 'INDEX.md').relative_to(REPO)}")

    private = [
        exp_id for exp_id, entry in registry["entries"].items() if not entry.get("public")
    ]
    if private:
        print(
            f"\n有 {len(private)} 个私有市场实验在 experiments_private/（不进 Git）。"
            "\n拉回 Mac 的私有仓库（在 Mac 上执行，<CS> 换成 gh codespace list 里的名字）："
            "\n  gh codespace cp -e -r "
            "'remote:/workspaces/rdagent-qlib-cloud/experiments_private' "
            "~/jquants/rdagent_experiments -c <CS>"
        )

    if args.commit or args.push:
        git_commit_and_push(push=args.push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
