# 核验 PCM16 WAV 并生成回执

在仓库根目录用 Python 3 执行。以 CLOU-94 首件为例，预期格式是 24000 Hz、单声道、16 位，文件上限为 2 MiB。将 sample.wav 换为已获准读取的文件。

```sh
python scripts/pcm_wav.py sample.wav --rate 24000 --channels 1 --max-bytes 2097152
```

输出一行 JSON，含整文件 SHA-256、字节数、帧数、秒数和实测格式。核收已登记的候选时，追加 `--sha256 <原回执中的完整摘要>`。不匹配时退出码为 1。只需要复跑合成样例时，运行 `python -m unittest discover -s tests -p test_pcm_wav.py`。

从项目根目录的 Python 代码复用同一函数：

```python
from scripts.pcm_wav import verify_pcm16_wav

receipt = verify_pcm16_wav("sample.wav", sample_rate=24000, channels=1, max_bytes=2 * 1024**2)
```

有参考原轨时可传 `expected_pcm`（解码后的 PCM 字节）。本工具专用于标准 44 字节头、非空且至少有一个非零样本的 PCM16 WAV。扩展头、附加元数据块、压缩音频和纯静音片段在此契约之外。调用方负责限制可读路径、提供本项目的格式和大小要求，并决定是否采用或放行。

首例来自 CLOU-94 的首件及余量流程。整文件摘要可用来找回同一实件；对白自然度、是否获准采用及未知提交的续办须另按原回执判断。已冻结的历史入口继续按原脚本摘要复现。
