---
name: qwen-tts-skill
description: 为凡人演义说书二创项目维护外置角色声线与旁白配置，用本地离线 Qwen 生成提议样片或已授权集数，并核验真实音频、字幕及试听证据。
---

# 凡人演义 Qwen 说书

只处理凡人项目的Qwen执行适配。维护位置为 Library `/内容创作/凡人说书二创项目/04_风格Skill/qwen-tts-skill`。当前可制作哪部作品／篇章、哪些集、在哪个环境执行，由该任务唯一接手入口及实际用户授权决定；本skill不签发制作许可，也不要求操作Mac。下文未带篇章前缀的01—17、v5—v7迁移、旧Mac readiness和旧配置版本均为历史实现／验证案例，不是当前待执行清单。生产前核当集原生入口、冻结配置及实际环境，不把旧命令模板原样运行到新篇。新小说须另建适配，不能直接套本项目人物和声音。

## 输入与声线

角色 JSON 是独立、外置的真源：读取 Library 中最新正式 `schema_version=1.1.0` 配置及其版本、哈希，不把附件 ID、旧版本副本或完整角色表写死进技能代码。用 `load_config(config_path, models_path)` 同时验证角色配置和本地模型登记；具体字段见 [schema.md](references/schema.md)。保留 canonical_id、别名、性别、原著外观年龄证据与表演年龄的区别，不自行补造证据或人物。

角色归属与角色声线分别维护。完整 `speaker-annotations.json` 是说话范围的唯一真源，纯口播及原 performance 保持文字真源；先读上下文核定完整话轮及旁白，再在每个范围内做技术切分。单句、句号、字幕换行及原父段切换不自动换人；跨父段续讲保留同一个 `dialogue_turn_id`，明确的旁白插话单独标为 `narrator_aside`，随后必须恢复同角色同话轮。另一角色发言或普通 narration 结束原话轮，已结束的 turn 不复活；孤立或尾部 aside 拒绝。所有父段和所有字符都须显式标注，包括旁白；缺标、重叠、未知身份或改字后的旧 offset 均拒绝，不把剩余文字默认交给 NARRATOR。使用 Python Unicode 码点的零起点半开区间，不使用字节或 UTF-16 索引。具体契约见 [schema.md](references/schema.md)。

人读 `【角色／开始】…【角色／结束】` 视图只由权威标注和纯正文生成，禁止送入 TTS，也不另维护一份手改标签稿。朗读 `text` 只从核定原文范围精确切片；`annotation_span_id`、`dialogue_turn_id`、标签、语义证据及场景指令不拼入正文或字幕，不靠正则剥标签继续制作。原文真实含有的括号、姓名和标点照原样保留。结构/hash 校验只证明绑定和完整性；独立、绑定当前原文与标注的语义审查收据记录完整话轮审查，不等于声音批准、机器发音或人耳试听通过。

语义收据支持两个严格分支。01 已有 `schema_version:1` 迁移收据及最终成果保留，非空 changes/narrator_decisions、实测有限音频 cue 和旧单元计数不放宽。02–17 的初次完整说话审查可用 `schema_version:2`、`review_mode:"initial_full_speaker_review"`，按 annotation 顺序逐项审查全部 span；明确 `comparison_scope:"no_audio_migration_comparison"`、无 unresolved 且 `production_authorized:false`，不能说该集没有旧音频或已经试听通过。v2 绑定实际 baseline 文件的 raw hash；baseline 按原 performance 父段一整段投影，仅保留原 speaker 标签，新的 canonical 归属只来自 annotation。直接读取真实原 JSON 数组或对象的 `segments`，不展平为伪正式稿。对象集号可为精确字符串或整数 1–17 与同一两位集号匹配；spoken_sha256 可缺省，存在时仍严格绑定 raw TXT，五源实际字节与完整投影门继续执行。正式 02 已核实摘要算法；原 16／17 的整数无摘要格式无需改稿适配；每次完整图、收据和当前配置仍须实际绑定，具体字段见 [schema.md](references/schema.md)。

