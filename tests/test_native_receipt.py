"""Extract bounded native final replies from isolated Codex transcript fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/native_receipt.py"


class NativeReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.transcript = self.root / "native-transcript.jsonl"
        self.output = self.root / "receipt.json"
        self.thread = "native-thread-fixture"
        self.turn = "selected-business-turn"
        self.contact = "issue-2-unit-qa-contact"
        self.final = "Actual generated inspection result."
        self.analysis_marker = "PRIVATE_ANALYSIS_MUST_NOT_APPEAR"
        self.rows = [
            {"type": "session_meta", "payload": {"id": self.thread}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "old-turn"}},
            {"type": "turn_context", "payload": {"turn_id": "old-turn"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Old task: " + self.contact}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Old final must not be selected."}]}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "old-turn",
                "last_agent_message": "Old final must not be selected."}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": self.turn}},
            {"type": "turn_context", "payload": {"turn_id": self.turn}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Please inspect " + self.contact}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "analysis",
                "content": [{"type": "output_text", "text": self.analysis_marker}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "commentary",
                "content": [{"type": "output_text", "text": "An intermediate progress update."}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": self.final}]}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": self.turn,
                "last_agent_message": self.final}},
        ]

    def write_transcript(self, rows=None):
        raw = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (self.rows if rows is None else rows)).encode("utf-8")
        self.transcript.write_bytes(raw)
        return raw

    def cli(self, *, thread=None, turn=None, contact=None, output=None, ok=True):
        result = subprocess.run([sys.executable, "-E", "-S", "-B", str(SCRIPT),
            "--transcript", str(self.transcript), "--thread", self.thread if thread is None else thread,
            "--turn", self.turn if turn is None else turn, "--contact-ref", self.contact if contact is None else contact,
            "--output", str(self.output if output is None else output)],
            text=True, capture_output=True, timeout=10)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(result.stderr.strip())
        return result

    def test_extracts_only_the_requested_native_user_and_completed_final_with_provenance(self):
        raw = self.write_transcript()
        self.cli()
        result = json.loads(self.output.read_bytes())
        self.assertEqual(result["source_kind"], "codex_transcript_snapshot.v1")
        self.assertEqual(result["thread"]["id"], self.thread)
        self.assertEqual(len(result["turns"]), 1)
        turn = result["turns"][0]
        self.assertEqual(turn["id"], self.turn)
        users = [item for item in turn["items"] if item["type"] == "userMessage"]
        finals = [item for item in turn["items"] if item["type"] == "agentMessage"]
        self.assertEqual(len(users), 1)
        self.assertIn(self.contact, users[0]["content"][0]["text"])
        self.assertEqual([(item["phase"], item["text"]) for item in finals], [("final_answer", self.final)])
        self.assertNotIn(self.analysis_marker, self.output.read_text(encoding="utf-8"))
        self.assertNotIn("Old final", self.output.read_text(encoding="utf-8"))
        provenance = result["provenance"]
        self.assertEqual(provenance["source"], {"path": str(self.transcript), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertTrue(provenance["observed_at"])
        self.assertIsInstance(provenance["selected_line_numbers"], list)
        self.assertIn(9, provenance["selected_line_numbers"])
        self.assertIn(12, provenance["selected_line_numbers"])
        self.assertNotIn(10, provenance["selected_line_numbers"])

    def test_wrong_association_missing_completion_and_nonfinal_messages_never_publish(self):
        for case in ("session", "thread", "turn", "contact", "missing-complete", "complete-turn",
                     "last-message", "commentary", "contact-only-in-old-turn"):
            with self.subTest(case=case):
                rows = deepcopy(self.rows)
                arguments = {}
                if case == "session":
                    rows[0]["payload"]["id"] = "foreign-session"
                elif case in ("thread", "turn", "contact"):
                    arguments[case] = "foreign-" + case
                elif case == "missing-complete":
                    rows.pop()
                elif case == "complete-turn":
                    rows[-1]["payload"]["turn_id"] = "foreign-turn"
                elif case == "last-message":
                    rows[-1]["payload"]["last_agent_message"] = "Different final text"
                elif case == "commentary":
                    rows[-2]["payload"]["phase"] = "commentary"
                else:
                    rows[8]["payload"]["content"][0]["text"] = "An unrelated request without the contact"
                self.write_transcript(rows)
                output = self.root / f"refused-{case}.json"
                self.cli(output=output, ok=False, **arguments)
                self.assertFalse(output.exists())

    def test_existing_different_output_is_preserved(self):
        self.write_transcript()
        original = b'{"original":"preserve this receipt"}\n'
        self.output.write_bytes(original)
        self.cli(ok=False)
        self.assertEqual(self.output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
