import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pcm_wav import verify_pcm16_wav


class WavReceiptTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.wav = Path(temp.name) / "sample.wav"
        self.pcm = b"\x01\x00\xff\xff" * 20
        buf = io.BytesIO()
        with wave.open(buf, "wb") as writer:
            writer.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            writer.writeframes(self.pcm)
        self.original = buf.getvalue()
        self.wav.write_bytes(self.original)
        self.options = dict(sample_rate=24000, channels=1, max_bytes=len(self.original))

    def test_receipt_matches_cli_and_reference(self):
        sha = hashlib.sha256(self.original).hexdigest()
        receipt = verify_pcm16_wav(self.wav, **self.options, expected_pcm=self.pcm, expected_sha256=sha)
        self.assertEqual(receipt, dict(path=str(self.wav), sha256=sha, bytes=len(self.original), frames=40,
                                       seconds=40 / 24000, sample_rate=24000, channels=1, bits=16))
        cmd = [sys.executable, str(ROOT / "scripts/pcm_wav.py"), str(self.wav),
               "--rate", "24000", "--channels", "1", "--max-bytes", str(len(self.original)), "--sha256"]
        self.assertEqual(json.loads(subprocess.check_output(cmd + [sha])), receipt)
        bad = subprocess.run(cmd + ["0" * 64], capture_output=True)
        self.assertEqual(bad.returncode, 1)
        self.assertFalse(bad.stdout)

    def test_contract_and_payload_mismatches(self):
        for change in [dict(sample_rate=16000), dict(channels=2), dict(max_bytes=len(self.original)-1),
                       dict(expected_pcm=b"other"), dict(expected_sha256="0" * 64)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_pcm16_wav(self.wav, **(self.options | change))

    def test_malformed_or_silent_wav(self):
        for name, raw in {"short": self.original[:42], "truncated": self.original[:-1],
                          "extra": self.original+b"x", "silence": self.original[:44]+bytes(len(self.pcm)),
                          "alignment": self.original[:32]+b"\x01\0"+self.original[34:],
                          "bad riff length": self.original[:4]+bytes(4)+self.original[8:]}.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.wav.write_bytes(raw)
                verify_pcm16_wav(self.wav, **self.options)
