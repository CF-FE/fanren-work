"""Exercise the CLI with temporary dist-info metadata; no packages are installed."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
LOCK = TOOLS.parent / "locks/qwen-tts-int4-win64-py311-cu128.lock.txt"
spec = importlib.util.spec_from_file_location("verify_environment", TOOLS / "verify_environment.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

# Feed real importlib.metadata readers a synthetic fixture, without a production
# bypass flag or any dependency on the host machine's installed package set.
RUNNER = """
import importlib.metadata as metadata
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import verify_environment as verifier
read_distributions = metadata.distributions
verifier.metadata.distributions = lambda: read_distributions(path=[sys.argv[2]])
raise SystemExit(verifier.main(['--lock', sys.argv[3]]))
"""


class EnvironmentSetTests(unittest.TestCase):
    def run_inventory(self, entries):
        with tempfile.TemporaryDirectory() as folder:
            for number, (name, version) in enumerate(entries):
                info = Path(folder) / f"fixture{number}-1.dist-info"
                info.mkdir()
                (info / "METADATA").write_text(
                    f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", RUNNER, str(TOOLS), folder, str(LOCK)],
                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def setUp(self):
        self.pins = verifier.read_lock(LOCK)

    def test_complete_exact_set(self):
        code, report = self.run_inventory(self.pins.items())
        self.assertEqual(code, 0)
        self.assertEqual((report["expected_count"], report["installed_count"]), (92, 92))

    def test_missing_package_exits_nonzero(self):
        entries = dict(self.pins)
        entries.pop("qwen-tts")
        code, report = self.run_inventory(entries.items())
        self.assertEqual(code, 1)
        self.assertEqual(report["missing"], ["qwen-tts"])

    def test_extra_bootstrap_package_exits_nonzero(self):
        entries = dict(self.pins, **{"bootstrap-only": "1.0"})
        code, report = self.run_inventory(entries.items())
        self.assertEqual(code, 1)
        self.assertEqual(report["extra"], ["bootstrap-only"])

    def test_wrong_direct_wheel_versions_exit_nonzero(self):
        entries = dict(self.pins)
        entries["torch"] = "2.11.0+cu127"
        entries["torchaudio"] = "2.11.0"
        code, report = self.run_inventory(entries.items())
        self.assertEqual(code, 1)
        self.assertEqual(set(report["version_mismatch"]), {"torch", "torchaudio"})

    def test_normalized_names(self):
        entries = [(name.upper().replace("-", "_."), version) for name, version in self.pins.items()]
        self.assertEqual(self.run_inventory(entries)[0], 0)

    def test_duplicate_normalized_metadata_exits_nonzero(self):
        entries = list(self.pins.items()) + [("QWEN_TTS", self.pins["qwen-tts"])]
        code, report = self.run_inventory(entries)
        self.assertEqual(code, 2)
        self.assertIn("Duplicate installed distribution", report["error"])

    def test_direct_wheel_pins_keep_cuda_local_version(self):
        self.assertEqual(self.pins["torch"], "2.11.0+cu128")
        self.assertEqual(self.pins["torchaudio"], "2.11.0+cu128")


if __name__ == "__main__":
    unittest.main()
