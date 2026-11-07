# 抽样器验收装置说明（第八阶段第二轮）

2026-11-06。对应契约 `SAMPLER-CONTRACT.md`。第一轮装置（`CONTRACT.md`、`verify_metric.py`、`guard.py`、`PINNED.json`、`fixtures/`、`tools/`）未改动，仍由 `guard.py` 保护。

## 两个入口

| 文件 | 作用 |
|---|---|
| `verify_sampler.py` | 24 例固定验收，输出 `{"failed_cases": N, "total_cases": 24}` |
| `guard_sampler.py` | 18 项保护检查，退出 0 通过 |

运行：

```
E:/yingyong/an/envs/iad-week1/python.exe -B verify_sampler.py
E:/yingyong/an/envs/iad-week1/python.exe -B guard_sampler.py
```

`verify_sampler.py` 用时约 1.1 s，`guard_sampler.py` 约 0.5 s，均不写盘。

## 参考值从哪来

小实例的计数与入选概率由验收器现场用 `2^n` 穷举重算，期望值不落盘。三个大数无法穷举，作为外部锚写入夹具，来源是第八阶段裁定记录的独立稀疏多项式复算（`scores_read=false`）：

| 量 | 值 |
|---|---:|
| G0 整组恰取 32 张 | 1672489259948266974 |
| G1 固定 18 张组后 | 1672464128242708178 |
| I0 逐图任取 32 张 | 8661069563374624785150762 |

夹具生成器 `sampler_tools/gen_sampler_fixtures.py` 用记忆化递归独立复算这三个数，与裁定记录不符即终止；本次生成三个数逐位一致。

## 基线可测性与 0 可达性

| 状态 | failed_cases |
|---|---:|
| `src/sampler.py` 接口桩（已提交基线） | 24 |
| 参考实现临时放入 `src/sampler.py` | 0 |
| 复原桩 | 24 |

参考实现放在 `.scratch/`（已忽略），不入库。第 23 例会启动子进程加载真实的 `src/sampler.py` 并加审计钩子，因此它测的是提交的实现而不是被替换的模块；这也是把参考实现临时放进 `src/` 才能测得 0 的原因。

## 十组负向对照

`.scratch/selftest_mutations.py` 逐条破坏契约，确认用例不是装饰：

| 破坏 | 失败用例 |
|---|---|
| 秩顺序改为先选分支 | 14, 15, 17, 18, 19, 23 |
| 接受布尔秩 | 15, 23 |
| 计数忽略 excluded | 10, 12, 19, 23 |
| 解码忽略 excluded | 15, 17, 18, 19, 23 |
| 逐组抛硬币抽样 | 21, 23 |
| 入选概率返回 float | 23, 24 |
| 接受重复 excluded | 6, 23 |
| 接受 target 大于总和 | 4, 23 |
| 接受零组大小 | 1, 23 |
| 解码输出不排序 | 14, 16, 18, 19, 20, 23 |

10 组全部被对应用例捕获。第 23 例几乎在所有破坏下都失败，因为它是唯一在子进程里做真实抽样的用例。

## 守卫覆盖

1. `PINNED-SAMPLER.json` 自身摘要（内嵌 `e509250f…`）。
2. 抽样器四件：契约、验收器、夹具、夹具生成器。
3. 第一轮七件：`CONTRACT.md`、`verify_metric.py`、`guard.py`、`PINNED.json`、`fixtures/case24-cases.json`、`tools/gen_fixtures.py`、`README.md`。
4. 用例数 24、夹具实例 40 的三处一致。
5. 第四至七阶段归档，经 `PINNED.json` 登记的 4 份清单与 41 个文件传递核对（`PINNED.json` 自身摘要已由第 3 项锁定）。
6. `git` 保护路径干净；`src/` 下最多只有 `src/sampler.py` 处于未提交状态。

自指摘要同样不可实现：`guard_sampler.py` 由第 6 项覆盖，成规模的协同改写由提交号与控制器 Git 溯源覆盖。这条限制写在文件头。

## 运行方式

新运行 scope 为 `src/sampler.py`，指标 `failed_cases` 目标 0，前台模式。第一轮运行 `f29dca4878b14a7082089737bbd9b82c` 已 complete，不重开、不改历史指标。
