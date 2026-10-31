# Windows 小显存 Qwen-TTS：环境创建与 INT4 首样流程

核验截至 **2026-10-31**。推荐路线：**隔离环境 → 官方 1.7B Base → bitsandbytes NF4 运行时量化 → 受控短样 → 分层检查**。已有成功层直接复用证据，不为读教程重装或重测。

> **21 码点、4.08 秒**首样已获用户试听认可；后续四个短片共 **140 码点、32.16 秒**，已通过独立文件身份、完整解码与技术检查，新片内容、声线和听感仍未验。以下首样资源数字保留其样本归属，不外推长音频或长期稳定性。示例路径、文本及声音身份均为占位；命令未在本次文档整理中执行。

## 1. 前置条件

- 先确认本次任务许可、输入版本、GPU 独占和资源交还；沿用当前资源锁、审批、Job 与预算，不能另开裸 worker 抢 GPU。参考音频须有使用权及必要同意。
- 本案例实测组合如下；**不是最低配置或通用速度承诺**：

| 项目 | 成功路线版本 / 条件（缺项明示） |
| --- | --- |
| 系统 / 显卡 | Windows 10 Pro 22H2，19045.6466；RTX 2050 Laptop，4 GB |
| 驱动 | NVIDIA 621.01 / Windows 32.0.16.2101，WHQL，设备问题码 0；用户手动安装后已核实际加载 |
| VC++ x64 运行库 | **精确版本未核**：成功 pip 清单不覆盖系统 CRT，不用早期失败快照代替；新机须核官方运行库与实际 DLL |
| Python | 64 位 CPython **3.11.15**，本案例为 uv 托管分发 |
| Torch / 音频 | torch、torchaudio **2.11.0+cu128**；构建 runtime 为 CUDA **12.8** |
| 上层依赖 | qwen-tts **0.1.1**；Transformers **4.57.3**；Accelerate **1.12.0** |
| 量化 | bitsandbytes **0.50.2**，实际加载 `libbitsandbytes_cuda128.dll` |
| 模型 I/O 与数值库 | NumPy **2.2.6**；tokenizers **0.22.2**；safetensors **0.8.0**；huggingface-hub **0.36.2** |
| 神经 codec | 第 3 节同一官方 Base revision 内的 **12 Hz speech_tokenizer**，BF16；没有独立 pip 版本号 |
| 文件音频 / 重采样 | SoundFile **0.13.1**；soxr **1.1.0**；librosa **0.11.0**；SciPy **1.17.1**；底层 libsndfile DLL 版本**未核** |
| pip SoX / 外部工具 | Python 包 **sox 1.5.0**；外部 SoX 在该执行路径未检出（`NO_SOX`），不是固定 PCM 路线前置；soxr 不是 SoX |
| 图像 / UI 依赖 | Pillow **12.3.0**；Gradio **6.16.0**；保留已知风险版本，边界见第 2 节，不用于图片/PDF 或公网服务 |
| 安装工具 | runtime 内 pip **26.2.2** / setuptools **80.9.0**；与附件所列独立 SoX 构建工具分开 |
| 外部音频工具 | **Gyan.FFmpeg / ffprobe 8.1.2** 已核版本、绝对路径调用、临时音频转码及完整解码；它独立于 92 包 Python 锁，固定 PCM 路线无需为此重装。TorchCodec 不在成功 92 包清单中 |
| 运行余量 | 原执行合同要求入场可用 RAM ≥20 GiB、卷可用 ≥20 GiB；不能把 4 GB 显存当作只需少量系统内存 |

