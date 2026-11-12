"""Exercise the offline evidence CLI using only synthetic, frozen fixtures."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "offline_qa_evidence.py"
REPORT = "derived-evidence-validation.json"
NOTES = "validation-notes.md"
MANIFEST = "artifact-manifest.json"

IN_BOUNDS = (
    "【完整转写】\n一个合成片段。\n【结尾观察】\n片段。\n"
    "【位置与依据】\n- “片段”：从0.70秒开始，到2.20秒结束。"
)
OUT_OF_BOUNDS = (
    "【结尾观察】\n句子。\n"
    "【位置与依据】\n- 起始时间：0.00秒\n- 结束时间：20.00秒"
)


OFFLINE_RUN = """
from pathlib import Path
import runpy
import sys

def deny_external_calls(event, args):
    if event in {"subprocess.Popen", "os.exec", "os.posix_spawn", "os.system", "socket.__new__"}:
        raise AssertionError("offline validator attempted an external call: " + event)

sys.addaudithook(deny_external_calls)
sys.argv.pop(0)
sys.path.insert(0, str(Path(sys.argv[0]).parent))
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class OfflineQaEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "frozen"
        self.source.mkdir()
        self.output = self.root / "derived"
        self.input_path = self.root / "input.json"
        self.contract_path = self.root / "contract.json"
        self.review = {
            "attempt": "synthetic-targeted-attempt",
            "workflow_task_id": "synthetic-targeted-task",
            "workflow_action_id": "a" * 64,
        }
        self.contract = {
            "schema_version": 1, "review": self.review, "require_full_transcript": True, "clips": [],
        }
        self.input = {
            "schema_version": 1, "project": "fanren-work", "task_id": "synthetic-validation-task",
            "unit_id": "synthetic-offline-qa", "deliverable_kind": "sealed_response_offline_evidence_validation_report",
            "executor": {"name": "synthetic-qa", "session": "session", "pane": "w1:p2", "thread": "thread"},
            "inputs": [],
        }

    @staticmethod
    def digest(raw):
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def add_source(self, name, value):
        path = self.source / name
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            self.write_json(path, value)
        raw = path.read_bytes()
        ref = {"path": str(path), "bytes": len(raw), "sha256": self.digest(raw)}
        self.input["inputs"].append(ref)
        return ref

    def add_clip(self, ordinal, model_text, *, expected_tail=None, source_id=None, malformed_response=False,
                 include_finish_reason=True):
        clip_id = f"synthetic-clip-{ordinal}"
        spec = {"id": clip_id, "ordinal": ordinal}
        if expected_tail is not None:
            spec["expected_tail"] = expected_tail
        self.contract["clips"].append(spec)
        stem = f"{ordinal:03d}"
        identity = {**self.review, "id": source_id or clip_id}
        row = {**identity, "original_ordinal": ordinal, "audio_duration_seconds": 4.0}
        request_sha = "b" * 64
        self.add_source(stem + ".input.json", {**row, "request_sha256": request_sha})
        choice = {"index": 0, "message": {"role": "assistant", "content": model_text}}
        if include_finish_reason:
            choice["finish_reason"] = "stop"
        response = self.add_source(stem + ".response.raw.json", b'{"choices":' if malformed_response else {
            "choices": [choice],
            "usage": {"completion_tokens": 12},
        })
        self.add_source(stem + ".sealed.json", {
            **identity, "request_sha256": request_sha, "response_sha256": response["sha256"],
        })
        self.add_source(stem + ".comparison.json", {
            **row, "model_observation": model_text, "finish_reason": "stop", "completion_tokens": 12,
            "expected_text": f"合成片段，{expected_tail or '结尾'}。",
        })

    def cli(self, *, ok=True, guard_offline=False):
        self.write_json(self.input_path, self.input)
        self.write_json(self.contract_path, self.contract)
        command = [sys.executable, "-E", "-S", "-B"]
        if guard_offline:
            command.extend(["-c", OFFLINE_RUN])
        result = subprocess.run([
            *command, str(SCRIPT), "--input", str(self.input_path),
            "--input-sha256", self.digest(self.input_path.read_bytes()),
            "--contract", str(self.contract_path), "--output-dir", str(self.output),
        ], cwd=self.root, capture_output=True, text=True, timeout=15)
        if not ok:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("STOP", result.stderr)
            self.assertFalse(self.output.exists())
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((self.output / REPORT).read_bytes())

    def test_multiple_clips_preserve_claims_and_separate_range_from_quality(self):
        self.add_clip(37, IN_BOUNDS, expected_tail="片段")
        self.add_clip(103, OUT_OF_BOUNDS, expected_tail="真正的尾句")
        report = self.cli()
        clips = {row["ordinal"]: row for row in report["clips"]}
        self.assertEqual(set(clips), {37, 103})
        for ordinal, expected, text in ((37, "IN_BOUNDS", IN_BOUNDS), (103, "OUT_OF_BOUNDS", OUT_OF_BOUNDS)):
            with self.subTest(ordinal=ordinal):
                row = clips[ordinal]
                self.assertEqual(row["location"]["status"], expected)
                self.assertEqual(row["location"]["accepted_position"], "UNKNOWN")
                self.assertEqual(row["quality"], "UNKNOWN")
                self.assertEqual(row["original_model_text"], text)
        self.assertIn("20.00", json.dumps(clips[103]["location"]["claims"], ensure_ascii=False))
        self.assertEqual(clips[37]["transcript"]["status"], "PRESENT")
        self.assertEqual(clips[103]["transcript"]["status"], "MISSING")
        self.assertEqual(clips[103]["tail"]["status"], "INSUFFICIENT")

    def test_sha_mismatch_stops_before_emitting_artifacts(self):
        self.add_clip(37, IN_BOUNDS)
        self.input["inputs"][1]["sha256"] = "0" * 64
        self.assertIn("SHA", self.cli(ok=False))

    def test_valid_bytes_for_wrong_clip_still_stop(self):
        self.add_clip(37, IN_BOUNDS, source_id="another-clip")
        self.assertIn("037.sealed.json.id: identity mismatch", self.cli(ok=False))

    def test_missing_frozen_file_stops_before_emitting_artifacts(self):
        self.add_clip(37, IN_BOUNDS)
        missing = Path(self.input["inputs"][2]["path"])
        missing.unlink()
        self.assertIn(missing.name, self.cli(ok=False))

    def test_unparseable_response_or_location_is_unknown(self):
        self.add_clip(37, IN_BOUNDS, malformed_response=True)
        unknown_position = "【位置与依据】\n- 录音过了一会儿才开始。"
        self.add_clip(38, unknown_position)
        clips = {row["ordinal"]: row for row in self.cli()["clips"]}
        self.assertEqual(clips[37]["location"]["status"], "UNKNOWN")
        self.assertEqual(clips[37]["transcript"]["status"], "UNKNOWN")
        self.assertEqual(clips[38]["location"]["status"], "UNKNOWN")
        self.assertEqual(clips[38]["original_model_text"], unknown_position)

    def test_exact_time_boundary_and_tail_echo_remain_separate(self):
        self.add_clip(37, (
            "【完整转写】\nUNKNOWN。\n【结尾观察】\n未听到“真正的尾句”。\n"
            "【位置与依据】\n- 估计误差：99秒。\n- 时间点：4.0000000000000001秒"
        ), expected_tail="真正的尾句")
        clip = self.cli()["clips"][0]
        self.assertEqual(clip["transcript"]["status"], "UNKNOWN")
        self.assertEqual(clip["tail"]["status"], "UNKNOWN")
        self.assertTrue(clip["tail"]["literal_mention_in_closing"])
        self.assertEqual(clip["location"]["unparsed_lines"], ["- 估计误差：99秒。"])
        self.assertEqual(clip["location"]["status"], "OUT_OF_BOUNDS")
        self.assertEqual(clip["location"]["claims"][0]["seconds"], "4.0000000000000001")

    def test_missing_raw_finish_reason_is_not_inferred_from_the_comparison(self):
        self.add_clip(37, IN_BOUNDS, include_finish_reason=False)
        clip = self.cli()["clips"][0]
        self.assertIsNone(clip["finish"]["targeted"]["reason"])
        self.assertEqual(clip["quality"], "UNKNOWN")

    def test_history_retains_its_own_finish_reason_and_outputs_are_idempotent(self):
        self.add_clip(37, IN_BOUNDS)
        history_name = "synthetic-FINAL-QUALITY-REPORT.json"
        history_identity = {"task_ref": "historical-task", "attempt": "historical-attempt"}
        self.contract["history"] = {"file": history_name, **history_identity, "retain_ordinals": []}
        self.add_source(history_name, {
            **history_identity, "counts": {"BEGIN": 1, "RETURN": 1, "compared": 1},
            "rows": [{"id": "synthetic-clip-37", "ordinal": 37, "response_finish_reason": "length",
                      "response_usage": {"completion_tokens": 270}}],
        })
        frozen_before = {path.name: path.read_bytes() for path in self.source.iterdir()}

        report = self.cli()
        finish = report["clips"][0]["finish"]
        self.assertEqual(finish["targeted"]["reason"], "stop")
        self.assertEqual(finish["targeted"]["completion_tokens"], 12)
        self.assertEqual(finish["historical"]["reason"], "length")
        self.assertEqual(finish["historical"]["completion_tokens"], 270)
        first = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.assertEqual(set(first), {REPORT, NOTES, MANIFEST})
        manifest = json.loads(first[MANIFEST])
        self.assertEqual(manifest["task_id"], self.input["task_id"])
        self.assertNotIn("native_receipt", manifest)
        self.assertNotIn("status", manifest)
        self.assertEqual({Path(ref["path"]).name for ref in manifest["artifacts"]}, {REPORT, NOTES})
        for ref in manifest["artifacts"]:
            raw = Path(ref["path"]).read_bytes()
            self.assertEqual((ref["bytes"], ref["sha256"]), (len(raw), self.digest(raw)))

        self.cli(guard_offline=True)
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, first)
        self.assertEqual({path.name: path.read_bytes() for path in self.source.iterdir()}, frozen_before)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"frozen", "derived", "input.json", "contract.json"})


if __name__ == "__main__":
    unittest.main()
