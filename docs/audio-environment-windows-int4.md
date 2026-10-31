# Windows 小显存 Qwen-TTS：环境重建准备指南

核验截至 **2026-10-31**。本文交付**平台检查、隔离依赖安装、完整 92 包版本核验和模型/参考准备**。**端到端生成实现尚未交付**：仓库没有可复现案例出音的量化装配、必要适配和真实启动入口；完成本文不等于已能生成音频。待办见第 4 节。

案例已有 21 码点、4.08 秒首样获用户试听认可；后续四片共 140 码点、32.16 秒通过独立文件/完整解码/技术检查，内容、声线、听感仍未验。这里只记录已证条件，不为写教程重装或重测；新机及 SoX 源包重建均未验证。

## 1. 前置条件与配置选择

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
| 1.7B Base / INT4（NF4） | 同一 Base 运行时量化；codec 保持浮点 | 本机 4 GB：首样框架 reserved 峰 **2,529,165,312 B ≈2.36 GiB**；后续四片峰 **2,860,515,328 B ≈2.66 GiB**；Job private 峰约 **9.76 GiB**；最低 RAM 未给定，需实测 | GPU-only，无 CPU/disk offload；codec/敏感层 BF16 | 本机可复用的已证短样配置；长段另验 | 本机 **4.08 秒首样成功**；后续四短片技术检查通过，非长期连续/长音频稳定 |

量化均指**官方 Base 加载时的运行时路线，不是官方原生 INT8/INT4 checkpoint**；兼容边界沿用上表实际版本及第 2 节官方来源，不能从 bnb 支持某硬件推定 0.6B 集成已通过。reserved 仅为 Torch allocator 峰值，Job private 峰不是系统 RAM 最低值；20 GiB 入场线是项目合同余量。权重算术估计不含 codec、缓存、激活等开销，不能充当总峰值或可运行证据。**0.6B 只作选型比较，不切换当前生产模型。**

## 2. 建立并核验隔离依赖

