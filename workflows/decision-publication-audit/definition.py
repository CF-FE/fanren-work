# coding: utf-8
from hashlib import sha256
from pathlib import Path
import sys


def prepare(root, run):
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from episode_delivery import definition_functions
    finally:
        sys.path.remove(str(scripts))
    funcs = definition_functions()
    data = run["input"]
    funcs["require"](data["project"] == run["project"] and data["task_id"] == run["task"],
                     "audit project or task mismatch")
    for field in ("owner_plan", "decision_context", "runtime_inputs"):
        funcs["artifact_bytes"](data[field])
    for reference in data["inputs"]:
        funcs["artifact_bytes"](reference)
    funcs["validate_identity"](data["acceptor"], owner=True)
    for key in ("dispatch_binding_path", "result_manifest_path"):
        path = Path(data[key])
        funcs["require"](path.is_absolute() and not path.resolve().is_relative_to(root),
                         "native evidence must be outside the repository")
    entrypoint = scripts / "decision_publication_audit.py"
    deps = (entrypoint, scripts / "episode_delivery.py",
            root / "workflows/episode-delivery/definition.py")
    actual = {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in deps}
    funcs["require"](actual == data["source_files"], "restore the original audit sources")
    return {"unit_id": data["unit_id"], "source_files": actual}


def record_order(root, run):
    order = ["release_install_review_receipts", "native_execution_and_publication_trace"]
    if run["step"] == "trace_first":
        order.reverse()
    return {"audit_order": order}


OPERATIONS = {"prepare": prepare, "record_order": record_order}


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
                              'next': 'owner_acceptance'},
           'owner_acceptance': {'kind': 'decision',
                                'question': '负责人根据原生执行、原产物和自动发布回执作出本工程单元的限定验收。',
                                'choices': {'accept': 'accepted',
                                            'revise': 'revision_required',
                                            'hold': 'held'}},
           'accepted': {'kind': 'end'},
           'revision_required': {'kind': 'end'},
           'held': {'kind': 'end'}}}
