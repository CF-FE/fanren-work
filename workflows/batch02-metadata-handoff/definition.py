# coding: utf-8
import hashlib
import json
from pathlib import Path


EXPECTED_BYTES = 386612
EXPECTED_ROWS = 86
EXPECTED_SHA256 = (
    "1309cc8f99f9498284899d1f5abe56060"
    "e0a2154835813dd217977e17c002c4a"
)
ISSUE_URL = "https://github.com/CF-FE/fanren-work/issues/2"
PROJECT_ITEM_URL = (
    "https://github.com/orgs/CF-FE/projects/5"
    "?pane=issue&itemId=285760278"
)
TERMINAL_ACCEPTANCE_REF = (
    "fanren-issue2-batch02-1706-owner-decision-20261104"
    "/terminal-owner-review"
)


def verify_metadata(root, run):
    request = run["input"]
    source_name = request["completion_path"]

    if not isinstance(source_name, str) or not source_name:
        raise ValueError("completion_path must be a nonempty string")
    if request["prior_acceptance_ref"] != TERMINAL_ACCEPTANCE_REF:
        raise ValueError("Unexpected prior acceptance reference")

    source_path = Path(source_name)
    if not source_path.is_absolute():
        source_path = Path(root) / source_path

    with source_path.open("rb") as source_file:
        raw = source_file.read(EXPECTED_BYTES + 1)

    if len(raw) != EXPECTED_BYTES:
        raise ValueError("Completion file size mismatch")

    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != EXPECTED_SHA256:
        raise ValueError("Completion file SHA-256 mismatch")

    report = json.loads(raw)
    if not isinstance(report, dict):
        raise ValueError("Completion report must be an object")

    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROWS:
        raise ValueError("Expected exactly 86 rows")

    row_index = []
    for ordinal, row in enumerate(rows):
        row_bytes = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        row_index.append({
            "pointer": f"/rows/{ordinal}",
            "sha256": hashlib.sha256(row_bytes).hexdigest(),
        })

    index_bytes = json.dumps(
        row_index,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    return {
        "task": {
            "issue": ISSUE_URL,
            "project_item": PROJECT_ITEM_URL,
        },
        "source": {
            "path": str(source_path),
            "bytes": len(raw),
            "sha256": source_sha256,
        },
        "row_count": len(rows),
        "row_index": row_index,
        "row_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "prior_acceptance_ref": request["prior_acceptance_ref"],
    }


def build_handoff(root, run):
    evidence = run["outputs"]["verify_metadata"]

    return {
        "technical_receipt": {
            "task": evidence["task"],
            "source": evidence["source"],
            "row_count": evidence["row_count"],
            "row_index_sha256": evidence["row_index_sha256"],
            "prior_acceptance_ref": evidence["prior_acceptance_ref"],
            "scope": "sealed_metadata_identity_and_row_index",
        },
        "handoff_package": {
            "recipient": {
                "role": "project_owner",
                "generation": 1,
            },
            "row_index": evidence["row_index"],
            "topics_for_owner_review": [
                "本次元数据流程的实际采用范围",
                "独立音频QA、听审及内容质量的既有承接",
                "角色素材与完整音轨的后续关联",
                "正式时轴、字幕及封面采用的遗留关联",
            ],
            "state": "READY_FOR_OWNER_REVIEW",
        },
    }


OPERATIONS = {
    "verify_metadata": verify_metadata,
    "build_handoff": build_handoff,
}


# Project-owned workflow definition. Edit this file to change future runs.
DEFINITION = {'version': 1,
 'project': 'fanren-work',
 'workflow': 'batch02-metadata-handoff',
 'memory': 'README.md',
 'start': 'verify_metadata',
 'steps': {'verify_metadata': {'kind': 'program',
                               'operation': 'verify_metadata',
                               'next': 'build_handoff'},
           'build_handoff': {'kind': 'program',
                             'operation': 'build_handoff',
                             'next': 'owner_handoff'},
           'owner_handoff': {'kind': 'handoff',
                             'instruction': '将build_handoff的真实输出、同次运行的checkpoint及证据引用交generation=1现任项目负责人，一次审定本次元数据流程采用范围。',
                             'next': 'done'},
           'done': {'kind': 'end'}}}
