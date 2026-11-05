# 项目工作流

负责人选择任务单元、输入与核收条件，程序执行明确步骤，成果沿原任务交给接手方。实时进展查 [Issue #2](https://github.com/CF-FE/fanren-work/issues/2) 与 [Project #5](https://github.com/orgs/CF-FE/projects/5?pane=issue&itemId=285760278)。

<!-- workflow-index:start -->
## 工作流索引

```mermaid
flowchart TD
    project["fanren-work workflows"]
    f0["batch02-metadata-handoff"]
    project --> f0
    f1["episode-delivery"]
    project --> f1
    domain["episode08-01-continuation"]
    project --> domain
    domain --> f1
```

总览连线表示项目包含这些流程，不表示流程间存在依赖。

- [batch02-metadata-handoff](#batch02-metadata-handoff)
- [episode-delivery](#episode-delivery)
- [episode08-01-continuation](episode08-01-continuation/README.md)
<!-- workflow-index:end -->

<!-- workflow:batch02-metadata-handoff:start -->
## batch02-metadata-handoff

[步骤图、数据接口与运行方式](batch02-metadata-handoff/README.md) · [项目共同入口](../README.md)

把已有 batch02 封存回执核成逐行指纹索引，再将真实输出交下一单元整理，最终交现任项目负责人核收本次元数据流程的采用范围。
<!-- workflow:batch02-metadata-handoff:end -->

集合入口及各流程源码由本项目独立维护。元数据流程保留 d7f5573 初始化基线；首集后续单元使用固定版本 36e23b4 初始化。新增或修改流程时，同步维护图与说明。


<!-- workflow:episode-delivery:start -->
## episode-delivery

```mermaid
flowchart TD
    n0["prepare — program: prepare"]
    n1[["native_handoff — handoff: ADOPT_EXISTING：沿prepare中的原生执行者与原投递回执收回本单元成果，禁止再次投递。只有完整原生结果及工件关联核清后才收件；阻塞只更新进度。"]]
    n2["verify_result — program: verify_result"]
    n3{"owner_acceptance — decision: 现任项目负责人是否接受本次明确范围的单元成果？原生决定只覆盖此单元，不代表整集放行。"}
    n4(["result: accepted"])
    n5(["result: revision_required"])
    n6(["result: held"])
    n0 --> n1
    n1 --> n2
    n2 --> n3
    n3 -->|"accept"| n4
    n3 -->|"revise"| n5
    n3 -->|"hold"| n6
```

- 用途与步骤：见上图；从 `prepare` 开始。
- 输入：`--input` JSON；字段由本流程的 program 操作定义。
- 输出：状态 JSON 的 `outputs`、`decisions`、`action` 和执行检查点。
- 职责与收件合同：[首集后续单元](episode-delivery/README.md)。原 Herdr 协调员承接原动作，现任项目负责人决定本单元成果；实时进展沿上方原 Issue / Project。
- 项目共同记忆：[阅读入口](../README.md)。
- 源码：[definition.py](episode-delivery/definition.py) · [workflow.py](episode-delivery/workflow.py)。

从项目根使用项目接续入口（输入、结果及检查点均在仓库外）：

```sh
python3 scripts/episode_delivery.py --state "$STATE" init --input "$INPUT"
python3 scripts/episode_delivery.py --state "$STATE" status
python3 scripts/episode_delivery.py --state "$STATE" collect --manifest "$RESULT"
python3 scripts/episode_delivery.py --state "$STATE" decide --record "$OWNER_DECISION"
```

程序处置完成和业务通过分列；`HELD`、`REVISION_REQUIRED` 均为未验收。新的实际制作沿负责人明确的依赖、范围和预算建立后继单元，保留原动作与成果引用。
<!-- workflow:episode-delivery:end -->

首集领域依赖和Q/R/P/C节点沿[领域定义](episode08-01-continuation/definition.json)及[运行接续说明](episode08-01-continuation/README.md)维护；实际单元在私有registry绑定固定源码与检查点，准备结果不代表整集验收。
