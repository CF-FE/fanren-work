"""Reconcile existing Herdr actions with project workflow checkpoints; never dispatch."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "workflows" / "episode-delivery" / "workflow.py"
DEFINITION = FLOW.with_name("definition.py")


def run_workflow(state, *arguments):
    result = subprocess.run([sys.executable, str(FLOW), "--state", str(state), *arguments],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip())
    return json.loads(result.stdout)


def load_run(state):
    # First have the unchanged runner check its source signature without loading operations.
    run_workflow(state, "status")
    with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)) as db:
        run = json.loads(db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()[0])
    if run["outputs"]["prepare"]["entrypoint_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("project entrypoint version conflict; restore the original project revision")
    return run


def definition_functions():
    namespace = {"__name__": "episode_delivery_definition", "__file__": str(DEFINITION)}
    exec(compile(DEFINITION.read_bytes(), str(DEFINITION), "exec"), namespace)
    return namespace


def save_exact(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("stored evidence conflicts with the original bytes")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def status_with_progress(state):
    result = run_workflow(state, "status")
    pointer = state.parent / (state.name + ".progress.json")
    if result["step"] == "native_handoff" and pointer.exists():
        progress = json.loads(pointer.read_bytes())
        snapshot = Path(progress["manifest"]["path"]).read_bytes()
        if len(snapshot) != progress["manifest"]["bytes"] or hashlib.sha256(snapshot).hexdigest() != progress["manifest"]["sha256"]:
            raise ValueError("saved progress bytes mismatch")
        result["progress"] = progress
    return result


def save_progress(state, raw, manifest):
    hash_ = hashlib.sha256(raw).hexdigest()
    snapshot = state.parent / (state.name + ".progress") / (hash_ + ".json")
    save_exact(snapshot, raw)
    progress = {"status": manifest["status"], "summary": manifest["summary"],
                "observed_at": datetime.now(timezone.utc).isoformat(), "business_accepted": False,
                "manifest": {"path": str(snapshot), "bytes": len(raw), "sha256": hash_}}
    descriptor, temporary = tempfile.mkstemp(prefix=".progress-", dir=state.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(progress, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state.parent / (state.name + ".progress.json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(args):
    state = Path(args.state).resolve()
    if state.is_relative_to(ROOT):
        raise ValueError("private state must be outside the repository")
    if args.command == "init":
        data = json.loads(Path(args.input).read_bytes())
        result_path = Path(data["result_manifest_path"]).resolve()
        if result_path.is_relative_to(ROOT):
            raise ValueError("private result manifest must be outside the repository")
        state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return run_workflow(state, "start", "--task", data["task_id"], "--input", args.input)
    if args.command == "status":
        return status_with_progress(state)

    run = load_run(state)
    functions = definition_functions()
    data = run["input"]
    if args.command == "collect":
        raw = Path(args.manifest).read_bytes()
        manifest = json.loads(raw)
        action_id = hashlib.sha256(json.dumps(
            [run["project"], run["workflow"], run["task"], "native_handoff"],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
        complete = functions["validate_result"](data, manifest, action_id)
        if not complete:
            if run["step"] == "native_handoff":
                save_progress(state, raw, manifest)
            return status_with_progress(state)
        path = Path(data["result_manifest_path"]).resolve()
        if path.is_relative_to(ROOT):
            raise ValueError("private result manifest must be outside the repository")
        save_exact(path, raw)
        evidence = "sha256:" + hashlib.sha256(raw).hexdigest()
        return run_workflow(state, "receive", "--action", action_id, "--status", "COLLECTED", "--evidence", evidence)

    record_raw = Path(args.record).read_bytes()
    record = json.loads(record_raw)
    evidence_hash = hashlib.sha256(record_raw).hexdigest()
    previous = run["decisions"].get("owner_acceptance")
    if previous == {"choice": record["choice"], "evidence": "sha256:" + evidence_hash}:
        return status_with_progress(state)
    functions["require"](record["schema_version"] == 1, "unsupported decision schema")
    for key in ("task_id", "unit_id"):
        functions["require"](record[key] == data[key], f"decision {key} mismatch")
    functions["require"](record["owner"] == data["acceptor"], "decision owner mismatch")
    functions["require"](record["choice"] in ("accept", "revise", "hold"), "invalid owner choice")
    verified = run["outputs"].get("verify_result")
    functions["require"](verified is not None, "result has not been verified")
    functions["require"](record["result_sha256"] == verified["result_sha256"], "decision result mismatch")
    if record["choice"] == "accept":
        current = functions["verify_result"](ROOT, run)
        functions["require"](current["result_sha256"] == verified["result_sha256"], "accepted result bytes changed")
    functions["verify_owner_claim"](record, data["acceptor"])
    save_exact(state.parent / (state.name + ".owner-" + evidence_hash + ".json"), record_raw)
    return run_workflow(state, "decide", "--step", "owner_acceptance", "--choice", record["choice"],
                        "--evidence", "sha256:" + evidence_hash)


def describe(result):
    result["business_accepted"] = result["status"] == "FINISHED" and result["step"] == "accepted"
    result["disposition"] = {"accepted": "ACCEPTED", "revision_required": "REVISION_REQUIRED",
                             "held": "HELD"}.get(result["step"], "PENDING")
    if result["step"] == "native_handoff":
        result["next_action"] = "Reconcile the existing native action; do not dispatch again."
    elif result["status"] == "WAITING_DECISION":
        result["next_action"] = "Collect the incumbent owner's native decision for this unit."
    elif result["step"] in ("revision_required", "held"):
        result["next_action"] = "This unit is disposed without acceptance; the coordinator follows the owner for a bounded successor, preserving original references."
    elif result["status"] == "RUNNABLE":
        result["next_action"] = "Restore the original evidence and reconcile this checkpoint; the unit is not closed."
    else:
        result["next_action"] = "This unit is closed; consult the owner for any next unit."
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--input", required=True)
    commands.add_parser("status")
    collect = commands.add_parser("collect")
    collect.add_argument("--manifest", required=True)
    decide = commands.add_parser("decide")
    decide.add_argument("--record", required=True)
    try:
        print(json.dumps(describe(execute(parser.parse_args())), ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
