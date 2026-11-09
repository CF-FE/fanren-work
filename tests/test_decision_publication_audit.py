"""Exercise the audit checkpoint's original evidence and interruption boundaries."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "workflows/decision-publication-audit/workflow.py"
ENTRY = ROOT / "scripts/decision_publication_audit.py"


class AuditBoundaryTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.directory = Path(work.name)
        self.state = self.directory / "unit.sqlite3"
        self.runner = runpy.run_path(str(FLOW))
        _, source, raw, self.version = self.runner["project_code"](None)
        self.definition, self.operations = self.runner["project_definition"](source, raw)
        files = (ENTRY, ROOT / "scripts/episode_delivery.py", ROOT / "workflows/episode-delivery/definition.py")
        self.executor = {"name": "worker", "session": "mac", "pane": "w1:p8", "thread": "worker-thread"}
        self.owner = {"name": "owner", "session": "mac", "pane": "w1:p4", "thread": "owner-thread", "generation": 1}
        self.input = {
            "project": "fanren-work", "task_id": "task", "unit_id": "unit", "contact_ref": "contact",
            "deliverable_kind": "report", "acceptor": self.owner, "inputs": [],
            "source_files": {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in files},
            "dispatch_binding_path": str(self.directory / "binding.json"),
            "result_manifest_path": str(self.directory / "result.json"),
        }
        for field in ("owner_plan", "decision_context", "runtime_inputs"):
            self.input[field] = self.artifact(field, {"project": "fanren-work", "task_id": "task", "unit_id": "unit",
                "consumer": {"release": str(self.directory), "python": sys.executable}, "publisher": {}})
        self.cli(FLOW, "start", "--task", "task", "--input", self.artifact("input", self.input)["path"])
        with sqlite3.connect(self.state) as db:
            run = json.loads(db.execute("SELECT data FROM checkpoint").fetchone()[0])
            run["decision_integration"] = {
                "requests": {
                    "route": {"request": {"preset": "workflow_next_action", "subject_ref": {"unit_id": "adapter"}},
                              "decision": {"candidate_id": "receipt_first", "evidence": "decision:route"}},
                    "model": {"request": {"preset": "role_model_selection", "subject_ref": {"unit_id": "adapter"}},
                              "model": {"execution_ref": {"ids": {"turn_id": "turn", "thread_id": "worker-thread"}},
                                        "effective_model": {"configuration_status": "confirmed"},
                                        "application_status": "not_applied"}},
                },
                "actions": {}, "results": {}, "events": {},
                "launches": {"adapter": {"request_id": "model", "thread_id": "worker-thread",
                             "target": {"agent": "worker", "session": "mac", "pane_id": "w1:p8"}}},
            }
            db.execute("UPDATE checkpoint SET data=?", (json.dumps(run),))
        self.action = self.cli(FLOW, "decide", "--step", "audit_route", "--choice", "receipt_first",
                               "--evidence", "decision:route")["action"]["id"]

    def artifact(self, name, content):
        path = self.directory / name
        raw = json.dumps(content).encode()
        path.write_bytes(raw)
        return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}

    def cli(self, script, *args, error=None):
        flags = ["--workflow", str(FLOW)] if script == ENTRY else []
        result = subprocess.run([sys.executable, "-B", str(script), "--state", str(self.state), *flags, *args],
                                capture_output=True, text=True, timeout=10)
        if error:
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(error, result.stderr)
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def native(self, name, actor, turn, text):
        marker = "contact\nWORKFLOW_TASK_ID=task\nWORKFLOW_ACTION_ID=" + self.action
        return self.artifact(name, {"thread": {"id": actor["thread"]}, "turns": [{"id": turn, "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": marker}]},
            {"type": "agentMessage", "phase": "final", "text": text}]}]})

    def result(self):
        native = self.native("worker", self.executor, "turn", "Finished audit")
        core = {"schema_version": 1, "task_id": "task", "unit_id": "unit", "executor": self.executor,
                "action_id": self.action, "native_turn_id": "turn"}
        dispatch = self.artifact("dispatch", {"exit_code": 0, "stdout": json.dumps({"result": {
            "type": "agent_prompted", "agent": {"name": "worker", "pane_id": "w1:p8"}}})})
        self.artifact("binding.json", dict(core, dispatch_receipt=dispatch, native_request=native))
        return self.artifact("result.json", dict(core, status="DELIVERED", deliverable_kind="report",
            summary="Audit complete", native_receipt=native, artifacts=[self.artifact("report", {"ok": True})]))

    def commit_only(self, **fields):
        # Interrupt after the real committed import, before the runner calls advance().
        args = argparse.Namespace(state=str(self.state), **fields)
        with sqlite3.connect(self.state) as db:
            self.runner["import_record"](db, ROOT, self.definition, self.version, self.operations, args)
        self.assertEqual(self.cli(FLOW, "status")["status"], "RUNNABLE")

    def owner_record(self, result):
        claim = {"task_id": "task", "unit_id": "unit", "choice": "accept", "result_sha256": result["sha256"]}
        owner = self.artifact("owner", dict(claim, schema_version=1, owner=self.owner, native_turn_id="owner-turn",
            native_receipt=self.native("owner-native", self.owner, "owner-turn", json.dumps(claim))))
        (self.directory / (self.state.name + ".owner-" + owner["sha256"] + ".json")).write_bytes(
            Path(owner["path"]).read_bytes())
        return owner

    def test_real_receipt_stays_collected_while_model_is_unconfirmed(self):
        result = self.result()
        with sqlite3.connect(self.state) as db:
            run = json.loads(db.execute("SELECT data FROM checkpoint").fetchone()[0])
            model = run["decision_integration"]["requests"]["model"]["model"]
            model.pop("execution_ref")
            model["application_status"] = "unknown"
            model["effective_model"] = {"configuration_status": "unconfirmed"}
            db.execute("UPDATE checkpoint SET data=?", (json.dumps(run),))
        collected = self.cli(FLOW, "receive", "--action", self.action, "--status", "COLLECTED",
                             "--evidence", "sha256:" + result["sha256"])
        self.assertEqual(collected["step"], "owner_acceptance")
        owner = self.owner_record(result)
        self.cli(FLOW, "decide", "--step", "owner_acceptance", "--choice", "accept",
                 "--evidence", "sha256:" + owner["sha256"], error="actual model configuration is unconfirmed")
        self.assertEqual(self.cli(FLOW, "status")["receipts"], collected["receipts"])

    def test_rejects_unbacked_native_collection_and_wrong_model_turn(self):
        self.cli(FLOW, "receive", "--action", self.action, "--status", "COLLECTED", "--evidence", "arbitrary",
                 error="result.json")
        self.result()
        self.cli(ENTRY, "model-reconcile", "--request-id", "model", "--rollout", "unused",
                 "--turn-id", "preflight", error="another native turn")
        self.assertEqual(self.cli(FLOW, "status")["status"], "WAITING_RECEIPT")

    def test_reconcile_resumes_receipt_and_owner_commits(self):
        result = self.result()
        self.commit_only(command="receive", status="COLLECTED", action=self.action,
                         evidence="sha256:" + result["sha256"])
        result_path = Path(result["path"])
        original_result = result_path.read_bytes()
        result_path.unlink()
        self.cli(ENTRY, "reconcile", error="result.json")
        self.assertEqual(self.cli(FLOW, "status")["step"], "verify_result")
        result_path.write_bytes(original_result)
        self.assertEqual(self.cli(ENTRY, "reconcile")["step"], "owner_acceptance")
        result_path.unlink()
        self.cli(ENTRY, "reconcile", error="original collected result manifest is missing")
        result_path.write_bytes(original_result)
        status = self.cli(FLOW, "status")
        self.assertEqual(status["decision_evaluation"], "owner_only")
        self.assertNotIn("decision_integration_version", status)
        self.cli(FLOW, "decide", "--step", "owner_acceptance", "--choice", "accept", "--evidence", "arbitrary",
                 error="invalid owner evidence")
        owner = self.owner_record(result)
        report = self.directory / "report"
        original_report = report.read_bytes()
        report.write_bytes(b'{"ok":0}')
        self.cli(FLOW, "decide", "--step", "owner_acceptance", "--choice", "accept",
                 "--evidence", "sha256:" + owner["sha256"], error="artifact")
        self.assertEqual(self.cli(FLOW, "status")["step"], "owner_acceptance")
        report.write_bytes(original_report)
        self.commit_only(command="decide", step="owner_acceptance", choice="accept",
                         expected_state_digest=None, evidence="sha256:" + owner["sha256"])
        self.assertEqual(self.cli(ENTRY, "reconcile")["status"], "FINISHED")


if __name__ == "__main__":
    unittest.main()
