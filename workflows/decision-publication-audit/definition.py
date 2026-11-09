# coding: utf-8
"""Project-owned audit boundaries and branch operations."""
from hashlib import sha256
import json
from pathlib import Path
import re
import sys


def episode_validators(root):
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from episode_delivery import definition_functions
    finally:
        sys.path.remove(str(scripts))
    return definition_functions()


def verify_sources(root, run):
    files = ("scripts/decision_publication_audit.py", "scripts/episode_delivery.py",
             "workflows/episode-delivery/definition.py")
    actual = {path: sha256((root / path).read_bytes()).hexdigest() for path in files}
    if actual != run["input"]["source_files"]:
        raise ValueError("restore the original audit sources")
    return actual


def prepare(root, run):
    sources = verify_sources(root, run)
    funcs = episode_validators(root)
    data = run["input"]
    funcs["require"](data["project"] == run["project"] and data["task_id"] == run["task"],
                     "audit project or task mismatch")
    verify_inputs(funcs, data)
    funcs["validate_identity"](data["acceptor"], owner=True)
    for key in ("dispatch_binding_path", "result_manifest_path"):
        path = Path(data[key])
        funcs["require"](path.is_absolute() and not path.resolve().is_relative_to(root),
                         "native evidence must be outside the repository")
    return {"unit_id": data["unit_id"], "source_files": sources}


def verify_inputs(funcs, data):
    for field in ("owner_plan", "decision_context", "runtime_inputs"):
        funcs["artifact_bytes"](data[field])
    for reference in data["inputs"]:
        funcs["artifact_bytes"](reference)


def record_order(root, run):
    order = ["release_install_review_receipts", "native_execution_and_publication_trace"]
    if run["step"] == "trace_first":
        order.reverse()
    return {"audit_order": order}


def decision_unit(run):
    route = run["decisions"]["audit_route"]
    matches = [entry["request"]["subject_ref"]["unit_id"]
               for entry in run["decision_integration"]["requests"].values()
               if entry["request"]["preset"] == "workflow_next_action" and entry.get("decision")
               and route == {"choice": entry["decision"]["candidate_id"], "evidence": entry["decision"]["evidence"]}]
    if len(matches) != 1:
        raise ValueError("no unique adopted operational choice")
    return matches[0]


def delivery_source(run, unit_id):
    data = run["decision_integration"]
    launch = data["launches"][unit_id]
    target = launch["target"]
    executor = {"name": target["agent"], "session": target["session"], "pane": target["pane_id"],
                "thread": launch["thread_id"]}
    return dict(run["input"], executor=executor, mode="PREPARE_NEW"), data["actions"]["native_handoff"]["id"]


def verify_owner(root, run, raw_owner, result_hash, choice):
    funcs = episode_validators(root)
    data = run["input"]
    owner = json.loads(raw_owner)
    funcs["require"](owner["schema_version"] == 1 and owner["task_id"] == data["task_id"]
                     and owner["unit_id"] == data["unit_id"] and owner["result_sha256"] == result_hash,
                     "owner receipt must refer to this original result")
    funcs["require"](owner["owner"] == data["acceptor"] and owner["choice"] == choice,
                     "owner authority or choice mismatch")
    funcs["verify_owner_claim"](owner, data["acceptor"])


def verify_delivery(root, run, raw):
    funcs = episode_validators(root)
    require = funcs["require"]
    unit_id = decision_unit(run)
    source, action = delivery_source(run, unit_id)
    manifest = json.loads(raw)
    require(funcs["validate_result"](source, manifest, action), "an original delivered result is required")
    data = run["decision_integration"]
    model_request_id = data["launches"][unit_id]["request_id"]
    model = data["requests"][model_request_id]["model"]
    model_ref = model.get("execution_ref", {}).get("ids", {})
    require(model_ref.get("turn_id") and model_ref.get("thread_id"),
            "actual model readback is pending for this native turn")
    require(model_ref["turn_id"] == manifest["native_turn_id"] and model_ref["thread_id"] == source["executor"]["thread"],
            "effective model evidence belongs to another native turn")
    require(model.get("effective_model", {}).get("configuration_status") == "confirmed"
            and model.get("application_status") in {"applied", "not_applied"},
            "actual model configuration is unconfirmed")


