# Papers — 研究成果精选归档

本仓库同步 AeBAD-S 异常检测研究的部分报告、分组证据和已验收计算工具。2026-11-06 首批快照；完整本地归档仍为事实来源。文件保持原字节，摘要见 [SNAPSHOT-MANIFEST.json](SNAPSHOT-MANIFEST.json)。

## 阅读顺序

1. [第五阶段：两池候选阈值覆盖诊断](week5/week5-report-route-c-v1.md)
2. [第六阶段：view 候选扩充，G=3](week6/week6-report-route-b-v5.md)
3. [第七阶段：background 独立规则实验](week7/week7-report-background-v2.md)
4. [第八阶段：结项记录](week8/stage8-closure-2026-11-07.md)与[最终报告 v2](week8/week8-report-grouped-split-v2.md) — 状态 STAGE8_GROUPED_SPLIT_CLOSED_VERIFIED。
5. [结项核查清单](week8/acceptance/stage8-closure-2026-11-07/closure-check.json)、[修正版评价](week8/acceptance/stage8-arms-v2-2026-11-07/eval-v2.json)和[精确审计](week8/acceptance/stage8-arms-2026-11-06/exact-audit-v1.json)。

2026-11-07 更新包含第八阶段登记的 81 项产物及结项清单自身，共 82 项，保留早期报告、原评价及修正链。四臂共 40000 行清单和修正版逐行评价均已收录。最终科学读数引用报告 v2；原驱动的 C* 分支及正文 v1 的已更正口径仅供历史追踪。

## 工具及复现范围

[grouped-split-lab](week8/grouped-split-lab/README.md) 从原独立仓库提交 6667d44e8546011d10afd20412b61fa0fe7028db 导出，不含其 .git。工程验收可在该目录分别运行 `python -B verify_metric.py`、`python -B verify_sampler.py`，仅需 Python 标准库；两套固定 24 例均应全部通过。

[控制器事件](week8/grouped-split-lab/autoresearch-results/events.jsonl)与日志是只读历史快照，不应把本 GitHub 仓库当成原 autoresearch 运行仓库继续执行控制器。

`guard.py` 与 `guard_sampler.py` 核查原本地仓库及阶段 5–7 完整归档。精选快照不含这些外部数据，故不能在此声称守卫可完整重放；15/15、18/18 的历史记录保留。[图像分组脚本](week8/grouping_evidence.py)及四臂评价脚本也需原数据、角色表或既有分数文件。

未同步原始图像、掩码、模型权重、vendor、凭证及阶段 3–7 完整评价产物。历史报告中通向未随快照发布的本地产物的链接可能不可用；这不表示产物不存在，也不表示已发布完整复现包。本文不改变数据集或第三方软件原有许可。

## 结果边界

现有分数上的重划分属于条件于有限池的事后敏感性分析。dHash 连通分量只隔离指定代理关系，不能认证采集批次或物理独立性。第八阶段已完成工程验收、四臂分析和两条精确计数路径，结论边界见最终报告与结项记录。