声音仍通过角色 ID 和正式配置解析。旧 `speaker` 不得覆盖角色；同名身份待核、内嵌引号 `REVIEW_REQUIRED` 等路由不能自动成为已分配对白。已知 reserve canonical 可以完成归属标注，但没有可用声线时明确阻断渲染，不能用旁白代读。固定声线身份；逐句情绪从该角色的 `emotion_overrides` 选择。CustomVoice 角色空 instruct 模板须结合 `emotion_key` 与该句 `scene_intent` 生成非空指令，也可提交绑定台词哈希的 `performance`，或精确同文复用 `tested_scene_examples`；记录实际 `applied_scene_instruct`。情绪表演不能改 speaker、language 或 DSP，不能把一条示例的情境套给所有台词。

正式 `voice_contract_refs` 指定 Base 固定参考时，先按 canonical 读取并核验外置契约，旧 CustomVoice 声线、同文示例、generation 和 seed 都只作历史。通过重复的 `--voice-contract <JSON>` 提供契约，本地模型 registry 的 `references` 按 Library ID 绑定参考路径和批准哈希；缺失或不符即停。Base 使用 `create_voice_clone_prompt` → `generate_voice_clone`，不发送 speaker/instruct/emotion；保留该句场景意图作验收资料，明确不能宣称独立情绪控制已经应用。选中声音身份不等于参考 WAV 单独听审或全部句子发音通过。

旁白当前声线以外置正式选声契约为准。历史 `Uncle_Fu / Chinese` 的低稳柔和、稍快及后期 `tempo_multiplier=1.08`、`pitch_shift_semitones=-1` 保留为历史，不覆盖新原创 Base B。`NARRATOR_Base_B` 与韩立可指向同一物理 Base 模型，但参考、prompt、采样参数和种子独立；旁白 B 用显式种子 `20261030`，韩立保持 `20262002`。新 B 使用中性 DSP：0 半音、1.0 倍速、0 dB，不继承历史变速、移调或试听响度增益。这些旁白要求也不能继承为所有角色的低稳、平调限制。Qwen API 参数与 DSP 数值分层，具体能力和限制见 [model-workflow.md](references/model-workflow.md)。

## 执行

先做配置校验与计划，再执行所需模式。入口为 `python3 scripts/fanren_qwen_tts.py`，命令及完整参数见 `--help` 和 [runtime-contract.md](references/runtime-contract.md)：

- `validate-config --config <正式角色JSON> --models <本地模型登记JSON>`：结构通过不代表声线或生产已批准。
- `validate-annotations --config ... --models ... --source <完整来源清单> --annotations <权威标注JSON> --source-file <纯口播原文件> --performance-file <原表演稿JSON>`：核实际原文件字节 hash、完整角色范围和身份，读取独立语义证据时加 `--review-receipt <复核与来源JSON>`；不加载模型。
- `compile-annotations` 使用相同输入，另加 `--max-chars 100 --output-dir <新审稿目录>`：生成纯正文切片清单、人读起止标注和校验报告，不生成音频。100 字是软目标，优先完整句/分句边界；不可分意群不超过两倍目标，极长无合法边界则 `review_required`，纯标点只在同 span 内附到正文。
- `plan --config ... --models ... --source <冻结清单> --mode sample|production`：核对全部角色、原文来源、路由和授权。已审标注入口另成组提供 `--annotation-baseline-source --annotations --source-file --performance-file --review-receipt` 五个实际文件；必须全有或全无。plan 只读收集每条具体阻塞，不生成音频。
- `--scene-controls <单一已审场景JSON>`：可用于 reviewed `plan`/`run`/`assemble`；保持原五输入与活动四 hash 不变，另由正式 cast 的 `active_episode_scene_controls` 绑定该文件原始字节。每条 entry 核完整 annotation span，再给其全部技术 child 派生受控 `emotion_key/scene_intent` 副本，不改 source 或身份/声音/DSP/model/generation/批准。具体契约见 [production-adapter-contract.md](references/production-adapter-contract.md)。
- `run --config ... --models ... --source ... --mode ... --backend mock|qwen --cache-dir ... --state-dir ... --output-dir ...`：所有本项目运行共用同一 state-dir 锁与暂停标记；真实后端显式传 `--model-lock .../season20/qwen_production/model_resource.lock` 与 ASR/样片任务共用；新成果使用新目录。
- `assemble --source ... --annotation-baseline-source ... --annotations ... --source-file ... --performance-file ... --review-receipt ... --native-runs <本地计划/清单/cache_root登记JSON> --state-dir ... --output-dir <新候选目录>`：只核验并组装当前有效 production 原生整片段，不加载 TTS/ASR；全集动态覆盖且每段恰好一次，发布仍标记 `candidate_pending_qa`。
- `pause --state-dir ...`：当前句安全结束后暂停，拼接前再次检查；`resume --state-dir ...` 是旧入口的显式暂停恢复用法；实际会话断连／once运行不能套用为盲重跑，先核当前入口是否支持该模式，并按下文精确缺失恢复。
- `validate-audio --wav ... --srt ... --source-text ...`：可另传真实 `--asr`、独立 `--human-review` 和新的 `--report` 路径。