def verify_collected(root, run):
    funcs = episode_validators(root)
    verify_sources(root, run)
    data = run["input"]
    verify_inputs(funcs, data)
    result = Path(data["result_manifest_path"]).read_bytes()
    digest = sha256(result).hexdigest()
    collected = [(action, row["evidence"]) for action, history in run["receipts"].items()
                 for row in history if row["status"] == "COLLECTED"]
    funcs["require"](len(collected) == 1 and collected[0][1] == "sha256:" + digest,
                     "collection must reference this original result")
    manifest = json.loads(result)
    source = dict(data, executor=manifest["executor"], mode="PREPARE_NEW")
    funcs["require"](funcs["validate_result"](source, manifest, collected[0][0]),
                     "an original delivered result is required")
    return {"result_sha256": digest}


def validate_record(root, run, args):
    """Validate original evidence inside the runner before its state transition commits."""
    verify_sources(root, run)
    require = episode_validators(root)["require"]
    if args.command == "receive" and args.status == "COLLECTED":
        source, action = delivery_source(run, decision_unit(run))
        raw = Path(source["result_manifest_path"]).read_bytes()
        require(args.action == action and args.evidence == "sha256:" + sha256(raw).hexdigest(),
                "collection must reference this original result")
        verify_delivery(root, run, raw)
    elif args.command == "decide" and args.step == "owner_acceptance":
        require(args.expected_state_digest is None, "owner acceptance requires the original owner entrypoint")
        result_hash = verify_collected(root, run)["result_sha256"]
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", args.evidence), "invalid owner evidence reference")
        owner_hash = args.evidence.removeprefix("sha256:")
        state = Path(args.state).resolve()
        owner_raw = (state.parent / (state.name + ".owner-" + owner_hash + ".json")).read_bytes()
        require(sha256(owner_raw).hexdigest() == owner_hash, "stored owner receipt changed")
        verify_owner(root, run, owner_raw, result_hash, args.choice)


OPERATIONS = {"prepare": prepare, "record_order": record_order, "verify_result": verify_collected,
              "validate_record": validate_record}

# Project-owned workflow definition. Edit this file to change future runs.
DEFINITION = {'version': 1,
 'project': 'fanren-work',
 'workflow': 'decision-publication-audit',
 'memory': 'README.md',
 'start': 'prepare',
 'steps': {'prepare': {'kind': 'program', 'operation': 'prepare', 'next': 'audit_route'},
           'audit_route': {'kind': 'decision',
                           'question': '独立核验凡人工作流自动发布接线时，哪种顺序最适合现有证据？',
                           'choices': {'receipt_first': 'receipt_first',
                                       'trace_first': 'trace_first'}},
           'receipt_first': {'kind': 'program',
                             'operation': 'record_order',
                             'next': 'native_handoff'},
           'trace_first': {'kind': 'program',
                           'operation': 'record_order',
                           'next': 'native_handoff'},
           'native_handoff': {'kind': 'handoff',
                              'instruction': '按原检查点选定的顺序独立核验工程证据。核查两组证据，交付工程采用报告和链路索引。只读工程证据并写私有报告。原协调员负责收件、自动发布回执和向负责人交验。',
                              'next': 'verify_result'},
           'verify_result': {'kind': 'program', 'operation': 'verify_result', 'next': 'owner_acceptance'},
           'owner_acceptance': {'kind': 'decision',
                                'question': '负责人根据原生执行、原产物和自动发布回执作出本工程单元的限定验收。',
                                'choices': {'accept': 'accepted',
                                            'revise': 'revision_required',
                                            'hold': 'held'}},
           'accepted': {'kind': 'end'},
           'revision_required': {'kind': 'end'},
           'held': {'kind': 'end'}}}
