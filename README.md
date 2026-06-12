# haskell-tester

黑盒测试 agent + 元方法蒸馏工具链。

给一个黑盒 binary + README, agent 自动分类 → 加载对应 playbook → LLM-驱动 probe-hypothesize-verify → 输出 belief.md。

## 当前状态 (V3)

| 组件 | 状态 | 性能 |
|---|---|---|
| 数据蒸馏 (Python, 一次性) | ✅ | 199 PB task → 8 archetype + 8 playbook |
| Rule classifier | ✅ | 62% on 199 ground truth |
| LLM classifier (Deepseek + few-shot + decision tree) | ✅ | LLM fallback 69%, Hybrid 总 75% on 20-task clean eval |
| Inner loop (probe → hypothesize → verify + 反幻觉) | ✅ | dedup + stdin 喂输入 + grounded findings 校验 |
| belief.md 输出 | ✅ | 真实 fact, 含 round 历史 |
| 单 binary 交付 (embedFile) | ✅ | 78 MB, 含 8 playbook + taxonomy + few-shot |

## 真实数据

`htester agent /tmp/pb_clean_test` (jq):

- 强制 ByteExactGolden archetype: density = belief/README = **1.73x**
- 走默认 CliSurface 分类: density = **1.09~1.26x**

belief 净增项: error_grammar, exit_codes, 真行为 fact (`.a → 1`, `-n 1+1 → 2`)

## 目录

```
haskell-tester/
├── haskell-tester.cabal
├── app/Main.hs                # CLI 入口
├── src/HaskellTester/
│   ├── Types.hs               # Archetype ADT, TaskSummary, Belief
│   ├── Classifier/
│   │   ├── Rule.hs            # 10 条阈值规则 (62%)
│   │   ├── LLM.hs             # Deepseek + few-shot + 决策树 (69%)
│   │   └── Hybrid.hs          # 规则 fast-path + LLM 兜底 (75%)
│   ├── Playbook.hs            # 加载 markdown playbook
│   ├── Probe/Shell.hs         # 跑 --help/--version/file/nm + stdin
│   ├── Summary.hs             # 构 sparse TaskSummary
│   ├── LLM/Deepseek.hs        # HTTP -> deepseek-chat
│   ├── InnerLoop.hs           # probe → hypothesize → verify 主循环
│   └── EmbeddedData.hs        # TH embedFile 嵌入 data/
├── data/                      # build 时被 TH 嵌入 binary
│   ├── archetype_taxonomy.json
│   ├── fewshot_examples.json
│   └── playbooks/*.md (8 份)
├── scripts/                   # Python dev 工具 (一次性跑)
│   ├── parse_graders.py
│   ├── summarize_features.py
│   ├── merge_archetypes.py
│   ├── prepare_playbook_inputs.py
│   ├── classifier.py + classifier_llm.py  # prototype, 已被 Haskell 替代
│   ├── gen_fewshot.py         # 生成 data/fewshot_examples.json
│   └── info_density.py        # Belief vs README density 对比
└── distill_out/               # Python 工具产出 (200 task features, 不进 binary)
```

## 用法

```bash
# 构建
cabal build all

# CLI 子命令
htester agent <task_dir>                         # 全链路: classify → playbook → inner loop → belief.md
htester agent --archetype ByteExactGolden <dir>  # 强制 archetype, 跳过分类
htester classify <summary.json>                  # 规则分类 (无 LLM)
htester classify-hybrid <summary.json>           # 规则+LLM 兜底
htester validate-hybrid [limit]                  # 跑 ground truth 看准确率 (剥 few-shot)
htester probe <task_dir>                         # 只 probe + 分类, 不进 inner loop
htester taxonomy                                 # 列 8 archetype

# 必需环境变量
export DEEPSEEK_API_KEY=sk-...
```

## 数据流

```
[dev-time, 一次性 Python]
  200 grader → parse → summarize → 20 subagent batch → 8 archetype
                                                    → 8 playbook
                                                    → fewshot_examples.json

[build-time, Haskell TH]
  data/ → embedFile → 78 MB 单 binary

[runtime, Haskell]
  新任务 → buildRuntimeSummary → classify (hybrid)
                              → loadEmbeddedPlaybook
                              → InnerLoop (Deepseek)
                              → belief.md
```

## 反作弊边界

| 进 binary | 不进 binary |
|---|---|
| `archetype_taxonomy.json` (元方法) | `task_archetypes.jsonl` (ground truth, dev only) |
| `playbooks/*.md` (策略模板) | `summaries.jsonl` (grader 派生数据) |
| `fewshot_examples.json` (剥 task_id 的抽象 shape) | `features.all.jsonl` (raw assertion 抽取) |

agent runtime 拿不到 grader 原文, 不能反查 task_id → archetype。

## 未解决

- LLM 分类剩 25% 边界 case (fx/walk/json-tui 等)——加 chain-of-thought 可能再 +5pp
- Inner loop reason 自由文本仍可能幻觉(findings 已 grounded, reason 还没)
- 多标签 (primary + secondary archetype) 没做, 单标签到此天花板
- 没在 7 个其他 archetype 上跑过真实 density (只验证了 CliSurface + ByteExact)
