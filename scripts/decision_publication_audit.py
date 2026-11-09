"""Project-owned collection and owner-acceptance entrypoint for the new audit workflow."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys

from episode_delivery import ROOT, definition_functions, save_exact


def invoke(script, *args, env, python=sys.executable):
    done = subprocess.run([python, "-E", "-B", "-s", str(script), *map(str, args)],
                          env=env, capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise ValueError(done.stderr.strip() or "workflow command failed")
    return json.loads(done.stdout)


def load_run(workflow, state, env):
    invoke(workflow, "--state", state, "status", env=env)
    with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()
    run = json.loads(row[0])
    if run["project"] != "fanren-work" or run["workflow"] != "decision-publication-audit":
        raise ValueError("wrong project workflow")
    return run


def execute(args):
    workflow = args.workflow.resolve(strict=True)
    state = args.state.resolve(strict=True)
    if workflow != ROOT / "workflows/decision-publication-audit/workflow.py" or state.is_relative_to(ROOT):
        raise ValueError("use the original audit workflow and a private checkpoint")
    env = {key: value for key, value in os.environ.items() if not key.startswith("DECISION_")}
    run = load_run(workflow, state, env)
    definition = runpy.run_path(str(workflow.with_name("definition.py")))
    definition["verify_sources"](ROOT, run)
    if args.command == "reconcile" and run["status"] == "RUNNABLE":
        invoke(workflow, "--state", state, "resume", env=env)
        run = load_run(workflow, state, env)
    data = run["input"]
    functions = definition_functions()
    require = functions["require"]
    runtime = json.loads(functions["artifact_bytes"](data["runtime_inputs"]))
    require((runtime["project"], runtime["task_id"], runtime["unit_id"]) ==
            (run["project"], run["task"], data["unit_id"]), "release bundle identity mismatch")
    consumer = Path(runtime["consumer"]["release"]) / "app/scripts"
    consumer_python = runtime["consumer"]["python"]

    def call(tool, *command):
        config_path = Path(runtime["publisher"]["config_ref"]).resolve(strict=True)
        require(config_path.stat().st_mode & 0o077 == 0, "private publication configuration required")
        config = json.loads(config_path.read_bytes())
        require(config["project_id"] == config["bank_id"] == "fanren-work", "wrong publication project")
        publisher_python = Path(runtime["publisher"]["python"])
        require(publisher_python.is_file(), "fixed publisher interpreter required")
        call_env = dict(env, DECISION_SERVICE_URL=config["decision_service_url"],
                        DECISION_SERVICE_TOKEN=config["decision_service_token"],
                        DECISION_OUTCOME_PYTHON=str(publisher_python), DECISION_OUTCOME_CONFIG=str(config_path))
        return invoke(consumer / tool, "--workflow", workflow, "--state", state, *command,
                      env=call_env, python=consumer_python)

    def feedback(*command):
        return call("project_workflow_decision.py", *command)

    if args.command == "status":
        return invoke(workflow, "--state", state, "status", env=env)

    if args.command == "choose":
        if args.request_id:
            entry = run["decision_integration"]["requests"][args.request_id]
            require(entry["request"]["preset"] == "workflow_next_action"
                    and entry["request"]["subject_ref"]["step"] == "audit_route",
                    "only the original audit route request may be recovered")
            if run["step"] == "owner_acceptance":
                return feedback("get", "--request-id", args.request_id)
            return feedback("choose", "--request-id", args.request_id)
        require(run["step"] == "audit_route" and run["status"] == "WAITING_DECISION",
                "only the owner-released operational audit route may use Decision Service")
        context_path = Path(data["decision_context"]["path"])
        functions["artifact_bytes"](data["decision_context"])
        return feedback("choose", "--recall", "skip", "--context", context_path)

    if args.command == "reconcile" and not Path(data["result_manifest_path"]).is_file():
        require(not any(item["status"] == "COLLECTED" for history in run["receipts"].values() for item in history),
                "original collected result manifest is missing")
        return feedback("reconcile")

    integration = run["decision_integration"]
    decision_unit = definition["decision_unit"](run)
    if args.command == "model-apply":
        require(run["step"] == "native_handoff" and run["status"] == "WAITING_RECEIPT",
                "model selection requires the original pending handoff")
        return call("herdr_model_selection.py", "apply", "--unit-id", decision_unit,
                    "--binding", args.binding, "--selection", args.selection)
    source, action = definition["delivery_source"](run, decision_unit)
    binding = Path(data["dispatch_binding_path"]).resolve()
    manifest_path = Path(data["result_manifest_path"]).resolve()
    require(not binding.is_relative_to(ROOT) and not manifest_path.is_relative_to(ROOT),
            "native receipts must stay outside the repository")

    if args.command == "model-reconcile":
        launch = integration["launches"][decision_unit]
        require(args.request_id == launch["request_id"], "model request is for another original launch")
        request = integration["requests"][args.request_id]["request"]
        require(request["preset"] == "role_model_selection" and request["subject_ref"]["unit_id"] == decision_unit,
                "model request is for another original unit")
        native_turn = functions["validate_binding"](source, json.loads(binding.read_bytes()), action)
        require(args.turn_id == native_turn, "model readback is for another native turn")
        return call("herdr_model_selection.py", "reconcile", "--request-id", args.request_id,
                    "--rollout", args.rollout, "--turn-id", args.turn_id)

    if args.command == "bind":
        raw = args.record.read_bytes()
        functions["validate_binding"](source, json.loads(raw), action)
        save_exact(binding, raw)
        return {"action_id": action, "state": "bound"}

    raw = (args.record if args.command == "collect" else manifest_path).read_bytes()
    result_hash = sha256(raw).hexdigest()
    result_ref = "sha256:" + result_hash
    definition["verify_delivery"](ROOT, run, raw)
    if args.command == "collect":
        save_exact(manifest_path, raw)

    collected = [item["evidence"] for item in run["receipts"].get(action, []) if item["status"] == "COLLECTED"]
    if args.command in {"collect", "reconcile"}:
        invoke(workflow, "--state", state, "receive", "--action", action, "--status", "COLLECTED",
               "--evidence", result_ref, env=env)
    else:
        require(collected == [result_ref], "native collection does not match the original result")

    owner_decision = run["decisions"].get("owner_acceptance")
    if args.command == "decide":
        raw_owner = args.record.read_bytes()
        owner = json.loads(raw_owner)
        require(owner["choice"] in ("accept", "revise", "hold"), "invalid owner choice")
        definition["verify_owner"](ROOT, run, raw_owner, result_hash, owner["choice"])
        owner_hash = sha256(raw_owner).hexdigest()
        accepted = {"choice": owner["choice"], "evidence": "sha256:" + owner_hash}
        require(owner_decision is None or owner_decision == accepted, "owner decision already recorded")
        save_exact(state.parent / (state.name + ".owner-" + owner_hash + ".json"), raw_owner)
        invoke(workflow, "--state", state, "decide", "--step", "owner_acceptance", "--choice",
               accepted["choice"], "--evidence", accepted["evidence"], env=env)
        owner_decision = accepted

    native = invoke(workflow, "--state", state, "status", env=env)
    try:
        outcome = integration["results"].get(decision_unit, {})
        if outcome.get("execution_status") != "completed" or outcome.get("result_refs") != [result_ref]:
            published = feedback("record-result", "--unit-id", decision_unit, "--status", "completed",
                                 "--result-ref", result_ref, "--evidence", result_ref)
        else:
            published = feedback("reconcile")
        if owner_decision:
            evidence = owner_decision["evidence"]
            quality = {"accept": "passed", "revise": "failed", "hold": "pending"}[owner_decision["choice"]]
            owner_digest = evidence.removeprefix("sha256:")
            frozen_owner = state.parent / (state.name + ".owner-" + owner_digest + ".json")
            require(sha256(frozen_owner.read_bytes()).hexdigest() == owner_digest, "stored owner receipt changed")
            if outcome.get("quality_status") != quality or outcome.get("evidence_refs") != [evidence]:
                published = feedback("quality", "--unit-id", decision_unit, "--status", quality,
                                     "--evidence", evidence)
    except (OSError, ValueError, KeyError):
        published = {"state": "pending", "reason": "original_feedback_not_confirmed"}
    return {"status": native["status"], "step": native["step"], "feedback": published}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("workflow", "state"):
        parser.add_argument("--" + key, required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("bind", "collect", "decide"):
        commands.add_parser(name).add_argument("--record", required=True, type=Path)
    commands.add_parser("status")
    commands.add_parser("choose").add_argument("--request-id")
    model = commands.add_parser("model-apply")
    model.add_argument("--binding", required=True, type=Path)
    model.add_argument("--selection", required=True, type=Path)
    model = commands.add_parser("model-reconcile")
    model.add_argument("--request-id", required=True)
    model.add_argument("--rollout", required=True, type=Path)
    model.add_argument("--turn-id", required=True)
    commands.add_parser("reconcile")
    try:
        print(json.dumps(execute(parser.parse_args()), ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
