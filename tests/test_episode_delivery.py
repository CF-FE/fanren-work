"""Exercise the project CLI with isolated files and native-receipt fixtures only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


STAGING = Path(__file__).resolve().parents[1]


class EpisodeDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "fanren-work"
        self.repo.mkdir()
        shutil.copytree(STAGING / "workflows", self.repo / "workflows")
        shutil.copytree(STAGING / "scripts", self.repo / "scripts")
        (self.repo / "README.md").write_text("# Project memory\nUse the original task and owner plan.\n", encoding="utf-8")
        self.script = self.repo / "scripts/episode_delivery.py"
        self.state = self.root / "unit.sqlite3"
        self.executor = {"name": "qa-worker", "session": "fanren-project", "pane": "w1:p7", "thread": "worker-thread-1"}
        self.owner = {"name": "fanren-owner-gen1", "session": "project-coordinator", "pane": "w1:p4",
                      "thread": "owner-thread-1", "generation": 1}
        self.plan = self.write_artifact("owner-plan.txt", b"Owner plan: inspect existing audio; no new production.\n")
        self.source = self.write_artifact("input-metadata.json", b'{"original":"issue-2"}\n')
        native_dispatch = {"exit_code": 0, "stdout": json.dumps({"result": {"type": "agent_prompted",
                           "agent": {"name": self.executor["name"], "pane_id": self.executor["pane"]}}})}
        self.dispatch = self.write_artifact("existing-dispatch.json", self.json_bytes(native_dispatch))
        self.request = {
            "schema_version": 1, "project": "fanren-work", "contact_ref": "fanren-issue2-owner-plan-1",
            "task_id": "fanren-issue2-audio-qa-1", "unit_id": "audio-qa",
            "native_turn_id": "worker-final-turn-1",
            "owner_plan": self.plan, "executor": self.executor, "acceptor": self.owner,
            "due_at": "2030-11-05T18:00:00+08:00", "scope": {"mode": "inspect_existing", "new_audio": False},
            "inputs": [self.source], "deliverable_kind": "audio-qa-report", "deliverables": ["audio-qa-report"],
            "prior_refs": ["original-owner-plan"], "result_manifest_path": str(self.root / "saved-result.json"),
            "existing_dispatch": self.dispatch,
        }
        self.input_path = self.root / "request.json"

    @staticmethod
    def json_bytes(value):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

    @staticmethod
    def descriptor(path):
        data = path.read_bytes()
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def write_artifact(self, filename, data):
        path = self.root / filename
        path.write_bytes(data)
        return self.descriptor(path)

    def write_json(self, filename, value):
        path = self.root / filename
        path.write_bytes(self.json_bytes(value))
        return path

    def cli(self, command, *args, state=None, ok=True):
        result = subprocess.run([sys.executable, "-E", "-S", "-B", str(self.script),
                                 "--state", str(self.state if state is None else state), command, *map(str, args)],
                                cwd=self.repo, text=True, capture_output=True, timeout=15)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(result.stderr.strip(), "Refusal must explain the contract failure")
            return result
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIsInstance(output, dict)
        return output

    def initialize(self, request=None, state=None):
        path = self.write_json("request.json", self.request if request is None else request)
        return self.cli("init", "--input", path, state=state)

    def native_receipt(self, actor, turn_id, filename="worker-native-receipt.json", *, phase="final", text="Actual generated reply",
                       contact_ref=None):
        raw = {"thread": {"id": actor["thread"]}, "turns": [
            {"id": turn_id, "items": [
                {"type": "userMessage", "content": [{"type": "text", "text": "Original task: " + (
                    self.request["contact_ref"] if contact_ref is None else contact_ref)}]},
                {"type": "agentMessage", "phase": phase, "text": text}]}]}
        return self.write_artifact(filename, self.json_bytes(raw))

    def manifest(self, action, *, status="DELIVERED"):
        turn = self.request["native_turn_id"]
        return {"schema_version": 1, "task_id": self.request["task_id"], "unit_id": self.request["unit_id"],
                "action_id": action, "executor": deepcopy(self.executor), "deliverable_kind": self.request["deliverable_kind"],
                "status": status, "summary": "Inspected the existing fixture artifact and produced a report.",
                "native_turn_id": turn, "native_receipt": self.native_receipt(self.executor, turn),
                "artifacts": [self.write_artifact("qa-result.txt", b"Existing material inspected.\n")]}

    def collect(self, manifest, *, ok=True):
        path = self.write_json("incoming-result.json", manifest)
        return self.cli("collect", "--manifest", path, ok=ok)

    def decision(self, choice="accept"):
        turn = "owner-final-turn-1"
        saved = Path(self.request["result_manifest_path"])
        record = {"schema_version": 1, "task_id": self.request["task_id"], "unit_id": self.request["unit_id"],
                  "owner": deepcopy(self.owner), "choice": choice,
                  "result_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(), "native_turn_id": turn}
        claim = {key: record[key] for key in ("task_id", "unit_id", "result_sha256", "choice")}
        record["native_receipt"] = self.native_receipt(self.owner, turn, "owner-native-receipt.json",
                                                      text=json.dumps(claim))
        return record

    def decide(self, record, *, ok=True):
        path = self.write_json("owner-decision.json", record)
        return self.cli("decide", "--record", path, ok=ok)

    def test_adopted_native_acceptance_and_restart_preserve_one_handoff_per_task(self):
        before = Path(self.dispatch["path"]).read_bytes()
        first = self.initialize()
        self.assertEqual((first["status"], first["step"]), ("WAITING_RECEIPT", "native_handoff"))
        prepared = first["outputs"]["prepare"]
        self.assertEqual(prepared["mode"], "ADOPT_EXISTING")
        self.assertIs(prepared["dispatch_required"], False)
        self.assertEqual(prepared["existing_dispatch"], self.dispatch)
        action = first["action"]["id"]
        self.assertTrue(action)
        self.assertEqual(self.initialize()["action"]["id"], action)
        self.assertEqual(self.cli("status")["action"]["id"], action)
        self.assertEqual(Path(self.dispatch["path"]).read_bytes(), before)
        self.assertFalse(Path(self.request["result_manifest_path"]).exists())

    def test_distinct_units_have_independent_stable_actions(self):
        actions = []
        for index, unit in enumerate(("audio-qa", "role-assets", "post-production")):
            with self.subTest(unit=unit):
                request = deepcopy(self.request)
                request.update(task_id=f"fanren-issue2-{unit}", unit_id=unit,
                               result_manifest_path=str(self.root / f"saved-result-{index}.json"))
                state = self.root / f"unit-{index}.sqlite3"
                first = self.initialize(request, state)
                action = first["action"]["id"]
                self.assertEqual(self.initialize(request, state)["action"]["id"], action)
                actions.append(action)
        self.assertEqual(len(set(actions)), 3)

    def test_invalid_adopted_dispatch_cannot_create_a_handoff(self):
        for case in ("nonzero-exit", "wrong-kind", "wrong-agent", "wrong-pane"):
            with self.subTest(case=case):
                native = {"exit_code": 0, "stdout": {"result": {"type": "agent_prompted", "agent": {
                    "name": self.executor["name"], "pane_id": self.executor["pane"]}}}}
                if case == "nonzero-exit":
                    native["exit_code"] = 1
                elif case == "wrong-kind":
                    native["stdout"]["result"]["type"] = "blocked"
                elif case == "wrong-agent":
                    native["stdout"]["result"]["agent"]["name"] = "foreign-worker"
                else:
                    native["stdout"]["result"]["agent"]["pane_id"] = "w1:p99"
                native["stdout"] = json.dumps(native["stdout"])
                request = deepcopy(self.request)
                request["existing_dispatch"] = self.write_artifact(f"dispatch-{case}.json", self.json_bytes(native))
                path = self.write_json("invalid-request.json", request)
                self.cli("init", "--input", path, state=self.root / f"bad-{case}.sqlite3", ok=False)

    def test_wrong_result_associations_and_hashes_never_advance_the_handoff(self):
        waiting = self.initialize()
        action = waiting["action"]["id"]
        original = self.manifest(action)
        for case in ("task", "unit", "action", "executor", "deliverable", "artifact-hash", "artifact-size",
                     "receipt-hash", "receipt-thread", "receipt-turn", "manifest-turn", "contact", "not-final", "empty-final"):
            with self.subTest(case=case):
                manifest = deepcopy(original)
                if case in ("task", "unit", "action"):
                    manifest[{"task": "task_id", "unit": "unit_id", "action": "action_id"}[case]] = "foreign"
                elif case == "executor":
                    manifest["executor"]["thread"] = "foreign-thread"
                elif case == "deliverable":
                    manifest["deliverable_kind"] = "foreign-kind"
                elif case == "artifact-hash":
                    manifest["artifacts"][0]["sha256"] = "0" * 64
                elif case == "artifact-size":
                    manifest["artifacts"][0]["bytes"] += 1
                elif case == "receipt-hash":
                    manifest["native_receipt"]["sha256"] = "0" * 64
                else:
                    actor = deepcopy(self.executor)
                    if case == "receipt-thread":
                        actor["thread"] = "foreign-thread"
                    turn = "foreign-turn" if case in ("receipt-turn", "manifest-turn") else manifest["native_turn_id"]
                    if case == "manifest-turn":
                        manifest["native_turn_id"] = turn
                    manifest["native_receipt"] = self.native_receipt(actor, turn, f"receipt-{case}.json",
                        phase="commentary" if case == "not-final" else "final",
                        text="" if case == "empty-final" else "A generated response",
                        contact_ref="other-original-task" if case == "contact" else None)
                self.collect(manifest, ok=False)
                current = self.cli("status")
                self.assertEqual((current["status"], current["action"]["id"]), ("WAITING_RECEIPT", action))
                self.assertFalse(Path(self.request["result_manifest_path"]).exists())

    def test_partial_blocked_and_unknown_are_progress_without_collected_side_effects(self):
        waiting = self.initialize()
        action = waiting["action"]["id"]
        original_state = self.state.read_bytes()
        for status in ("PARTIAL", "BLOCKED", "UNKNOWN"):
            with self.subTest(status=status):
                current = self.collect(self.manifest(action, status=status))
                self.assertEqual((current["status"], current["action"]["id"]), ("WAITING_RECEIPT", action))
                self.assertTrue(current.get("progress"))
                progress = self.cli("status")["progress"]
                self.assertEqual(progress["status"], status)
                snapshot = Path(progress["manifest"]["path"])
                self.assertEqual(self.descriptor(snapshot), progress["manifest"])
                self.assertEqual(self.state.read_bytes(), original_state)
                self.assertFalse(Path(self.request["result_manifest_path"]).exists())

    def test_delivered_result_waits_for_real_owner_record_before_acceptance(self):
        action = self.initialize()["action"]["id"]
        result = self.collect(self.manifest(action))
        self.assertEqual((result["status"], result["step"]), ("WAITING_DECISION", "owner_acceptance"))
        self.assertIsNot(result.get("business_accepted"), True)
        self.assertIs(result["outputs"]["verify_result"]["business_accepted"], False)
        self.assertEqual(self.cli("status")["status"], "WAITING_DECISION")
        self.assertNotIn("progress", result)
        record = self.decision()
        accepted = self.decide(record)
        self.assertEqual((accepted["status"], accepted["step"]), ("FINISHED", "accepted"))
        self.assertEqual(self.decide(record)["status"], "FINISHED")

    def test_wrong_owner_identity_result_or_native_reply_cannot_decide(self):
        action = self.initialize()["action"]["id"]
        self.collect(self.manifest(action))
        original = self.decision()
        for case in ("owner", "task", "unit", "result", "receipt-thread", "not-final"):
            with self.subTest(case=case):
                record = deepcopy(original)
                if case == "owner":
                    record["owner"]["generation"] = 2
                elif case in ("task", "unit"):
                    record["task_id" if case == "task" else "unit_id"] = "foreign"
                elif case == "result":
                    record["result_sha256"] = "0" * 64
                else:
                    actor = deepcopy(self.owner)
                    if case == "receipt-thread":
                        actor["thread"] = "foreign-owner-thread"
                    record["native_receipt"] = self.native_receipt(actor, record["native_turn_id"],
                        f"owner-receipt-{case}.json", phase="commentary" if case == "not-final" else "final")
                self.decide(record, ok=False)
                self.assertEqual(self.cli("status")["status"], "WAITING_DECISION")

    def test_revise_and_hold_close_with_an_explicit_disposition_without_acceptance(self):
        for choice, step, disposition in (("revise", "revision_required", "REVISION_REQUIRED"), ("hold", "held", "HELD")):
            with self.subTest(choice=choice):
                self.state = self.root / f"{choice}.sqlite3"
                action = self.initialize()["action"]["id"]
                self.collect(self.manifest(action))
                result = self.decide(self.decision(choice))
                self.assertEqual((result["status"], result["step"]), ("FINISHED", step))
                self.assertEqual(result["disposition"], disposition)
                self.assertIsNone(result["action"])
                self.assertIsNot(result.get("business_accepted"), True)
                self.assertIs(result["outputs"]["verify_result"]["business_accepted"], False)

    def test_old_owner_final_and_conflicting_choices_do_not_authorize_acceptance(self):
        action = self.initialize()["action"]["id"]
        self.collect(self.manifest(action))
        record = self.decision()
        claim = {key: record[key] for key in ("task_id", "unit_id", "result_sha256", "choice")}
        cases = {
            "old-final": "Accepted an earlier unrelated unit.",
            "old-result": json.dumps({**claim, "result_sha256": "f" * 64}),
            "conflicting-choices": json.dumps({"decisions": [claim, {**claim, "choice": "hold"}]}),
        }
        for case, text in cases.items():
            with self.subTest(case=case):
                rejected = deepcopy(record)
                rejected["native_receipt"] = self.native_receipt(self.owner, record["native_turn_id"],
                                                                 f"owner-{case}.json", text=text)
                self.decide(rejected, ok=False)
                self.assertEqual(self.cli("status")["status"], "WAITING_DECISION")
        record["native_receipt"] = self.native_receipt(self.owner, record["native_turn_id"],
            "owner-final-answer.json", phase="final_answer", text=json.dumps({"decisions": [claim]}))
        self.assertEqual(self.decide(record)["disposition"], "ACCEPTED")

    def test_final_answer_phase_is_a_valid_worker_result(self):
        action = self.initialize()["action"]["id"]
        manifest = self.manifest(action)
        manifest["native_receipt"] = self.native_receipt(self.executor, manifest["native_turn_id"],
                                                        "worker-final-answer.json", phase="final_answer")
        self.assertEqual(self.collect(manifest)["status"], "WAITING_DECISION")

    def test_committed_collection_evidence_cannot_be_replaced_before_verification(self):
        action = self.initialize()["action"]["id"]
        manifest = self.manifest(action)
        original = self.json_bytes(manifest)
        saved = Path(self.request["result_manifest_path"])
        saved.write_bytes(self.json_bytes({**manifest, "summary": "Changed after collection"}))
        runner = self.repo / "workflows/episode-delivery/workflow.py"
        result = subprocess.run([sys.executable, "-E", "-S", "-B", str(runner), "--state", str(self.state),
            "receive", "--action", action, "--status", "COLLECTED", "--evidence", "sha256:" + hashlib.sha256(original).hexdigest()],
            cwd=self.repo, text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("committed collection receipt", result.stderr)
        status = self.cli("status")
        self.assertEqual((status["status"], status["step"]), ("RUNNABLE", "verify_result"))
        self.assertNotIn("verify_result", status["outputs"])
        result = subprocess.run([sys.executable, str(runner), "--state", str(self.state), "resume"],
                                cwd=self.repo, text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)

    def test_entrypoint_changes_and_changed_artifacts_cannot_import_acceptance(self):
        action = self.initialize()["action"]["id"]
        manifest = self.manifest(action)
        original_source = self.script.read_bytes()
        self.script.write_bytes(original_source + b"\n# Changed helper revision\n")
        self.collect(manifest, ok=False)
        self.script.write_bytes(original_source)
        self.collect(manifest)
        record = self.decision()
        for artifact in (self.source, manifest["artifacts"][0]):
            with self.subTest(path=artifact["path"]):
                path = Path(artifact["path"])
                original = path.read_bytes()
                path.write_bytes(original + b"changed\n")
                self.decide(record, ok=False)
                self.assertEqual(self.cli("status")["status"], "WAITING_DECISION")
                path.write_bytes(original)
        self.assertEqual(self.decide(record)["status"], "FINISHED")


if __name__ == "__main__":
    unittest.main()
