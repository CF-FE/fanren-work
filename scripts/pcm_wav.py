"""Read-only receipt for an uncompressed PCM16 WAV with a standard 44-byte header."""

import argparse
import hashlib
import json
from pathlib import Path
import struct


HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")


def verify_pcm16_wav(path, *, sample_rate, channels, max_bytes, expected_pcm=None, expected_sha256=None):
    """Verify file layout, format and any supplied reference; return a JSON-compatible receipt."""
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(HEADER.size)
        if len(header) != HEADER.size:
            raise ValueError("incomplete WAV header")
        (riff, riff_size, wave, fmt, fmt_size, encoding, actual_channels, rate,
         byte_rate, align, bits, data, pcm_size) = HEADER.unpack(header)
        if (riff, wave, fmt, fmt_size, encoding, data) != (b"RIFF", b"WAVE", b"fmt ", 16, 1, b"data"):
            raise ValueError("expected standard 44-byte PCM WAV header")
        if (rate, actual_channels, bits) != (sample_rate, channels, 16) or rate == 0 or actual_channels == 0:
            raise ValueError("unexpected PCM sample rate, channels or bit depth")
        if align != channels * 2 or byte_rate != rate * align or pcm_size % align:
            raise ValueError("inconsistent PCM frame layout")
        size = HEADER.size + pcm_size
        if not pcm_size or size > max_bytes or riff_size != size - 8:
            raise ValueError("unexpected WAV size")
        pcm = stream.read(pcm_size)
        if len(pcm) != pcm_size or stream.read(1):
            raise ValueError("WAV length differs from the declared payload")
    if not any(pcm):
        raise ValueError("all PCM samples are zero")
    if expected_pcm is not None and pcm != expected_pcm:
        raise ValueError("PCM differs from reference")
    digest = hashlib.sha256(header)
    digest.update(pcm)
    sha = digest.hexdigest()
    if expected_sha256 is not None and sha != expected_sha256.lower():
        raise ValueError("WAV SHA-256 differs from reference")
    frames = pcm_size // align
    return {"path": str(path), "sha256": sha, "bytes": size, "frames": frames,
            "seconds": frames / rate, "sample_rate": rate, "channels": channels, "bits": bits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--rate", required=True, type=int)
    parser.add_argument("--channels", required=True, type=int)
    parser.add_argument("--max-bytes", required=True, type=int)
    parser.add_argument("--sha256", help="Expected digest of the entire WAV file")
    args = parser.parse_args()
    try:
        receipt = verify_pcm16_wav(args.wav, sample_rate=args.rate, channels=args.channels,
                                   max_bytes=args.max_bytes, expected_sha256=args.sha256)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(receipt, ensure_ascii=True))


if __name__ == "__main__":
    main()