- 在获准检查时用 `nvidia-smi` 核加载版本；驱动显示的 CUDA 能力上限**不等于** Torch runtime 或已安装 Toolkit。使用 cu128 wheel 不必据此另装整套 CUDA Toolkit。
- 驱动仅从 [NVIDIA 官方入口](https://www.nvidia.com/Download/index.aspx)取得；1114 类问题按需核 [Microsoft VC++ x64 运行库](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。不要把升级驱动当成 meta tensor 的既定修法。
- **兼容边界：**[bnb 0.50.2 标签 README 的支持矩阵](https://github.com/bitsandbytes-foundation/bitsandbytes/blob/0.50.2/README.md#accelerator-support)列 Windows 11 / Server 2022+，该表自注为开发状态说明；本例 Win10 短片成功不等于上游承诺支持 Win10。

**成功标志：**解释器、驱动和包版本有记录；无安装/重启冲突，旧活动/UNKNOWN 任务已对账并排除并发或重复执行风险；未知退出码仍可保留 UNKNOWN。

### 模型与精度怎么选（只比较 Base）

官方 [0.6B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) 与 [1.7B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) 均支持参考音频快速克隆、10 种语言及流式生成；官方未列出二者能力类别上的差异。**各路线的最低显存/RAM：官方未给定，需实测。**CustomVoice 的预置音色、VoiceDesign 的文本音色设计不属于本表，也不据此给 Base 添加 `instruct` 能力。

| 模型 / 精度 | 功能差异 | GPU 显存与 RAM 要求 | offload 方式 | 适用场景 | 验证等级 |
| --- | --- | --- | --- | --- | --- |
| 0.6B Base / BF16 | 同类 Base 克隆能力；规模较小 | 官方未给定，需实测；本项目无显存/RAM 实测 | 官方示例为 CUDA BF16；CPU offload 未验 | 较小规模的非量化候选 | 官方功能说明；本机未验 |
| 0.6B Base / INT8 | 同一 Base 运行时量化；效果差异未验 | 官方未给定，需实测；无本机峰值 | GPU-only / CPU offload 均未验 | 小显存评估候选，不直接采用 | 仅方案，未验 |
| 0.6B Base / INT4（NF4） | 同一 Base 运行时量化；效果差异未验 | 官方未给定，需实测；无本机峰值 | GPU-only / CPU offload 均未验，须另核适配 | 更低权重存储的候选，不保证总显存或质量 | 仅方案，未验 |
| 1.7B Base / BF16 | 同类 Base 克隆能力；不量化 | 官方未给定，需实测；本机 4 GB + CPU offload 曾加载，无成功生成峰值 | `device_map="auto"`，GPU + CPU | 非量化基线候选，须补生成验证 | 本机仅加载已证，非成功生成 |
| 1.7B Base / INT8 | 同一 Base 运行时量化；codec 保持浮点 | 本机 4 GB：reserved 峰 **2,927,624,192 B**，codec 仍 OOM；RAM 门槛未给定，需实测 | GPU-only，无 CPU/disk offload；codec/敏感层 BF16 | 本机不能作为已可用生成路线 | 本机量化有效；生成失败 |
| 1.7B Base / INT4（NF4） | 同一 Base 运行时量化；codec 保持浮点 | 本机 4 GB 首样：reserved 峰 **2,529,165,312 B ≈2.36 GiB**；Job private 峰约 **9.76 GiB**；最低 RAM 未给定，需实测 | GPU-only，无 CPU/disk offload；codec/敏感层 BF16 | 本机可复用的已证短样配置；长段另验 | 本机 **4.08 秒首样成功**；后续四短片技术检查通过，非长期连续/长音频稳定 |

量化均指**官方 Base 加载时的运行时路线，不是官方原生 INT8/INT4 checkpoint**；兼容边界沿用上表实际版本及第 2 节官方来源，不能从 bnb 支持某硬件推定 0.6B 集成已通过。reserved 仅为 Torch allocator 峰值，Job private 峰不是系统 RAM 最低值；20 GiB 入场线是项目合同余量。权重算术估计不含 codec、缓存、激活等开销，不能充当总峰值或可运行证据。**0.6B 只作选型比较，不切换当前生产模型。**

## 2. 官方依赖与隔离环境

### 建目录和 venv（以下为 PowerShell）

先准备已核准的 Python 3.11.15 x64；可参考 [uv 官方 Python 管理说明](https://docs.astral.sh/uv/guides/install-python/)。将 `$PY311` 换成实际绝对路径。目标若已存在、大小写碰撞或父链有 junction/symlink，**先停止，不覆盖**。

```powershell
$R = "D:/audio-project"
$PY311 = "D:/tools/python311/python.exe" # 占位：替换为已核准解释器
if (Test-Path -LiteralPath $R) { throw "目标已存在，请先核对，不覆盖" }
New-Item -ItemType Directory -Path $R | Out-Null
"tools", "downloads", "models", "inputs", "outputs", "run-empty" | ForEach-Object {
    New-Item -ItemType Directory -Path "$R/$_" | Out-Null
}
& $PY311 -I -B -m venv "$R/.venv-int4"
$P = "$R/.venv-int4/Scripts/python.exe"
Set-Location "$R/run-empty"
```

脚本放 `tools/`；每个下载/解包件用自己的新空目录，不能在下载目录运行解释器。读取外来文件的 Python 使用 `-I`，避免同名模块注入；不要复制 venv 到新路径冒充重建。

### 锁定、安装、非 GPU 基础检查

默认重建成功 **INT4 的 92 包**，原 BF16 的 91 包 venv 只读保留，不混装。附件为[完整 runtime 版本与工件哈希锁](locks/qwen-tts-int4-win64-py311-cu128.lock.txt)及[独立 SoX 构建工具约束](locks/sox-1.5.0-build.constraints.txt)。来源是已存成功安装清单/官方工件回执；公开索引用 [PyPI](https://pypi.org/simple/) 与 [PyTorch cu128](https://download.pytorch.org/whl/cu128/)，发布摘要可按 `https://pypi.org/pypi/<包名>/<版本>/json` 核验。

**SoX 例外：**成功环境的 pip `sox 1.5.0` 是经审本地构建 wheel，未公开发布；附件改用同版本[官方源包](https://pypi.org/pypi/sox/1.5.0/json)的已核 SHA-256，绝不伪造公共 wheel 地址。新机须另经有界构建审查；构建工具约束不安装进 runtime、不自动重现原守卫，也不保证新 wheel 字节相同。无获准构建入口时停在准备；不要安装外部 SoX 代替这个 Python 包。

以下仅为**获准新机受控安装/构建中的命令形态**，不是本次执行或原离线安装的逐字重放。`$L` 指本文随附锁目录；pip 先固定为 **26.2.2**，以支持构建约束。锁仅放行 SoX 源包，其余必须为已锁 wheel；构建不能退回 runtime 的 setuptools 80.9.0。

```powershell
$L = "D:/tutorial-repo/docs/locks" # 占位：本教程副本的锁目录
& $P -I -B -c "import sys,struct; assert sys.platform=='win32' and struct.calcsize('P')==8 and sys.version_info[:3]==(3,11,15); print('Windows x64 CPython 3.11.15')"
& $P -I -B -m pip --isolated install --no-deps --only-binary=:all: "https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
& $P -I -B -m pip --isolated install --no-cache-dir --build-constraint "$L/sox-1.5.0-build.constraints.txt" --config-settings=--global-option=--no-user-cfg -r "$L/qwen-tts-int4-win64-py311-cu128.lock.txt"
& $P -I -B -m pip --isolated check
& $P -I -B -c "import importlib.metadata as m; print({n:m.version(n) for n in ('torch','torchaudio','qwen-tts','transformers','accelerate','bitsandbytes','sox','pillow')}); print('distributions=',len(list(m.distributions())))"
```

**风险边界：**[Pillow 官方 PDF 公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-p4wg-p73j-c528)及[图像形态公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-58r4-6rv3-gfh8)均覆盖实际 **12.3.0**，修复版为 **13.0.0**；现有 Gradio **6.16.0** 要求 Pillow<13，不能硬升。此锁是历史成功基线而非安全推荐：不接收/处理图片或 PDF、不开放 Gradio 服务，不等于版本已修复或风险归零；保留的 setuptools 80.9.0 也不能当成已修复版本用于任意源码构建。新增用途或升版另审，不改在产环境。

**成功标志：**上面的平台/包版本核验只读标准库与包元数据、不导入 Torch/bnb；`pip check` exit 0、92 包版本集合与锁一致。`pip freeze` 只是环境记录，不保证跨机复现；此锁只对应上述平台/构建，**尚未做跨机重建或 SoX 源包重建验证**。新机此后仍需获准按第 4—5 节做一次有界短样，核格式、非静音、约束/回收与试听；不能用安装通过代替音频通过，也不要求复制案例帧数或私有 SHA。

## 3. 模型与参考准备

- 固定 [官方 Qwen3-TTS-12Hz-1.7B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/tree/fd4b254389122332181a7c3db7f27e918eec64e3)，revision：`fd4b254389122332181a7c3db7f27e918eec64e3`。获准下载后可用官方 Hub API；不要自动追 `main`：

```powershell
& $P -I -B -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-Base', revision='fd4b254389122332181a7c3db7f27e918eec64e3', local_dir=r'$R/models/base')"
```

- 核完整文件集合（含 `speech_tokenizer/`、配置和文本 tokenizer 文件），权重大小/SHA-256 按该 revision 的官方 LFS/发布元数据对照；不执行仓库自带脚本。本例是**同一官方 Base 加载时量化**，不是官方原生 INT4 checkpoint。
- 准备自己的 `inputs/reference.wav`、逐字参考稿及已审短句。案例参考为 **24 kHz / mono / PCM16 / 6.7 秒**，原 PCM16 转 float32 后除以 32768；不靠换参考、改字或 DSP 让测试过门。声音身份用通用 `NARRATOR`，参考哈希登记为 `<APPROVED_REFERENCE_SHA256>`，不要公开私有参考或其逐字稿。

```powershell
Get-FileHash -Algorithm SHA256 "$R/inputs/reference.wav"
```

**成功标志：**模型 revision/文件核验、参考格式/批准哈希、参考逐字稿与短句版本均绑定；缺件即停，不造替身。

## 4. INT4 受控运行

**先核执行入口，而不是直接跑上游 demo。**成功样片使用项目已审控制器及局部适配；本文不提供绑定私有输入的生产启动包。新环境没有相应受控入口时停在这里，不能把下列参数摘录当成可独立运行的脚本。

1. 主模型量化参数与加载条件保持以下实际成功配置；codec/tokenizer 及敏感层保留 BF16，单 GPU、SDPA，不做 CPU/disk offload：

```python
from transformers import BitsAndBytesConfig
import torch

quant = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_quant_storage=torch.uint8, llm_int8_enable_fp32_cpu_offload=False,
    llm_int8_skip_modules=[
        "speaker_encoder", "talker.text_projection", "talker.codec_head",
        "talker.code_predictor.lm_head",
        "talker.code_predictor.small_to_mtp_projection", "speech_tokenizer",
    ],
)
load_kwargs = dict(
    quantization_config=quant, device_map={"": 0}, dtype=torch.bfloat16,
    attn_implementation="sdpa", local_files_only=True, trust_remote_code=False,
    use_safetensors=True, weights_only=True, offload_state_dict=False,
)
```

2. **两处必要适配不能省略：**qwen-tts 0.1.1 嵌套加载 tokenizer 时剔除量化 kwargs，仍保留 CUDA:0/BF16/SDPA；采用单次局部 loader 委托，不修改包文件/全局类。code predictor 若因报告设备为 meta 而初始化控制 ID，仅在已核真实 CUDA BF16 `[1,2,2048]` embeddings 条件下路由空的 CUDA int64 `[1,0]` 控制 ID；不搬 meta 权重、不伪改 `.device`、不改变采样/EOS。版本或结构不符即停，不能把任意 meta 错误套用此修法。
3. 控制器从空工作目录，以绝对解释器路径、`-I -B` 启动 worker；保留原资源锁、输入只读保护及 BEGIN/RETURN 账。成功调用顺序为 `from_pretrained` → `create_voice_clone_prompt(ref_audio=(reference, 24000), ref_text=已核逐字稿, x_vector_only_mode=False)` → `generate_voice_clone`。Base 不发送 `speaker/instruct/emotion`；seed 在 API 外设置。
4. 原短样采样设置：seed `20261030`；主/子 talker 都是 sample、temperature `0.7`、top_p `0.9`、top_k `50`；repetition_penalty `1.05`、max_new_tokens `480`、non_streaming_mode `True`。不加移调、变速、增益或归一化。复现时冻结全部参数，不把 token 上限当成保证时长。
5. 保留原准入：Job 私有内存上限 **12 GiB**、墙钟 **180 秒**；GPU 预算取父预算、`floor(0.75×总量)`、`当前空闲−512 MiB` 的最小值，主模型与 codec 共用。越界/OOM 记录原错并停止，不自动重抽；allocator 限额不是整卡物理显存硬配额。

已审控制器的调用形态如下，**仅为命令结构**；脚本须已按新任务复核绑定，变量来自本次真实批准、GPU 交还及系统 NVML 文件核验，不复制旧会话值或填假哈希：

```powershell
& $P -I -B "$R/tools/quant_driver.v3.py" int4 `
  --owner-turn $ApprovedTurn --gpu-return-evidence $GpuReturnReceipt `
  --gpu-return-sha256 $GpuReturnSHA256 --nvml-sha256 $NvmlSHA256 --nvml-bytes $NvmlBytes
```

**成功标志：**实际读回 **231 层**量化生效、浮点边界正确，factory/prompt/generate 各一次 BEGIN 与 RETURN；完整新 WAV 落盘。新任务是否可直接 INT4 由当前授权及执行器决定；原历史 v3 只允许实证 INT8 失败后的条件 INT4，不删 fallback gate、不复制旧批准或旧失败来放行。

## 5. 成功检查与保留

按三层分别记结果，不以“有 WAV”或一个退出码覆盖全部结论：

- **生成层：**API 账完整；整 WAV 解码、单声道 PCM16 / 24000 Hz，有限且非静音，无擅自截尾。绑定原文、参考和输出 SHA；内容/声音身份仍需独立复核及真实试听。
- **原约束层：**Job exit 0、预算及输入保护均满足。案例 INT4：**97,920 帧 / 4.08 秒 / 195,884 B**，Job 总耗时 **26.844 秒**；allocator reserved 峰值 **2,529,165,312 B**、紧后预算 **2,929,406,772 B**，Job 私有峰约 **9.76 GiB**。这些不是通用速度，也不能以权重压缩比推算总显存。
- **退出回收层：**Job Active 0、记录的进程消失、持有输入/句柄、mutex 和 NVML 全部闭合，退出后全局 GPU 观测回到基线。案例三次均为 **140,509,184 B**；NVML 全局读数不证明精确进程归属，也不是全机显存必须为 0。

历史 INT4 controller **exit 1 原样保留**：它把退出前 allocated/reserved 非零一并判失败；后来纯标准库独立报告将生成、原约束、退出回收分层核实，报告 exit 0、必要正反例 **8/8** 通过，并未把旧退出码改绿。技术判断、用户首样接受及长段稳定性分别记账。

**恢复/保留：**原 BF16 venv、模型、输入、失败对照、原始配音、母带和正式成品不动；新输出用新目录。断连先核原进程/锁/调用账/完整落盘，只恢复确证缺失阶段；UNKNOWN 不补成 0，成功层不重跑。回退指向原环境，不在原 venv 内升降依赖或删成果。

## 6. 少量常见故障

| 现象 | 最小处理 |
| --- | --- |
| Torch 导入 1114 / DLL 初始化失败 | 先核实际解释器、Torch wheel 与 VC 运行库/DLL 版本；按官方来源处理需获准的系统组件，不拼 DLL、不先归因 GPU 驱动。 |
| wheel 下载中断 / TLS 错误 | 保留部分件与原错，在原授权内核官方来源及完整哈希后才继续；不关 TLS、不换不明镜像。 |
| meta tensor / CPU offload | 先分清真实未物化权重与空控制 ID 的设备误路由，核第 4 节精确适配；不全局篡改设备或忽略 meta。 |
| 守卫误拦正常对象 | 原生 43 个 FP32 buffer 合计 1,792 B、Windows venv 重定向父链和可选 `org.python.core` 探测须按精确结构/来源分类；可选缺模块保持正常 `ImportError` 语义，不全面放宽守卫。 |
| INT8 codec 解码 OOM | 历史 INT8 在新增 16 MiB 分配时失败；只有完成回收且满足当次条件授权才转 INT4，不为教程重跑 INT8。 |
| Tool use aborted / 终态未知 / 附件 403 | 拒绝不换路绕过，先对账并保留 UNKNOWN；403 仅证原官方 GET 被拒，鉴权/网关/附件权限未分，不猜 scope、不重试 GET/HEAD 或重传。该首样已能试听，附件诊断不阻本机制作。 |

案例来源为既有 `environment-continuation-result.json`、`original-pins.json` / `installed.json`、`backend-source.json`、驱动 `FINAL-VERIFICATION.md`、`FIRST-MODEL-RUN-RESULT.v1.json`、`INT4-FIRST-SAMPLE-TECHNICAL-REVIEW.v1.json` 与 `OUTCOME-POLICY-CHECKS.v1.json` 的脱敏事实；原件留受控本地，**不是读者下载前置**。公开入口仅使用本文所列官方站点；不发布台本、参考素材、私有附件或运行身份。
