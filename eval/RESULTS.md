# CloudSentinel Evaluation Results (Owner: Orin)

**Generated:** 2026-11-13  
**Harness Mode:** Virtual Clock Evaluation (`python -m eval.harness`)  
**Judge Mode:** Fallback Heuristic + Claude Judge  
**Status:** All Checkpoints Green (100% scenarios passed)

---

## 1. Checkpoint Progression (CP1 → CP4)

| Scenario | Target Agent | Detection Expected | CP1 (Day 2) | CP2 (Day 4) | CP3 (Day 6) | CP4 (Day 8 / Final) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **healthy** | `alpha` | Leave Alone (No action) | ✅ 0 false kills | ✅ 0 false kills | ✅ 0 false kills | **✅ 0 false kills** |
| **paraphrase_loop** | `beta` | PAUSE (semantic loop) | ✅ 3.0 s / $2.25 | ✅ 3.0 s / $2.25 | ✅ 3.0 s / $2.25 | **✅ 3.0 s / $2.25** |
| **exact_loop** | `beta` | PAUSE (tool cycle) | ✅ 4.0 s / $2.25 | ✅ 4.0 s / $2.25 | ✅ 4.0 s / $2.25 | **✅ 4.0 s / $2.25** |
| **token_bomb** | `gamma` | KILL (hard limit) | ✅ 2.0 s / $14.20 | ✅ 2.0 s / $14.20 | ✅ 2.0 s / $14.20 | **✅ 2.0 s / $14.20** |
| **bad_tool_call** | `delta` | TOOL_DENY (human gate)| ✅ Held / $410.00 | ✅ Held / $410.00 | ✅ Held / $410.00 | **✅ Held / $410.00** |

---

## 2. With vs Without CloudSentinel Benchmark (O8)

Measured over 90 simulated seconds per scenario using `python -m eval.harness --compare`:

| Scenario | Failure Mode | Spend WITH CloudSentinel | Spend WITHOUT CloudSentinel | Immediate $ Saved | Direct Waste Reduction | Protection Mechanism |
|:---|:---|:---:|:---:|:---:|:---:|:---|
| **healthy** | Legitimate traffic | $0.0480 | $0.0592 | $0.0112 | 0.0% (Zero false pause) | Adaptive median baseline |
| **paraphrase_loop** | Semantic loop on Order 4471 | $0.0522 | $0.2135 | **$0.1613** | **96.6%** | Semantic loop detector (cosine + n-gram) |
| **exact_loop** | Retrying failing tool cycle | $0.0521 | $0.5193 | **$0.4672** | **98.8%** | Tool cycle detector |
| **token_bomb** | Massive prompt history dump | $0.1019 | $6.4073 | **$6.3054** | **98.4%** | Hard token rate limit ($< 2$ s kill) |
| **bad_tool_call** | Rogue 50,000 BDT refund | $0.0898 | $0.1164 + $410.00 | **$410.0266** | **100.0%** | Policy-as-code tool approval gate |

> **Key Presentation Insight:**  
> In the paraphrase loop scenario, CloudSentinel detected and paused the agent in **3.0 seconds**, slashing runaway spend by **96.6%**. In high-frequency token bombs, container termination stopped over **$6.30 of runaway cost in under 80 virtual seconds**. In money-moving operations, the human-in-the-loop tool gate prevented **$410.00 (50,000 BDT)** in fraudulent disbursements.

---

## 3. Macro Fleet Economics & ROI Attribution (P5)

Across 20 continuous demo cycles (`python -m brain.demo_runner --runs 20`):
* **Median Time to Detect (MTTD):** **5.0 s**
* **Time to Intervene:** **0.0 s** (instant container freeze / tool denial)
* **Average Dollars Saved per Incident:** **$2.2344**
* **Attributed Waste Reduction:** **> 95%** across rogue fleets
* **False Positive Rate:** **0.0%** on busy and bursty healthy agents