已审执行适配器位于 `execution.py`：五个实际文件、完整 compiled source、独立语义 receipt 及正式 `active_episode_annotations` 四个 raw hash 一起建立 `ReviewedAnnotationContext`。带 context 的 `prepare_segment` 以完整图决定身份，旧 partial routes 归档，不把语义 span 当场景指令；现有声音、行动短句 override 与生产批准门保留。`run` 接同一组五文件，先核完整图和全部选中请求，再访问 backend/cache；不能删 annotation 字段或换旧 source 绕过。新 Base NARRATOR 默认要求完整活动绑定；未迁移且未要求 annotation 的旧 CustomVoice 才保留原入口。作者 DEV4 开发候选已加入活动四 hash，Mac 对实际文件的配置校验及带语义收据编译通过；未改正式 cast v9 或批准状态，编译通过不代表声线、scene 或生产已经 ready。

v2 仍共用五个实际输入，整份 annotation 和语义 review 在选段前验证；当前配置 raw hash、voice 与生产批准门均不因跨集放宽。云端部署先固定本次 source-manifest 和代码 hash；Mac 不做 TTS，未完成真实模型/ASR/听审的范围继续明确待测。

需要只生成部分请求时，向适用的 `plan` 或 `run` 重复传 `--segment-id <ID>`，仍先验证完整 source、全部父段、完整已审说话图及整份场景 sidecar。技术段数随核定范围和切分策略变化；旧 94 段、19 变化／75 保留只是历史基线，不能硬编码到新计划。subset 输出明确标为 `selected_segments_not_episode`；保留全文、选段文本、选择哈希和逐条缓存路径。v5 历史恢复方案因旧生产资产随云端丢失，曾要求当时 01 图的 101 段全部新 render，按声线分别运行 Base/CustomVoice 后核动态全集；该记录保留，不要求重做现在已有的 01 最终输出。新集不用试听 MP3 冒充旧 PCM 或新 cache hit。组装只从显式本地 `cache_root/key` 取 raw/processed/cache.json，核当前代码、快照、有效请求、缓存键、实际 hash 和 PCM；不读 manifest 的云端路径，不按字符比例裁 WAV 或按位置 zip 新旧段。最终 SRT 用实测采样位置，双 ASR 和独立听审另做。

历史“上舟”四资产及编辑 recipe 留存为证据，不自动继承。新定向再生仅可由已审 scene entry 的精确 `regenerate_override_id` 及 sealed context 绑定现有源文/角色/完整范围/行动规则；旧 seed、参考候选和剪切采样不进入新请求。其余声线、场景和生产授权门仍执行，未提供此 exact context 的公共 run 保持旧 action guard。不得自行写场景或修改批准来放行。

