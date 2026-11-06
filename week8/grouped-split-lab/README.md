# Grouped split feasibility lab

Independent repository for the stage 8 grouping and whole-group partition
feasibility component. The development boundary, acceptance cases and
autoresearch launch conditions are in [CONTRACT.md](CONTRACT.md); the built
harness, its 24 cases and the measured baseline are in [HARNESS.md](HARNESS.md).

State: harness fixed, baseline measured at `failed_cases = 24` against an
interface stub, guard passing on 15 checks. No experiment loop is initialized
yet.

Measurement (from the repository root):

```text
E:/yingyong/an/envs/iad-week1/python.exe -B verify_metric.py
E:/yingyong/an/envs/iad-week1/python.exe -B guard.py
```
