#!/usr/bin/env python3
"""研究环境体检：跑实验之前挡住「配置错位」这类会静默产生假数字的问题。

被两个地方调用：
- `scripts/health_check.sh` 的第二段（第一段仍然是原来的 docker / rdagent / LLM 检查）
- `scripts/run_one_loop.sh` 和 `scripts/run_frozen_test.sh` 的开跑前关卡

实际的检查逻辑都在 `validation/checks.py`，和 Validation Gate 的 Gate 1
**共用同一份实现**，避免两边漂移出现「体检说没问题、Gate 说有问题」。

用法：
    python scripts/research_check.py                          # 只体检
    python scripts/research_check.py --require-mode research   # 并强制 research 模式
    python scripts/research_check.py --json                    # 机器可读输出

任何一项 FAIL → 退出码 1，并打印 ❌ STOP。调用方（run_one_loop.sh 用 set -e）
会因此直接停下，不会带着错配的配置去跑实验。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validation.checks import FAIL, OK, SKIP, WARN, run_environment_checks  # noqa: E402

SYMBOL = {OK: "✅", WARN: "⚠️ ", FAIL: "❌", SKIP: "➖"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-mode",
        choices=("research", "frozen"),
        help="强制当前必须是这个模式，否则 STOP",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    checks, environment = run_environment_checks(require_mode=args.require_mode)
    failed = [check for check in checks if check.failed]

    if args.json:
        print(
            json.dumps(
                {
                    "status": "FAIL" if failed else "PASS",
                    "environment": environment,
                    "checks": [
                        {
                            "name": check.name,
                            "status": check.status,
                            "detail": check.detail,
                            "data": check.data,
                        }
                        for check in checks
                    ],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 1 if failed else 0

    if environment:
        print("=== 当前研究配置 ===")
        rows = [
            ("模式", environment.get("mode")),
            ("市场", f"{environment.get('market')}（{environment.get('display_name')}）"),
            ("provider_uri", environment.get("provider_uri")),
            ("qlib market", environment.get("qlib_market")),
            ("benchmark", environment.get("benchmark")),
            ("涨跌停模拟", environment.get("limit_threshold") or "不模拟"),
        ]
        provider = environment.get("provider_facts") or {}
        rows += [
            (
                "数据起止",
                f"{provider.get('calendar_start')} .. {provider.get('calendar_end')}"
                f"（{provider.get('calendar_days')} 个交易日）",
            ),
            ("股票数量", provider.get("instrument_count")),
        ]
        splits = [
            ("Train", environment.get("train")),
            ("Validation", environment.get("validation")),
            ("Research OOS", environment.get("research_oos")),
            ("Frozen Test", environment.get("frozen_test")),
        ]
        for label, value in rows:
            print(f"  {label:14s} : {value}")
        for label, value in splits:
            marker = ""
            if value and environment.get("active_test_segment") == [
                str(value[0]),
                str(value[1]),
            ]:
                marker = "   ← 当前生效的 test 段"
            print(f"  {label:14s} : {value[0]} .. {value[1]}{marker}")
        print(f"  {'frozen_test_used':14s} : {environment.get('frozen_test_used')}")

        risks = {key: value for key, value in (environment.get("known_risks") or {}).items()
                 if isinstance(value, bool)}
        if risks:
            print("\n=== 已知可信性缺陷（随实验结果一起记录，不是忘了填）===")
            for key, value in risks.items():
                flag = "⚠️  是" if (value is False and "false" not in key) else ""
                print(f"  {key:32s} = {value}")

    print("\n=== 检查项 ===")
    for check in checks:
        print(f"{SYMBOL.get(check.status, '?')} {check.name}")
        if check.status != OK or check.detail:
            print(f"     {check.detail}")

    print()
    if failed:
        print(f"❌ STOP：{len(failed)} 项检查失败，不要在这个状态下跑实验。")
        for check in failed:
            print(f"   - {check.name}")
        return 1
    warned = [check for check in checks if check.status == WARN]
    print(f"✅ 研究环境检查通过（{len(checks)} 项，其中 {len(warned)} 项警告）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
