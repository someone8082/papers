# Papers — 研究成果精选归档

本仓库同步 AeBAD-S 异常检测研究的部分报告、分组证据和已验收计算工具。2026-11-06 首批快照；完整本地归档仍为事实来源。文件保持原字节，摘要见 [SNAPSHOT-MANIFEST.json](SNAPSHOT-MANIFEST.json)。

## 阅读顺序

1. [第五阶段：两池候选阈值覆盖诊断](week5/week5-report-route-c-v1.md)
2. [第六阶段：view 候选扩充，G=3](week6/week6-report-route-b-v5.md)
3. [第七阶段：background 独立规则实验](week7/week7-report-background-v2.md)
4. [第八阶段：分组与抽样裁定](week8/stage8-grouped-design-decision-2026-11-06.md) — 当前设计入口，包含对早期分组记录解释的更正。
5. [分组原始证据](week8/acceptance/stage8-grouping-2026-11-06/grouping-evidence.json)及[独立复算](week8/acceptance/stage8-grouping-2026-11-06/decision-check.json)。

## 工具及复现范围

[grouped-split-lab](week8/grouped-split-lab/README.md) 从原独立仓库提交 abc474f2025ae0aab4066b3b7492ecc92fe5c207 导出，不含其 .git。工程验收可在该目录运行 `python -B verify_metric.py`，仅需 Python 标准库；固定 24 例应全部通过。

[控制器事件](week8/grouped-split-lab/autoresearch-results/events.jsonl)与日志是只读历史快照，不应把本 GitHub 仓库当成原 autoresearch 运行仓库继续执行控制器。

`guard.py` 核查原本地仓库及阶段 5–7 完整归档。精选快照不含这些外部数据，故不能在此声称守卫可完整重放；历史 15/15 记录保留。[图像分组脚本](week8/grouping_evidence.py)也需自行取得原数据与角色表。

未同步原始图像、掩码、模型权重、vendor、凭证及完整评价产物。历史报告中通向未随快照发布的本地产物的链接可能不可用；这不表示产物不存在，也不表示已发布完整复现包。本文不改变数据集或第三方软件原有许可。

## 结果边界

现有分数上的重划分属于条件于有限池的事后敏感性分析。dHash 连通分量只隔离指定代理关系，不能认证采集批次或物理独立性。抽样器与第八阶段新四态尚未执行；工程验收达标不等于研究假设已验证。