样片模式允许配置提议，不得写成用户已批准。正式生产许可、机器测试、听审和角色状态分别记录；历史第 01 集单集授权不自动批准声线、全剧或新的标注/旁白修订。当前候选若明确记录 `not_requested_for_current_annotation_and_narrator_revision`，先完成审稿交接并保留该阻塞，不把旧授权改写为本次 production ready。v5 历史授权快照曾要求 05–17 集暂停；当时用户授权云端恢复全17集并保留01已有输出；该历史授权不决定当前篇章范围，现任务按其实际授权、冻结配置与生产状态执行。不因测试或绕过批准门擅自改 `production_enabled`、audition/status 字段。

冻结 source 原文及历史，逐段或子段必须来自精确字符切片并保留来源和哈希，不改字词、标点或称谓来让校验通过。原音频只读，新产物不得覆盖历史。缓存覆盖文本、角色有效配置、模型、指令、DSP、参考音频与逐字稿哈希；相关变化须失效。一个批次复用模型和 clone prompt。失败即停止受影响运行、记录原因并保持其失败／未知状态；独立且不依赖该失败的工作可继续。不得跳过缺失段发布成品，恢复按下文精确缺失流程。

句内保持连贯，句号保留模型自然短停。只在句末拼接处测量两侧静音之和：不足约 250 ms 才补差额至约 300 ms；不机械给所有句号或角色切换加静音。真实音频、实测 frame 时间轴、整句 SRT、导入 ASR 与人耳听审的区别见 [subtitle-validation.md](references/subtitle-validation.md)。禁止按字数捏造词级时码。

## 验证与边界

默认离线，已有依赖和完整本地模型不足时明确报告阻塞，不下载大模型、运行参考仓库代码、开放监听或申请新权限。自创声线的官方 VoiceDesign → 选定参考音频/逐字稿 → Base 复用 clone prompt 路线是需模型与试听的提议能力；不能声称已部署或已听审。Mock 是标记过的测试音，不是真实语音。

v7 最小格式兼容回归 359 项通过，0 失败／错误／跳过；v6 历史回归为 353 项。新核心供生产方独立复核后用于后续集，当前 12／13 冻结 v6 不自动替换，01–11 成品不动；历史 v5 的 328 项、v4 的 278 项测试与 101 段编译证据保留。正式 02 原对象的 72 parents 与最终 annotation/receipt v2 已完成实际五源绑定，126 span／35 turn／39 对白范围编译为动态 126 技术块，5326 码点原文不变；25 条真实输入负例全部拒绝。收据绑定不能代替语义真伪、人耳试听或生产就绪判断，完整计划继续核唯一作者的最新 cast/scene。v5 当时的作者 cast v11 与 scene v0 实际形状已核验，v11 缺 scene raw hash 活动绑定而被严格 context 拒绝；当时仅测试内存中的绑定提议用于验证接口，不写回正式配置或扩大批准。该 readiness 记录是历史快照，最新状态必须按唯一作者当前正式配置及实际文件核验，不从 v11 推导。真实新集 TTS、production 音频、双 ASR 与听审待云端执行。Mac 不部署、不安装、不下载模型；readiness 在工作区 `delivery/mac-runtime-readiness.md/json`：当时检查范围内无 Qwen 环境或 Base/CustomVoice 权重，双 ASR 亦未就绪；16 GiB 内存、约 120 GiB 可用磁盘只是资源快照，不证明模型可运行。

按 [tests/validation-report.md](tests/validation-report.md) 报告实际验证范围；单元测试、模拟后端、真实模型短测、自动 ASR 和人工试听分别报告。参考上游行为或更新适配时读 [upstream-review.md](references/upstream-review.md)，保留许可署名，避免重新引入段级 speaker 覆盖、逐段重载、失败跳过和拼接边界错位。


## 局部响度检查入口 2026年10月10日