将本节两个 PowerShell 代码段按顺序保存为同一份 `.ps1` 并整体执行；不要在交互窗口忽略异常后继续粘贴下一条。先准备 [Python 3.11.15 x64](https://docs.astral.sh/uv/guides/install-python/)；示例为占位绝对路径。目标已存在、大小写碰撞或父链有 junction/symlink 时先核对，不覆盖。`$ErrorActionPreference` 只处理 PowerShell 错误，**每个 native Python 命令仍须立即检查 `$LASTEXITCODE`，失败即停，不能继续安装**。

```powershell
$ErrorActionPreference = "Stop"
$R = "D:/audio-project"
$PY311 = "D:/tools/python311/python.exe" # 替换为已核准解释器
& $PY311 -I -B -c "import sys,struct; assert sys.platform=='win32' and struct.calcsize('P')==8 and sys.version_info[:3]==(3,11,15); print('Windows x64 CPython 3.11.15')"
if ($LASTEXITCODE -ne 0) { throw "平台检查失败；停止，不创建环境或安装包" }
if (Test-Path -LiteralPath $R) { throw "目标已存在，请先核对，不覆盖" }
New-Item -ItemType Directory -Path $R | Out-Null
"tools", "downloads", "models", "inputs", "outputs", "run-empty" | ForEach-Object {
    New-Item -ItemType Directory -Path "$R/$_" | Out-Null
}
& $PY311 -I -B -m venv "$R/.venv-int4"
if ($LASTEXITCODE -ne 0) { throw "venv 创建失败" }
$P = "$R/.venv-int4/Scripts/python.exe"
Set-Location "$R/run-empty"
```

使用[完整 runtime 锁](locks/qwen-tts-int4-win64-py311-cu128.lock.txt)重建成功路线的 92 包；原 BF16 的 91 包环境保留，不混装或复制 venv。锁的官方来源为 [PyPI](https://pypi.org/simple/) 与 [PyTorch cu128](https://download.pytorch.org/whl/cu128/)，每项保留工件 SHA-256。

**SoX 例外：**历史成功 wheel 为本地构建、未公开；锁改用同版本官方 `sox 1.5.0` 源包及已核哈希。新机只能在已审的有界构建条件下使用[独立构建约束](locks/sox-1.5.0-build.constraints.txt)，缺此条件先停在准备。约束中的哈希注释是来源记录，**pip 不会强制校验注释**；它也不保证重建 wheel 字节相同。构建工具不能装入 runtime，外部 SoX 不能替代该 Python 包。

```powershell
$T = "D:/tutorial-repo" # 本仓库副本
$L = "$T/docs/locks"
& $P -I -B -m pip --isolated install --no-deps --only-binary=:all: "https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap 失败" }
& $P -I -B -m pip --isolated install --no-cache-dir --build-constraint "$L/sox-1.5.0-build.constraints.txt" --config-settings=--global-option=--no-user-cfg -r "$L/qwen-tts-int4-win64-py311-cu128.lock.txt"
if ($LASTEXITCODE -ne 0) { throw "锁定依赖安装失败" }
& $P -I -B -m pip --isolated check
if ($LASTEXITCODE -ne 0) { throw "pip check 失败" }
& $P -I -B "$T/docs/tools/verify_environment.py" --lock "$L/qwen-tts-int4-win64-py311-cu128.lock.txt"
if ($LASTEXITCODE -ne 0) { throw "完整依赖名称/版本集合不匹配" }
```

[验证器](tools/verify_environment.py)仅用标准库读取包元数据，不导入 Torch/bnb：将名称按大小写及 `-_.` 规范化后，比较**全部 92 个精确版本**，包括 direct wheel URL 对应的 `torch/torchaudio==2.11.0+cu128`。缺项、额外包、错版本及重复元数据均非零退出；bootstrap/构建包没有豁免。`pip check` 不能替代此集合比较。验证器不检查已安装文件字节、工件来源或 ABI；安装工件哈希仍由锁和 pip `--require-hashes` 校验。[回归检查](tools/test_verify_environment.py)使用临时包元数据，不安装这 92 包。

**风险边界：**Pillow **12.3.0** 在两份[官方 PDF 公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-p4wg-p73j-c528)/[图像公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-58r4-6rv3-gfh8)的影响范围内，修复版为 **13.0.0**，但现有 Gradio **6.16.0** 要求 Pillow<13。此锁是历史成功记录，不是安全推荐；不处理图片/PDF、不开公网 Gradio，不代表风险已修复。保留的 setuptools 80.9.0 不用于任意源码构建；升级另行验证，不改在产环境。

**本步通过：**平台断言、安装、`pip check` 和完整集合比较均 exit 0。只证明环境准备检查通过；精确 VC++/libsndfile DLL、跨机及 SoX 重建仍有缺项，不保证出音或跨机复现。

## 3. 准备模型与自己的参考

固定[官方 Qwen3-TTS-12Hz-1.7B-Base revision](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/tree/fd4b254389122332181a7c3db7f27e918eec64e3)，不自动追 `main`。完成第 2 节后，先将有使用权及必要同意的参考放入 `inputs/reference.wav`，再将以下段保存为 `.ps1` 执行获准的下载准备：

```powershell
$ErrorActionPreference = "Stop"
$R = "D:/audio-project"
$P = "$R/.venv-int4/Scripts/python.exe"
if (-not (Test-Path -LiteralPath "$R/inputs/reference.wav")) { throw "请先准备自己的参考音频" }
& $P -I -B -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-Base', revision='fd4b254389122332181a7c3db7f27e918eec64e3', local_dir=r'$R/models/base')"
if ($LASTEXITCODE -ne 0) { throw "固定版本模型下载失败" }
Get-FileHash -Algorithm SHA256 "$R/inputs/reference.wav"
```

核模型完整集合（含 speech_tokenizer、配置、文本 tokenizer）及该 revision 官方大小/哈希；不执行模型仓库脚本。参考登记实际格式、SHA 和逐字参考稿，案例是 24 kHz/mono/PCM16/6.7 秒，不要求复制案例声音或私有哈希。

## 4. 到此停止：端到端生成待办

**本仓库尚无可执行生成入口。**已删除依赖未公开 `quant_driver.v3.py` 的示例调用，不用占位脚本或参数摘录冒充完整实现。后续交付须完成并单独验证：

1. **量化装配：**官方 1.7B Base 的运行时 NF4/double quant、BF16 compute、CUDA:0/SDPA；codec/tokenizer 与敏感层保持 BF16，禁止误量化嵌套 tokenizer。不是官方原生 INT4 checkpoint。
2. **两处必要适配：**嵌套 tokenizer 加载剔除量化 kwargs；精确结构下的 meta 控制 ID 路由修复。当前只有案例描述，没有可移植实现及相应回归验证，不能据摘要套用任意 meta 错误。
3. **参考与文本绑定：**真实参考 PCM/逐字稿/短句、版本及哈希核验，Base API 参数和采样设置固定；不得公开案例台本或复制旧批准身份。
4. **真实启动与验收：**发布脱敏的控制入口、资源互斥/预算/输入保护及 API BEGIN/RETURN 账，按实际 WAV 完整解码、资源回收和真实听审验收；新机失败分支也须验证。

不为补教程运行 GPU 或临时编造未验证代码。环境准备通过、原机曾成功、ASR 转写通过，均不等于新机端到端生成、声线或听感通过。

## 附录：案例数字与故障边界

| 已证样本 | 时长 | Torch allocator reserved 峰 | 结论范围 |
| --- | ---: | ---: | --- |
| 21 码点首样 | 4.08 秒 | 2,529,165,312 B，约 2.36 GiB | 用户认可仅覆盖此首样；Job private 峰约 9.76 GiB |
| 后续四片，140 码点 | 共 32.16 秒 | 2,860,515,328 B，约 2.66 GiB | 独立身份/解码/技术检查通过；内容、声线、听感未验 |

reserved 是框架分配器指标，**两行均不是设备总显存峰或硬件最低要求**；Job private 也不是最低 RAM。历史控制器曾要求 Job 12 GiB/180 秒及按实际空闲收紧的 GPU 预算；这是案例合同，不是本指南已交付的控制器。旧 exit 1 与后续离线分层复核分别保留，不为美化退出码重跑。

| 现象 | 最小处理 |
| --- | --- |
| Torch 1114/DLL 初始化失败 | 核实际解释器、wheel、VC 运行库/DLL 版本，不拼 DLL，不先归因驱动。 |
| 下载/TLS 中断 | 保留原错；核官方工件及完整哈希后恢复，不关闭 TLS。 |
| meta/CPU offload/守卫误判 | 按精确结构区分设备路由、原生 FP32 buffer、venv 父链及正常可选 ImportError；不全局放宽。 |
| INT8 codec OOM | 保留真实失败并完成回收；转 INT4 须符合当前任务，不为教程复跑。 |
| 断流、UNKNOWN 或附件拒绝 | 对账原进程/锁/回执，只恢复确证未执行部分；不换路绕拒、重传规避或补造历史指标。 |

原 BF16 venv、模型、输入、失败记录、原始配音、母带及成品保留原位，新输出用新目录。本指南只公开脱敏事实与官方来源，不含音频、台本文字、私有运行脚本或凭据。
