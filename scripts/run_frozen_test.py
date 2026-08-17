#!/usr/bin/env python3
"""在 Frozen Test 区间上评一个 candidate —— 唯一能碰 Frozen Test 的入口。

## 为什么必须是独立入口

原来的循环是：RD-Agent 提因子 → Qlib 在 test 区间算 → **RD-Agent 看到 test
结果** → 据此改因子 → 再算。几十轮之后 test 区间已经被间接训练过，
它报出来的数字不再是样本外表现，而是「被优化过的样本内表现」。

所以现在数据切成四段（validation/config.yaml）：

    Train + Validation + Research OOS   RD-Agent 可以反复使用
    Frozen Test                          RD-Agent 看不到，只有本脚本能进

## 本脚本保证了什么

1. 跑之前强制 `research_check.py --require-mode frozen`，配置必须真的处于
   frozen 模式（yaml 里 test 段 == frozen_test，取数窗口放宽到 frozen 末尾）。
2. **不启动 RD-Agent**。只调 Qlib 的 `qrun`。RD-Agent 的进程、log、session
   全程不参与，所以它不可能通过任何渠道拿到这里的结果。
3. 结果只写进 `experiments/<EXP>/frozen_test/`，**不写** RD-Agent 的 `log/`、
   不写它的 session 状态、不产生任何会被下一轮当反馈读到的文件。
4. 跑完自动把配置切回 research 模式，避免忘了切、下一轮普通 loop 误踩 frozen。

## 一旦 Frozen Test 被用于调参数、改因子、选择因子，它就不再是 Frozen Test

这句话不是免责声明，是操作纪律。本脚本每次运行都会在结果里写
`frozen_test_used: true` 和运行次数，就是为了让「这段被用过几次」这件事
留下痕迹 —— 用过一次是最终校验，用过五次就是又一个被训练过的 test 集。

## 用法

    bash scripts/run_frozen_test.sh EXP-0004
"""

from __future__ import annotations

import argparse
import glob
import json
import pickle
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_REL = "rdagent/scenarios/qlib/experiment/factor_template"


def load_manifest(exp_id: str) -> tuple[Path, dict[str, Any]]:
    for root in (REPO / "experiments", REPO / "experiments_private"):
        manifest = root / exp_id / "MANIFEST.json"
        if manifest.exists():
            return manifest.parent, json.loads(manifest.read_text(encoding="utf-8"))
    raise SystemExit(
        f"找不到 {exp_id} 的 MANIFEST.json。\n"
        "先跑 `python scripts/archive_experiment.py --all` 把 log/ 抽成 experiments/，"
        "然后用 experiments/INDEX.md 里的 EXP 编号。"
    )