真实原音产出后、组装后和最终编码交付前，必须按[局部响度与表演动态规范](../fanren-yanyi-storytelling/references/说书制作局部响度与表演动态规范.md)执行，不以调用validate-audio或ASR一致视为已经完成：
1. 绑定真实源SHA、角色／话轮及采样边界；原音池看同情境相对电平，组装后检查角色切换和话轮内部短语，短起句不可被整段均值豁免
2. 收到具体时间点先查对应台词与前后完整话轮，逐短语／活动窗追查raw、processed及可得后期层；缺失层不猜原因。区分弱声、静音、音色清晰度和有意表演，告警需情境裁定，不自动拉平
3. 修复限获准干净源副本；句内包络以真实低能间隙定边界，不能按SRT毫秒硬剪或切断发音。固定时轴重建后跑完整既定链、仅一次B；对照从最终成品同窗截取，不另行归一化
4. 验收记录话轮与句内两层局部结果、整轨峰值、MP3完整解码、帧数／SRT字节、gain计划及已改／未改区域回归。技术通过不替用户试听；确认撤回立即停止promotion并封存旧采用草稿，重新确认须绑定确切候选版本

本入口只列必做步骤，测量口径、候选阈值和TY07两轮复盘统一见专项正文，不复制参数。声音身份、raw原音、当前批次配置与模型锁保持。此为文档执行要求，现有命令不会因此自动实施局部检测、增益包络或放行判断；未改运行中共享代码，也不让新规范自动批准TTS、改EQ或重做旧成品。


## 同角色声音一致性检查（2026-10-22）

