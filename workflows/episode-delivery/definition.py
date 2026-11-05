# coding: utf-8
"""Fanren delivery units: local preparation and evidence checks only."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import stat


def require(condition, message):
    if not condition:
        raise ValueError(message)


def artifact_bytes(record):
    require(isinstance(record, dict), "expected an artifact reference")
    path = Path(record["path"])
    require(path.is_absolute(), "artifact path must be absolute")
    require(type(record["bytes"]) is int and record["bytes"] >= 0, "invalid artifact length")
    require(isinstance(record["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", record["sha256"]),
            "invalid artifact SHA-256")
    require(stat.S_ISREG(path.stat().st_mode), "artifact must be a regular file")
    raw = path.read_bytes()
    require(len(raw) == record["bytes"], "artifact length mismatch")
    require(hashlib.sha256(raw).hexdigest() == record["sha256"], "artifact SHA-256 mismatch")
    return raw


def validate_identity(identity, *, owner=False):
    require(isinstance(identity, dict), "expected an explicit native identity")
    for key in ("name", "session", "pane", "thread"):
        require(isinstance(identity.get(key), str) and identity[key].strip(), f"missing identity {key}")
    if owner:
        require(type(identity.get("generation")) is int and identity["generation"] >= 0,
                "missing owner generation")


def verify_dispatch(record, executor):
    dispatch = json.loads(artifact_bytes(record))
    require(dispatch["exit_code"] == 0, "dispatch has no successful native submission")
    response = json.loads(dispatch["stdout"])["result"]
    require(response["type"] == "agent_prompted", "not a native prompt receipt")
    native = response["agent"]
    require(native["name"] == executor["name"] and native["pane_id"] == executor["pane"],
            "dispatch target mismatch")
    if "agent_session" in native:
        require(native["agent_session"]["value"] == executor["thread"], "dispatch thread mismatch")


def validate_binding(data, record, action_id):
    require(record["schema_version"] == 1, "unsupported binding schema")
    for key in ("task_id", "unit_id", "executor"):
        require(record[key] == data[key], f"binding {key} mismatch")
    require(record["action_id"] == action_id, "binding action mismatch")
    require(isinstance(record["native_turn_id"], str) and record["native_turn_id"].strip(), "missing bound native turn")
    verify_dispatch(record["dispatch_receipt"], data["executor"])
    request = json.loads(artifact_bytes(record["native_request"]))
    require(request["thread"]["id"] == data["executor"]["thread"], "native request thread mismatch")
    turns = [turn for turn in request["turns"] if turn["id"] == record["native_turn_id"]]
    require(len(turns) == 1, "native request turn mismatch")
    verify_task_markers(turns[0], data, action_id)
    return record["native_turn_id"]


def verify_task_markers(turn, data, action_id):
    markers = {"WORKFLOW_TASK_ID=" + data["task_id"], "WORKFLOW_ACTION_ID=" + action_id}
    require(any(item.get("type") == "userMessage" and any(
                block.get("type") == "text" and data["contact_ref"] in block.get("text", "")
                and markers <= set(block.get("text", "").splitlines())
                for block in item.get("content", [])) for item in turn["items"]),
            "native request lacks this unique workflow task/action marker")


def validate_input(data, task):
    require(data["schema_version"] == 1 and data["project"] == "fanren-work", "input identity mismatch")
    require(data["task_id"] == task, "task identity mismatch")
    for key in ("contact_ref", "unit_id", "deliverable_kind"):
        require(isinstance(data[key], str) and data[key].strip(), f"missing {key}")
    require(Path(data["result_manifest_path"]).is_absolute(), "result manifest path must be absolute")
    deadline = datetime.fromisoformat(data["due_at"])
    require(deadline.utcoffset() is not None, "due_at must include timezone")
    require(isinstance(data["scope"], dict) and data["scope"], "explicit scope required")
    for key in ("inputs", "deliverables"):
        require(isinstance(data[key], list) and data[key], f"nonempty {key} required")
    for record in data["inputs"]:
        artifact_bytes(record)
    require(isinstance(data["prior_refs"], list), "prior_refs must be a list")
    validate_identity(data["executor"])
    validate_identity(data["acceptor"], owner=True)
    artifact_bytes(data["owner_plan"])
    mode = data.get("mode", "ADOPT_EXISTING")
    require(mode in ("ADOPT_EXISTING", "PREPARE_NEW"), "unsupported dispatch mode")
    if mode == "ADOPT_EXISTING":
        require(isinstance(data["native_turn_id"], str) and data["native_turn_id"].strip(), "missing original native turn")
        verify_dispatch(data["existing_dispatch"], data["executor"])
    else:
        require("existing_dispatch" not in data and "native_turn_id" not in data,
                "new preparation cannot claim an existing dispatch")
        require(Path(data["dispatch_binding_path"]).is_absolute(), "dispatch binding path must be absolute")
    return {
        "mode": mode, "task_id": task, "unit_id": data["unit_id"],
        "contact_ref": data["contact_ref"], "executor": data["executor"],
        "native_turn_id": data.get("native_turn_id"), "dispatch_binding_path": data.get("dispatch_binding_path"),
        "existing_dispatch": data.get("existing_dispatch"), "owner_plan": data["owner_plan"],
        "due_at": data["due_at"], "scope": data["scope"], "inputs": data["inputs"],
        "deliverable_kind": data["deliverable_kind"], "deliverables": data["deliverables"],
        "acceptor": data["acceptor"], "prior_refs": data["prior_refs"],
        "business_accepted": False, "requires_native_binding": mode == "PREPARE_NEW",
        "dispatch_required": None if mode == "PREPARE_NEW" else False,
    }


def verify_native_final(record, identity, turn_id):
    native = json.loads(artifact_bytes(record))
    require(native.get("source_kind", "codex_app_read_thread") in ("codex_app_read_thread", "codex_transcript_snapshot.v1"), "unsupported native receipt source")
    require(native["thread"]["id"] == identity["thread"], "native result thread mismatch")
    turns = [turn for turn in native["turns"] if turn["id"] == turn_id]
    require(len(turns) == 1, "native result turn mismatch")
    texts = [item["text"] for item in turns[0]["items"]
             if item.get("type") == "agentMessage" and item.get("phase") in ("final", "final_answer")
             and isinstance(item.get("text"), str) and item["text"].strip()]
    require(texts, "native final reply not present")
    return turns[0], texts


def validate_result(data, manifest, action_id):
    require(manifest["schema_version"] == 1, "unsupported result schema")
    for key in ("task_id", "unit_id", "executor", "deliverable_kind"):
        require(manifest[key] == data[key], f"result {key} mismatch")
    require(manifest["action_id"] == action_id, "result action mismatch")
    require(manifest["status"] in ("DELIVERED", "PARTIAL", "BLOCKED", "UNKNOWN"), "invalid result status")
    require(isinstance(manifest["summary"], str) and manifest["summary"].strip(), "missing result summary")
    if manifest["status"] != "DELIVERED":
        return False
    if data.get("mode", "ADOPT_EXISTING") == "PREPARE_NEW":
        binding = json.loads(Path(data["dispatch_binding_path"]).read_bytes())
        native_turn = validate_binding(data, binding, action_id)
    else:
        native_turn = data["native_turn_id"]
    require(manifest["native_turn_id"] == native_turn, "result belongs to another native task turn")
    turn, _ = verify_native_final(manifest["native_receipt"], data["executor"], manifest["native_turn_id"])
    if data.get("mode") == "PREPARE_NEW":
        verify_task_markers(turn, data, action_id)
    require(any(item.get("type") == "userMessage" and any(
                block.get("type") == "text" and data["contact_ref"] in block.get("text", "")
                for block in item.get("content", [])) for item in turn["items"]),
            "native task does not reference the original contact")
    require(isinstance(manifest["artifacts"], list) and manifest["artifacts"], "missing result artifacts")
    for record in manifest["artifacts"]:
        artifact_bytes(record)
    return True


def verify_owner_claim(record, identity):
    _, texts = verify_native_final(record["native_receipt"], identity, record["native_turn_id"])
    decoder = json.JSONDecoder()
    claims = []
    for text in texts:
        for offset, character in enumerate(text):
            if character != "{":
                continue
            try:
                claim, _ = decoder.raw_decode(text[offset:])
            except ValueError:
                continue
            if isinstance(claim, dict) and all(claim.get(key) == record[key]
                                              for key in ("task_id", "unit_id", "result_sha256")):
                claims.append(claim)
    require(claims and all(claim.get("choice") == record["choice"] for claim in claims),
            "native owner reply lacks an unambiguous decision for this task and result")


def prepare(root, run):
    prepared = validate_input(run["input"], run["task"])
    prepared["entrypoint_sha256"] = hashlib.sha256(
        (Path(root) / "scripts" / "episode_delivery.py").read_bytes()).hexdigest()
    return prepared


def verify_result(root, run):
    data = run["input"]
    for record in data["inputs"]:
        artifact_bytes(record)
    raw = Path(data["result_manifest_path"]).read_bytes()
    manifest = json.loads(raw)
    # The runner has just committed the receipt. Recheck the exact imported action.
    action_id = hashlib.sha256(json.dumps(
        [run["project"], run["workflow"], run["task"], "native_handoff"],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    collected = [item for item in run["receipts"].get(action_id, []) if item["status"] == "COLLECTED"]
    require(len(collected) == 1 and collected[0]["evidence"] == "sha256:" + hashlib.sha256(raw).hexdigest(),
            "result bytes differ from the committed collection receipt")
    require(validate_result(data, manifest, action_id), "incomplete result cannot advance")
    return {"status": "READY_FOR_OWNER_REVIEW", "unit_id": data["unit_id"],
            "deliverable_kind": data["deliverable_kind"], "summary": manifest["summary"],
            "result_sha256": hashlib.sha256(raw).hexdigest(), "artifacts": manifest["artifacts"],
            "native_receipt": manifest["native_receipt"], "business_accepted": False}


OPERATIONS = {"prepare": prepare, "verify_result": verify_result}




# Project-owned workflow definition. Edit this file to change future runs.
DEFINITION = {'version': 1,
 'project': 'fanren-work',
 'workflow': 'episode-delivery',
 'memory': 'README.md',
 'start': 'prepare',
 'steps': {'prepare': {'kind': 'program', 'operation': 'prepare', 'next': 'native_handoff'},
           'native_handoff': {'kind': 'handoff',
                              'instruction': '沿prepare中的显式目标处理：ADOPT_EXISTING只收原动作；PREPARE_NEW由原协调员唯一派发本handoff并绑定实际原生回执。完整结果及工件核清才收件，阻塞只记录进度。',
                              'next': 'verify_result'},
           'verify_result': {'kind': 'program',
                             'operation': 'verify_result',
                             'next': 'owner_acceptance'},
           'owner_acceptance': {'kind': 'decision',
                                'question': '现任项目负责人是否接受本次明确范围的单元成果？原生决定只覆盖此单元，不代表整集放行。',
                                'choices': {'accept': 'accepted',
                                            'revise': 'revision_required',
                                            'hold': 'held'}},
           'accepted': {'kind': 'end'},
           'revision_required': {'kind': 'end'},
           'held': {'kind': 'end'}}}
