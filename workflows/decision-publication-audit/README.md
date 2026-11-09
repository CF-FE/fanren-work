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

从本项目根目录执行，下列命令使用协调员冻结的输入和路径。

```sh
FLOW=workflows/decision-publication-audit/workflow.py
python3 "$FLOW" --state "$STATE" start --task "$TASK" --input "$INPUT"
python3 scripts/decision_publication_audit.py --workflow "$FLOW" --state "$STATE" choose
python3 scripts/decision_publication_audit.py --workflow "$FLOW" --state "$STATE" status
```

原选择响应丢失时，对已冻结的 `request_id` 使用 `choose --request-id`。原协调员核对当前手递动作、宿主候选及空槽位，再用 `model-apply --binding "$BINDING" --selection "$SELECTION"` 在原生 Herdr 创建。动态选型需要原创建者确认至少两组实际可用的组合。此试点的验收要求有实际动态选型，候选不足时原协调员回报原单。模型回读使用 `model-reconcile --request-id … --rollout … --turn-id …`，以原生回合核对推荐、启动与实际生效配置。

唯一派发后，协调员用 `bind --record "$NATIVE_BINDING"` 核对派发回执和原生请求。绑定与交付清单沿用 [现有原生收件合同](../episode-delivery/README.md)。原生工作者冻结私有工程报告和索引，索引引用原生执行证据。回调和验收发生后产生的证明另存，原报告保持原摘要。

## 自动发布和继续对账

协调员用 `collect --record "$RESULT"` 导入原生终稿，提交工作流原收件并触发原结果发布。已回收的首个结果质量为 `pending`。取得负责人的原生结论后，用 `decide --record "$OWNER_DECISION"` 导入同一成果摘要对应的限定验收，自动触发同一事件的质量修订。负责人回复应包含唯一的 `{task_id, unit_id, result_sha256, choice}` JSON 结论。验收只覆盖本工程单元。

只要反馈中有 `pending`、网络失败或回执尚未确认，原协调员沿[原生跟进待办](https://github.com/CF-FE/herdr-4-codexcloud/blob/main/docs/project-coordinator.md#native-followups)登记同任务及私有检查点。原观察器提醒后运行本入口的 `reconcile`，从已提交的原收件和负责人记录重建缺失的反馈并按原键补传。工作流 `FINISHED` 后仍执行这项检查。未回收时更新同一待办的复查时间，读回原事件的各修订且待回传清零后结单。程序可中断后从同检查点恢复。对账不创建岗位或重新派发工作。
