# 凡人自动发布接线核验

本流程沿 [凡人 Issue #2](https://github.com/CF-FE/fanren-work/issues/2) 独立核验工程采用。现任负责人批准的 `receipt_first` 和 `trace_first` 顺序不同，必验内容相同。协调员将工作流输出中的 `audit_order` 放入原生任务。两条路线均不适合时，Decision Service 的非执行候选 `needs-replan` 将任务交回原规划者。音频制作、整集放行及原有检查点各自沿原工作流维护。

## 固定输入和原生执行

在仓库外的私有目录保存检查点、负责人原生方案、发布安装输入、最小决策上下文、派发和原始成果。文件引用为 `{path, bytes, sha256}`，其中路径为绝对路径。运行输入包含以下字段。

- `project`、`task_id`、`unit_id`、`contact_ref`、`deliverable_kind` 来自原任务。
- `acceptor` 保存现任负责人的 name、session、pane、thread 和 generation。
- `owner_plan`、`runtime_inputs`、`decision_context` 及 `inputs` 中的补充证据以文件摘要固定。
- `source_files` 固定 `scripts/decision_publication_audit.py`、`scripts/episode_delivery.py` 和 `workflows/episode-delivery/definition.py` 的 SHA-256，工作流运行器同时绑定本流程的定义与 runner 摘要。
- `dispatch_binding_path` 和 `result_manifest_path` 是本单私有的唯一落点。
- `runtime_inputs` 绑定同一任务、单元、已复核的 Herdr consumer 发布位置和解释器、Decision Outcome Publisher 解释器，以及仅指向私有配置的 `config_ref`。私有配置不进入工作流或 Git。

新工作单元从仓库根目录读取 Mac 上已启用的项目绑定。命令生成私有运行输入，并输出可直接填入工作流 input 的 `runtime_inputs` 文件引用。协调员须使用原任务和工作单元的 ID。

```sh
python3 -B scripts/freeze_decision_publication_runtime.py --task "$TASK" --unit "$UNIT" --output "$RUNTIME_INPUTS"
```

项目绑定位于 `~/Library/Application Support/ProjectWorkflowTools/developer-inputs/fanren-work/current.json`。冻结文件保存固定发布路径。恢复已启动工作流时，使用检查点绑定的原输入及摘要。

从本项目根目录执行，下列命令使用协调员冻结的输入和路径。

```sh
FLOW=workflows/decision-publication-audit/workflow.py
python3 "$FLOW" --state "$STATE" start --task "$TASK" --input "$INPUT"
python3 scripts/decision_publication_audit.py --workflow "$FLOW" --state "$STATE" choose
python3 scripts/decision_publication_audit.py --workflow "$FLOW" --state "$STATE" status
```

原选择响应丢失时，对已冻结的 `request_id` 使用 `choose --request-id`。原协调员核对当前手递动作、宿主候选及空槽位，再用 `model-apply --binding "$BINDING" --selection "$SELECTION"` 在原生 Herdr 创建。两组及以上实际可用组合由原创建者确认后才做动态选型。只有一组时，原负责人方案允许沿原创建入口直接采用，并记录为单候选采用。本试点的动态模型分支在候选不足时保持待验证。启动回应未知时，沿同一绑定重入 `model-apply` 核原生线程。绑定原生派发后，使用 `model-reconcile --request-id … --rollout … --turn-id …` 对绑定的同一业务回合核对推荐、启动与实际生效配置。

唯一派发后，协调员用 `bind --record "$NATIVE_BINDING"` 核对派发回执和原生请求。绑定与交付清单沿用 [现有原生收件合同](../episode-delivery/README.md)。原生工作者冻结私有工程报告和索引，索引引用原生执行证据。回调和验收发生后产生的证明另存，原报告保持原摘要。

## 只读核验的原生证据交接

协调员给只读核验者的任务包包含原任务、单元和动作标记、冻结输入摘要、选定核验顺序及私有报告落点。任务包指定身份侧件的唯一绝对路径、提供者和限时检查点。真实业务回合开始后，由原协调员沿原生派发和回读提供该侧件，绑定任务、动作、执行者、槽位、thread、turn、派发回执及实际模型配置。

执行者先按已采用路线核对可读的固定原件，再对照本业务回合和身份侧件核验原生证据。侧件暂缺时保留该项待核，并继续有充分输入的只读检查。需操作 Herdr 的步骤由拥有真实 Herdr 入口和相应权限的角色完成身份检查。协调员在原端核查绑定、权限和实际配置，执行者依据冻结证据撰写报告。

协调员分别记录报告到达和工程必验项的执行状态。必验项为 `BLOCKED` 或 `UNKNOWN` 时，先按 `PARTIAL` 或 `BLOCKED` 归档原生快照并报告负责人。业务 `collect` 以原定必验项和交付条件为准。负责人依据同一报告版本决定质量与后继。

负责人释放后继单元时，为其绑定新的真实业务回合。验证两组工程事项、同回合身份和配置，并沿各自原任务关联报告及发布证据。首单的身份缺口、原报告和反馈各自沿原事件保存。

## 自动发布和继续对账

协调员用 `collect --record "$RESULT"` 导入原生终稿。绑定业务回合的原成果已核实时，提交工作流原收件并触发原结果发布。模型证据暂缺时保留实际交付和未确认配置，完整验收需先补同一业务回合的实际配置。实际配置与推荐不同时保留原回读及未采用结论。收件后原流程再次核验报告、引用工件及原输入，供负责人复核。已回收的首个结果质量为 `pending`。取得负责人的原生结论后，用 `decide --record "$OWNER_DECISION"` 导入同一成果摘要对应的限定验收，自动触发同一事件的质量修订。运行器在提交收件及验收前验证对应的原生证据和工件摘要。在负责人待验状态，工作流报告 `decision_evaluation=owner_only`，此时不向通用适配器开放自动评估；原运营请求仍可按 ID 只读对账。负责人回复应包含唯一的 `{task_id, unit_id, result_sha256, choice}` JSON 结论。验收只覆盖本工程单元。

只要反馈中有 `pending`、网络失败或回执尚未确认，原协调员沿[原生跟进待办](https://github.com/CF-FE/herdr-4-codexcloud/blob/main/docs/project-coordinator.md#native-followups)登记同任务及私有检查点。原观察器提醒后运行本入口的 `reconcile`，从已提交的原收件和负责人记录重建缺失的反馈并按原键补传。工作流 `FINISHED` 后仍执行这项检查。未回收时更新同一待办的复查时间，读回原事件的各修订且待回传清零后结单。程序可中断后从同检查点恢复，已提交但未推进的转换会继续到原下一步。对账不创建岗位或重新派发工作。
