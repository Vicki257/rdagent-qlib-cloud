#!/usr/bin/env python3
"""
修复 RD-Agent 官方代码里的一个真实缺陷(2026-08-16/17 实测踩到):

    改"用哪个市场的数据"(provider_uri)和改"AI 自己以为在研究什么"
    (显示在网页报告 Config 表格里、也讲给 AI 听的说明文字)是两件
    完全分开的事——改了前者不会自动改后者,容易出现"用的是日股数据,
    AI 却以为自己在研究 2008-2020 年的中国 CSI300"这种错位。
    这份补丁把后者从写死的字符串,改成可以从环境变量读取的模板,
    默认值不变(还是 CSI300),不影响原有行为。

打这个补丁后,配合 scripts/switch_market.sh 一起用,才能保证
"实际用的数据"和"AI/报告里说的数据"永远一致。

幂等:已经打过补丁会自动跳过。
"""
import sysconfig
from pathlib import Path

SCENARIO_DIR = "rdagent/scenarios/qlib/experiment"


def find(rel: str) -> Path:
    site_packages = Path(sysconfig.get_paths()["purelib"])
    p = site_packages / SCENARIO_DIR / rel
    if not p.exists():
        raise SystemExit(f"找不到目标文件: {p}")
    return p


def patch_prompts_yaml() -> None:
    path = find("prompts.yaml")
    content = path.read_text()

    old = '''qlib_factor_experiment_setting: |-
  | Dataset 📊 | Model 🤖    | Factors 🌟       | Data Split  🧮                                   |
  |---------|----------|---------------|-------------------------------------------------|
  | CSI300  | LGBModel | Alpha158 Plus | Train: 2008-01-01 to 2014-12-31 <br> Valid: 2015-01-01 to 2016-12-31 <br> Test &nbsp;: 2017-01-01 to 2020-08-01 |'''

    new = '''qlib_factor_experiment_setting: |-
  | Dataset 📊 | Model 🤖    | Factors 🌟       | Data Split  🧮                                   |
  |---------|----------|---------------|-------------------------------------------------|
  | {{ market_name | default("CSI300", true) }}  | LGBModel | Alpha158 Plus | Train: {{ train_range | default("2008-01-01 to 2014-12-31", true) }} <br> Valid: {{ valid_range | default("2015-01-01 to 2016-12-31", true) }} <br> Test &nbsp;: {{ test_range | default("2017-01-01 to 2020-08-01", true) }} |'''

    if new in content:
        print(f"SKIP: {path} 已经打过补丁")
        return
    if old not in content:
        print(f"WARNING: {path} 里没找到预期的原始代码块,可能版本已更新。跳过。")
        return
    path.write_text(content.replace(old, new))
    print(f"PATCHED: {path}")


def patch_factor_experiment_py() -> None:
    path = find("factor_experiment.py")
    content = path.read_text()

    old_import = '''from copy import deepcopy
from pathlib import Path

from rdagent.components.coder.factor_coder.config import get_factor_env'''
    new_import = '''import os
from copy import deepcopy
from pathlib import Path

from rdagent.components.coder.factor_coder.config import get_factor_env'''

    old_render = '''        self._experiment_setting = deepcopy(T(".prompts:qlib_factor_experiment_setting").r())'''
    new_render = '''        # PATCHED (rdagent-qlib-cloud, 2026-08-17): 从环境变量读取市场信息,
        # 没设就用原来的默认值(CSI300)。切换市场用 scripts/switch_market.sh。
        self._experiment_setting = deepcopy(
            T(".prompts:qlib_factor_experiment_setting").r(
                market_name=os.environ.get("RD_AGENT_MARKET_NAME"),
                train_range=os.environ.get("RD_AGENT_TRAIN_RANGE"),
                valid_range=os.environ.get("RD_AGENT_VALID_RANGE"),
                test_range=os.environ.get("RD_AGENT_TEST_RANGE"),
            )
        )'''

    if new_render in content:
        print(f"SKIP: {path} 已经打过补丁")
        return
    if old_import not in content or old_render not in content:
        print(f"WARNING: {path} 里没找到预期的原始代码块,可能版本已更新。跳过。")
        return

    content = content.replace(old_import, new_import, 1)
    content = content.replace(old_render, new_render, 1)
    path.write_text(content)
    print(f"PATCHED: {path}")


if __name__ == "__main__":
    patch_prompts_yaml()
    patch_factor_experiment_py()
