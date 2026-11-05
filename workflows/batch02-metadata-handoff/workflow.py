"""Project-owned workflow. Edit OPERATIONS for local, repeatable program steps."""
import argparse
from contextlib import closing, redirect_stdout
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def relative_file(root, name):
    require(isinstance(name, str) and name.strip(), "expected a project-relative file path")
    path = Path(name)
    require(not path.is_absolute() and not PureWindowsPath(name).anchor and ".." not in path.parts,
            f"path must stay inside the project: {name}")
    absolute = (root / path).resolve()
    require(absolute != root and absolute.is_relative_to(root), f"path escapes project: {name}")
    return absolute


def verify_files(root, run):
    """Hash each input file in order. A missing file is a review finding, not a failed batch."""
    data = run["input"]
    require(isinstance(data, dict) and isinstance(data.get("items"), list), "verify_files expects an items array")
    seen = set()
    items = []
    for item in data["items"]:
        require(isinstance(item, dict), "verify_files expects object entries")
        item_id, name, expected = (item.get(k) for k in ("id", "path", "sha256"))
        require(isinstance(item_id, str) and item_id.strip() and item_id not in seen, "missing or duplicate item id")
        require(isinstance(expected, str) and re.fullmatch(r"[a-fA-F0-9]{64}", expected), "invalid expected SHA-256")
        seen.add(item_id)
        path = relative_file(root, name)
        try:
            # A named pipe must not block the verifier; special files have no asset hash.
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        except FileNotFoundError:
            actual = None
        else:
            with os.fdopen(fd, "rb") as stream:
                require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), f"asset is not a regular file: {name}")
                hash_ = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hash_.update(block)
                actual = hash_.hexdigest()
        if actual is None:
            status = "MISSING"
        elif actual == expected.lower():
            status = "MATCH"
        else:
            status = "MISMATCH"
        items.append({"id": item_id, "path": name, "expected_sha256": expected.lower(),
                      "actual_sha256": actual, "status": status})
    ready = bool(items) and all(item["status"] == "MATCH" for item in items)
    return {"outcome": "ready" if ready else "needs_review", "items": items}


# Local functions take (project_root: Path, run: dict) and return JSON data.
# Keep external submissions in a handoff step; local functions may be retried after a crash.
OPERATIONS = {"verify_files": verify_files}


def project_code(requested_root):
    script = Path(__file__).resolve()
    root = script.parents[2]
    require(script.parent.parent.name == "workflows" and script.name == "workflow.py",
            "run the generated PROJECT/workflows/<id>/workflow.py")
    require(requested_root is None or Path(requested_root).resolve() == root, "project root does not own this workflow")
    definition_file = script.with_name("definition.py")
    source = definition_file.read_bytes()
    version = digest({script.name: hashlib.sha256(script.read_bytes()).hexdigest(),
                      definition_file.name: hashlib.sha256(source).hexdigest()})
    return root, definition_file, source, version


def project_definition(path, source):
    namespace = {"__name__": "definition", "__file__": str(path)}
    # Load these exact bytes; a stale timestamp-based .pyc must never select the graph.
    with redirect_stdout(sys.stderr):
        exec(compile(source, str(path), "exec"), namespace)
    definition = namespace["DEFINITION"]
    require(definition["workflow"] == path.parent.name and definition["version"] == 1, "workflow identity mismatch")
    custom = namespace.get("OPERATIONS", {})
    require(isinstance(custom, dict) and all(isinstance(key, str) and key.strip() and callable(fn)
                                              for key, fn in custom.items()), "invalid project OPERATIONS")
    require(not custom.keys() & OPERATIONS.keys(), "project operation conflicts with a built-in name")
    return definition, {**OPERATIONS, **custom}


def next_step(run, definition, target):
    require(target in definition["steps"], f"undefined next step: {target}")
    run["completed_steps"].append(run["step"])
    require(target not in run["completed_steps"], f"cycle at {target}")
    run.update(step=target, status="RUNNABLE", action=None, decision=None)


def advance_step(root, definition, operations, run):
    step_id = run["step"]
    step = definition["steps"][step_id]
    kind = step["kind"]
    if kind == "program":
        operation = step["operation"]
        require(operation in operations, f"unknown project operation: {operation}")
        with redirect_stdout(sys.stderr):
            output = operations[operation](root, deepcopy(run))
        run["outputs"][step_id] = output
        require(("next" in step) != ("routes" in step), "program requires either next or routes")
        if "routes" in step:
            outcome = output.get("outcome") if isinstance(output, dict) else None
            require(isinstance(outcome, str) and outcome in step["routes"], f"unmapped outcome: {outcome}")
            target = step["routes"][outcome]
        else:
            target = step["next"]
        next_step(run, definition, target)
    elif kind == "decision":
        run.update(status="WAITING_DECISION", decision={"question": step["question"], "choices": step["choices"]})
    elif kind == "handoff":
        identity = [run["project"], run["workflow"], run["task"], step_id]
        run.update(status="WAITING_RECEIPT", action={"id": digest(identity), "step": step_id,
                   "project": run["project"], "workflow": run["workflow"], "task": run["task"],
                   "instruction": step["instruction"], "memory": run["memory"]})
    elif kind == "end":
        run["status"] = "FINISHED"
    else:
        raise ValueError(f"unknown step kind: {kind}")