def find_workspace(manifest: dict[str, Any]) -> Path:
    """定位当初产出这个 candidate 的 Qlib 工作目录。

    刻意复用**原始工作目录**而不是重建一个：里面的
    ``combined_factors_df.parquet`` 就是那一轮真正喂给 Qlib 的因子值。
    重新算一遍等于引入「重算结果和当初不一致」的风险，
    而 frozen 测试的意义正是评「当初那个东西」。
    """

    loop_dir = REPO / manifest["source_log_dir"]
    candidates = sorted(glob.glob(str(loop_dir / "running" / "runner result" / "*" / "*.pkl")))
    if not candidates:
        raise SystemExit(
            f"{manifest['experiment_id']} 的日志里没有 runner result —— 这一轮没跑到回测，"
            "不是一个可以做 frozen 测试的 candidate。"
        )
    with open(candidates[-1], "rb") as handle:
        runner = pickle.load(handle)
    workspace = Path(str(getattr(getattr(runner, "experiment_workspace", None), "workspace_path", "")))
    if not workspace.is_dir():
        raise SystemExit(
            f"记录里的 Qlib 工作目录 {workspace} 已经不存在了。\n"
            "git_ignore_folder/ 是运行时产物，被 cleanup_disk.sh 或 Codespace 重建清掉了。\n"
            "没有当初的因子值就没法做 frozen 测试 —— 不要用重算的值假装是当初那个，\n"
            "重跑一遍 research loop 产生新的 candidate 再测。"
        )
    parquet = workspace / "combined_factors_df.parquet"
    if not parquet.exists():
        raise SystemExit(f"{workspace} 里没有 combined_factors_df.parquet，无法复现该 candidate。")
    return workspace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="EXP-NNNN（见 experiments/INDEX.md）")
    parser.add_argument("--keep-frozen-mode", action="store_true",
                        help="跑完不切回 research 模式（不建议，只用于排查）")
    args = parser.parse_args()

    exp_dir, manifest = load_manifest(args.candidate)
    market = manifest.get("market")
    if market not in ("cn", "jp"):
        raise SystemExit(f"{args.candidate} 的市场是 {market!r}，无法确定要用哪套 frozen 切分。")

    print(f"==> candidate: {args.candidate}（市场 {market}，来源 {manifest['source_log_dir']}）")
    if manifest.get("status") != "complete":
        print(f"    ⚠️  这个 candidate 的存档状态是 {manifest.get('status')}，"
              f"缺件 {manifest.get('missing_artifacts')}")

    workspace = find_workspace(manifest)
    print(f"==> 复用当初的 Qlib 工作目录: {workspace}")

    print("\n==> [1/4] 切到 frozen 模式")
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "apply_market_config.py"),
         "--market", market, "--mode", "frozen"],
        check=True,
    )

    try:
        print("\n==> [2/4] 研究环境体检（强制 frozen 模式）")
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / "research_check.py"),
             "--require-mode", "frozen"],
            check=True,
        )

        # 把 frozen 版配置拷进工作目录，覆盖当初那份 research 配置。
        # 只有 test 段和取数窗口不同，train/valid 完全一致 —— 评的是同一个
        # 模型在一段没被看过的时间上的表现，不是另一个模型。
        import sysconfig

        template = Path(sysconfig.get_paths()["purelib"]) / TEMPLATE_REL
        for name in ("conf_baseline.yaml", "conf_combined_factors.yaml"):
            shutil.copy(template / name, workspace / name)

        output = exp_dir / "frozen_test"
        output.mkdir(parents=True, exist_ok=True)

        print("\n==> [3/4] 跑 Qlib（只跑 qrun，完全不启动 RD-Agent）")
        log_path = output / "qrun_stdout.log"
        with log_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                ["bash", "-lc",
                 "source /opt/conda/etc/profile.d/conda.sh && conda activate rdagent4qlib && "
                 f"cd {workspace} && qrun conf_combined_factors.yaml"],
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        print(f"    qrun 退出码 {completed.returncode}，日志 {log_path.relative_to(REPO)}")

        print("\n==> [4/4] 记录结果（标记 frozen_test_used=true）")
        state = json.loads((REPO / "validation" / "current_state.json").read_text(encoding="utf-8"))
        previous = 0
        record_path = output / "frozen_test.json"
        if record_path.exists():
            previous = json.loads(record_path.read_text(encoding="utf-8")).get("times_used", 0)
        record = {
            "candidate": args.candidate,
            "market": market,
            "frozen_test_used": True,
            "times_used": previous + 1,
            "frozen_test_segment": state["frozen_test"],
            "train": state["train"],
            "validation": state["validation"],
            "qrun_returncode": completed.returncode,
            "qrun_log": str(log_path.relative_to(REPO)),
            "workspace": str(workspace),
            "known_risks": state.get("known_risks", {}),
            "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "discipline_note": (
                "一旦 Frozen Test 被用于调参数、改因子、选择因子，它就不再是 "
                "Frozen Test。times_used 就是为了让「这段被用过几次」留下痕迹："
                "用过 1 次是最终校验，用过 5 次说明它已经变成又一个被训练过的 test 集。"
            ),
            "not_fed_back_note": (
                "本次结果只写在 experiments/ 下，没有写进 RD-Agent 的 log/ 或 session 状态，"
                "因此不会被下一轮当作反馈读到。"
            ),
        }
        if previous:
            print(f"    ⚠️  这段 Frozen Test 之前已经被用过 {previous} 次。"
                  f"这是第 {previous + 1} 次 —— 它的「未被污染」性质正在流失。")
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"    → {record_path.relative_to(REPO)}")
        if completed.returncode != 0:
            print("\n❌ qrun 失败，frozen 测试没有产出可用结论。原始日志见上面那个文件，"
                  "不要把失败当成「没通过」——先看清是环境问题还是策略问题。")
            return 1
        return 0
    finally:
        if not args.keep_frozen_mode:
            print("\n==> 切回 research 模式（避免下一轮普通 loop 误踩 frozen）")
            subprocess.run(
                [sys.executable, str(REPO / "scripts" / "apply_market_config.py"),
                 "--market", market, "--mode", "research"],
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