真实原音产出、最终语境验收及收到“同角色不一致”反馈时，执行[专项第14节](../fanren-yanyi-storytelling/references/说书制作局部响度与表演动态规范.md#voice-consistency)：先核身份／实物路由，再用同角色锚作轻量对照，区分身份、合理表演和后期影响。同seed不保证同声，真实reference绑定只证明输入；ASR、hash和响度不代替听觉判断。等响仅作诊断，还须真实电平上下文验收。

沿说书08号既有双层状态记录输入／技术／实际听觉范围，缺可验证听审即待验证，不签PASS。制作方负责补验，不因缺听审冻结无关授权制作，也不靠披露关闭用户已报问题或默认逐句请用户确认。已确认问题仅修受影响完整话轮／处理层，保原声和失败对照、B仅一次。此次为规范源修订，不是运行中自动门、媒体或冻结配置升级。

## 连续制作的最小恢复与证据继承

- TTS、ASR、样片与实际需要模型的prepare遵守共享模型资源锁；按真实代码资源依赖分类，不能凭名称认定prepare不加载模型。启动下一集长批前，先核上一集剩余prepare、组装及后期的既有锁依赖并优先收尾。独立无模型检查可并行；现有程序要求双锁的步骤仍守双锁，不能换锁／删锁或只凭文档绕过。锁冲突先核持有者与终态
- 恢复按真实边界分三类：已完整落盘的单元保留并核身份／hash／QA；API已开始但完成未知的单元，先只读核原进程终态、实际落盘和调用账，确定真正缺集；原进程仍可能活动时不得重复启动。旧工具会话查不到，不等于原进程已停止；结合当前可观察进程／进程组、锁持有者、落盘完整性、调用账和环境身份排除重复执行。旧终态可永久保留UNKNOWN，在已排除仍运行且精确缺失集合可证时，用独立恢复记录补缺，不要求伪造旧exit0；经日志、代码路径与零输出检查确认在模型加载前退出的任务，待锁释放并完成必要独立核验后，仅恢复受影响阶段。访问拒绝不得换路绕过。没有证据不得声称“未调用”，也不把执行断连写成网络授权取消。不得整批重抽、补造旧RESULT或抹去历史尝试；具体重试次数和许可沿当次范围，不新增普遍逐次用户审批
- 新角色先查当前权威去重，再按固定候选提供完整原句／话轮试听。若正式音频与已接受样片整文件SHA一致，可沿用该片段的实际接受记录，仍完成正式来源、角色、覆盖与所需技术QA；不能从同声线、同文本、相同seed推定同音频，也不能推出其他句子或最终后期听感已通过
- 双ASR是定位线索：先区分专名／近同音／规范化差异、弱起或停顿识别、实质增漏词疑点，再核冻结原文、真实音频与已接受片段。已能由证据关闭的差异不反复送听；仍影响内容判断的疑点合并成最少完整语境试听。禁止把转写差异自动判成错读、自动重抽、剪去未知发声或改字幕掩盖问题
- 同字节样片进入正式池须有明确采用记录，绑定实际样片请求、参数、原音、技术QA与用户接受；保留历史sample模式／原ID，用单独映射连接正式声音节点，不伪造一次production调用。声音节点、剧情实体和场景声音载体分开：同声／同preset／同seed不证明人物同一或必不相同，实体未明须保留未明。
- 延用显式原生路由、完整话轮图和当集冻结版本；新增角色只变更必要权威记录及依赖，历史音频按原身份保留来源桥。共享代码、活动配置、模型和锁不因文档更新自动改变

以上是执行说明，未新增程序门、自动重试器或ASR裁决器。局部响度、一次B、精确采样时间轴和元数据不改音频的验证仍按原专项执行。



### 连续制作增补：逐批恢复、容量与最小证据（2026-10-24）

逐批完成后，按实际依赖保存该批原音、必要输入与调用记录、技术QA、选用映射及未决项。保存、完整回读与可恢复性分别记录；实际完整GET后核整包大小/SHA及成员清单与内容校验，才声明该范围云端可恢复。引用现有已核同字节资产，不重复装箱；本次重新取得的字节仍须校验。先保原始成果，再恢复真正缺失层；未知终态保留UNKNOWN，不为补证重跑成功模型调用。

容量以当前文件系统可用量、真实分配块、当前帧数／源数／映射及输出计划核算，包含同时驻留媒体、解码、打包、完整回读和约定余量；不直接沿用上一集数字，也不把压缩后大小或理论下界当准入。必要分卷时保独立可核清单、精确覆盖与恢复关系；不降低现行门、不迁往未批准存储。只增加能改变决策的检查，不复制全量报告或重复审已闭合层。

字幕原词粒度不对应时，执行[字幕证据的完整短语组映射补充](references/subtitle-validation.md#phrase-group-mapping)；一次B中间源保护沿[19号恢复边界补充](../fanren-yanyi-storytelling/references/19-postprocessing-and-tianyuan-b.md#once-b-recovery)。这是后续执行说明，不改当前冻结脚本、输入、活动状态或许可，不部署自动恢复／容量／听审程序，也不授权新制作或清理。


## 执行环境故障分层入口（2026-10-15）

遇执行器启动、下载、安装、导入或模型恢复失败时，先执行[现行环境恢复规范](development/凡人说书_20261008环境恢复结论与最小恢复材料_v1.md#现行故障分层与受控恢复规范2026-10-15)，按需读[本次误判复盘](references/20261015_环境启动误判复盘.md)。该规范是唯一故障流程真源，不从一条启动错误推导整个环境不可恢复。

先分清启动故障与明确权限拒绝：拒绝不得换路绕过，禁止路径不得探测或修权；基础设施启动失败则在原授权范围内检查受支持的默认方式，以最小无副作用检查缩小故障范围。核原进程终态和共享锁后仅恢复受影响阶段，保留原日志，不盲重试或无依据等待。HEAD、下载校验、安装、加载、合成与QA逐级报告，环境通过不等于生产放行。

本入口只维护后续恢复方法，不改任何在产批次的冻结输入、声学参数、执行合同、生产批准、代码或锁，也不要求重跑已验阶段。上文“默认离线、不下载大模型”仍约束未授权的新下载；用户已批准的原固定官方工件恢复按既有授权与现行恢复规范执行，不因此引入新模型、来源或权限。
