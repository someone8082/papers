# 第八阶段抽样器工程验收

2026-11-06。状态 STAGE8_SAMPLER_EXECUTION_VERIFIED。

foreground run b8b9f019c280420a8b4e5df69f9d89f8 由官方 Codex Goal 接管，控制器 finish 执行一次实验，failed_cases 从 24 降至 0，保留提交 6667d44e8546011d10afd20412b61fa0fe7028db，状态 complete。唯一改动 src/sampler.py，工作树干净。

实现使用整数后缀动态规划计数、先不选再选的字典序解码、单次 randrange(total) 抽样和前后缀组合计数得到的 Fraction 边际概率。输入统一验证，excluded 的一次性迭代器先物化；合法无解 count 返回 0、边际全 0，decode 和 sample 拒绝无解空间。

## 实测证据

- autoresearch-results/logs/0001-verify.json：24/24，failed_cases=0，退出 0，0.531 秒。
- autoresearch-results/logs/0001-guard.json：18/18，退出 0，0.234 秒。
- autoresearch-results/events.jsonl：baseline、keep iteration、complete，指标 24→0。
- 补充只读检查：对 40 个夹具实例使用 itertools.product((0,1), repeat=n) 穷举字典序合法向量，总共 881 个合法秩，与 decode 逐项相等；全部实例的逐组边际与穷举 Fraction 相等。
- 补充只读检查：真实组空间中，持续使用 random.Random(20261106) 抽样 1000 次，与另一个同种子 RNG 的 randrange(total) 流经 decode 得到的行逐项一致；种子 20261107 的序列不同。excluded 使用一次性迭代器仍通过；空空间及 target=0 边界通过。

固定装置保持原字节。补充检查未进入固定指标，未改用例或重新测量定义。

## 两处装置解释

SAMPLER-CONTRACT.md 中“秩等于把 b0 当最高位的二进制整数”数值上不成立。准确含义是合法指示向量按该二进制整数排序后的位置。例：sizes=[1,1], target=1 时，rank=0 对应向量 (0,1)，该向量的二进制整数为 1。第 14 例以及实际实现遵循合法向量的排序序号，故无需改变冻结验收器；本文作为解释补充。

第 22 例每次列表推导都新建 random.Random(11)，覆盖的是重复初始化后首个抽样的一致性。上述额外 1000 行检查覆盖了连续 RNG 状态推进的重放。未来驱动脚本应每臂仅建立一次 RNG。

## 下一步

建立并冻结四臂驱动协议、角色组键映射、代码与输入摘要；先落盘抽样清单及摘要，再读取归档分数评价。当前完成度只覆盖工程接口；四臂各 10000 次抽样与新四态尚未执行。
