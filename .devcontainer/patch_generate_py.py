#!/usr/bin/env python3
"""
修复 RD-Agent 官方自带的 generate.py 里一个真实 bug(不是我们的配置/数据问题):

    rdagent/scenarios/qlib/experiment/factor_data_template/generate.py

原代码逻辑:
    1. 先算 2008-12-29 至今【全历史】的股票池,取前 100 只股票代码
    2. 再用这前 100 只代码去筛选一份限定在 2018-2019 窗口的数据

如果这 100 只里有股票在 2018-2019 这段完全没交易(比如更早退市、
代码被复用),第 2 步的 .loc[] 会直接抛 KeyError 崩溃。
其他用户在官方仓库也报过同一个问题,官方目前没有修复:
    https://github.com/microsoft/RD-Agent/issues/619
    https://github.com/microsoft/RD-Agent/issues/1002

修法:改成"先按 2018-2019 窗口取数,再从这份已经限定窗口的数据里选前
100 只",这样选出来的股票保证在这个窗口里一定有数据,不改变原本
"选 100 只股票做调试子集"的设计意图,只是把选股池和取数窗口对齐。

幂等:如果已经打过补丁,或者 RD-Agent 版本更新后源码结构变了,
脚本会原样跳过并打印提示,不会破坏文件。
"""
import sysconfig
from pathlib import Path

REL_PATH = "rdagent/scenarios/qlib/experiment/factor_data_template/generate.py"


def find_target() -> Path:
    site_packages = Path(sysconfig.get_paths()["purelib"])
    p = site_packages / REL_PATH
    if not p.exists():
        raise SystemExit(f"找不到目标文件: {p}")
    return p


OLD = '''data = (
    (
        D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
        .swaplevel()
        .sort_index()
    )
    .swaplevel()
    .loc[data.reset_index()["instrument"].unique()[:100]]
    .swaplevel()
    .sort_index()
)'''

NEW = '''_debug_raw = (
    D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
    .swaplevel()
    .sort_index()
)
# PATCHED (rdagent-qlib-cloud, 2026-08-16): 原代码从 2008 年至今全历史股票池选前100只,
# 再拿去筛 2018-2019 窗口数据,若这100只里有股票在该窗口无交易会 KeyError 崩溃。
# 改为直接从已限定 2018-2019 窗口的数据里选前100只,保证一定存在。
data = (
    _debug_raw
    .swaplevel()
    .loc[_debug_raw.reset_index()["instrument"].unique()[:100]]
    .swaplevel()
    .sort_index()
)'''


def main() -> None:
    path = find_target()
    content = path.read_text()
    if NEW in content:
        print(f"SKIP: {path} 已经打过补丁")
        return
    if OLD not in content:
        print(f"WARNING: {path} 里没找到预期的原始代码块,可能 RD-Agent 版本已更新、"
              f"这个 bug 已被官方修复,或者代码结构变了。跳过打补丁,不动这个文件。")
        return
    path.write_text(content.replace(OLD, NEW))
    print(f"PATCHED: {path}")


if __name__ == "__main__":
    main()