def advance(db, root, definition, version, operations):
    # One committed transition per transaction. The same checkpoint can be opened by
    # concurrent workers. A crash does not erase an already committed decision.
    while True:
        with db:
            db.execute("BEGIN IMMEDIATE")
            run = read_run(db, version)
            if run["status"] != "RUNNABLE":
                return run
            advance_step(root, definition, operations, run)
            save_run(db, run)


def read_run(db, version):
    row = db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()
    require(row is not None, "checkpoint has no run")
    run = json.loads(row[0])
    require(run["source_sha256"] == version, "workflow source version conflict; restore the original project revision")
    return run


def save_run(db, run):
    db.execute("INSERT INTO checkpoint(id,data) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
               (encoded(run),))


def start(db, root, definition, version, operations, task, data):
    require(isinstance(task, str) and task.strip(), "empty original task")
    input_hash = digest(data)
    with db:
        db.execute("BEGIN IMMEDIATE")
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        require(not tables or tables == [("checkpoint",)], "state belongs to another application")
        db.execute("CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
        if db.execute("SELECT 1 FROM checkpoint WHERE id=1").fetchone():
            run = read_run(db, version)
            require(run["task"] == task and run["input_sha256"] == input_hash, "task or input conflict")
        else:
            memory = relative_file(root, definition["memory"])
            require(memory.is_file(), "project memory file missing")
            run = {
                "task": task, "project": definition["project"], "workflow": definition["workflow"],
                "source_sha256": version, "memory": definition["memory"],
                "memory_sha256": hashlib.sha256(memory.read_bytes()).hexdigest(),
                "input": data, "input_sha256": input_hash, "step": definition["start"], "status": "RUNNABLE",
                "outputs": {}, "decisions": {}, "receipts": {}, "decision": None, "action": None, "completed_steps": [],
            }
            advance_step(root, definition, operations, run)
            save_run(db, run)


def import_record(db, definition, version, args):
    require(args.evidence.strip(), "empty evidence reference")
    with db:
        db.execute("BEGIN IMMEDIATE")
        run = read_run(db, version)
        if args.command == "decide":
            decision = {"choice": args.choice, "evidence": args.evidence}
            previous = run["decisions"].get(args.step)
            if previous is not None:
                require(previous == decision, "decision conflicts with the recorded choice or evidence")
                return
            require(run["status"] == "WAITING_DECISION" and run["step"] == args.step, "not the pending decision")
            choices = run["decision"]["choices"]
            require(args.choice in choices, "choice not allowed")
            run["decisions"][args.step] = decision
            next_step(run, definition, choices[args.choice])
        else:
            record = {"status": args.status, "evidence": args.evidence}
            history = run["receipts"].get(args.action, [])
            if record in history:
                return
            require(run["status"] in ("WAITING_RECEIPT", "UNKNOWN") and run["action"]["id"] == args.action,
                    "action does not match the pending handoff")
            require(all(old["status"] != args.status for old in history), "conflicting receipt evidence")
            run["receipts"].setdefault(args.action, []).append(record)
            if args.status == "UNKNOWN":
                run["status"] = "UNKNOWN"
            else:
                next_step(run, definition, definition["steps"][run["step"]]["next"])
        save_run(db, run)


def execute(args):
    root, definition_file, definition_bytes, version = project_code(args.project_root)
    path = Path(args.state).resolve()
    require(not path.is_relative_to(root), "store the private checkpoint outside the project")
    mode = "ro" if args.command == "status" else "rw"
    if args.command == "start":
        data = json.loads(Path(args.input).read_bytes())
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            pass
    else:
        require(path.is_file(), "checkpoint does not exist")
    with closing(sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=30)) as db:
        if args.command == "status":
            return read_run(db, version)  # A query does not import or invoke project operations.
        if args.command != "start" or db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone():
            # Reject a different revision before executing even its module-level definitions.
            read_run(db, version)
        definition, operations = project_definition(definition_file, definition_bytes)
        if args.command == "start":
            start(db, root, definition, version, operations, args.task, data)
        elif args.command in ("decide", "receive"):
            import_record(db, definition, version, args)
        return advance(db, root, definition, version, operations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="private SQLite checkpoint outside the project, one per original task")
    parser.add_argument("--project-root", help="verify the project root (otherwise derived from this script)")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("start")
    new.add_argument("--task", required=True)
    new.add_argument("--input", required=True)
    commands.add_parser("status")
    commands.add_parser("resume")
    decide = commands.add_parser("decide")
    decide.add_argument("--step", required=True)
    decide.add_argument("--choice", required=True)
    decide.add_argument("--evidence", required=True)
    receive = commands.add_parser("receive")
    receive.add_argument("--action", required=True)
    receive.add_argument("--status", required=True, choices=("UNKNOWN", "COLLECTED"))
    receive.add_argument("--evidence", required=True)
    try:
        run = execute(parser.parse_args())
        result = {k: v for k, v in run.items() if k not in ("input", "completed_steps")}
        if result["action"]:
            result["action"] = {**result["action"], "outputs": run["outputs"], "decisions": run["decisions"]}
        print(encoded(result))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, SyntaxError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
