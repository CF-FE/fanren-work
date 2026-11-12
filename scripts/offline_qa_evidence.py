"""Derive Fanren QA evidence from an explicitly released metadata archive."""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from episode_delivery import ROOT, definition_functions, save_exact


SHA = r"[a-f0-9]{64}"
CLIP_SUFFIXES = ("input.json", "response.raw.json", "sealed.json", "comparison.json")
SUPPORT_FILES = ("FINAL-NATIVE-AUDIT.json", "TARGETED-REVIEW-RESULT.json",
                 "targeted_review.py", "final_audit.py")
OUTPUT_NAMES = ("derived-evidence-validation.json", "validation-notes.md", "artifact-manifest.json")
HEADER = re.compile(r"^[ \t]*【([^】\r\n]+)】[ \t]*", re.MULTILINE)
NUMBER = r"[+-]?[0-9]+(?:\.[0-9]+)?"
ENDPOINT = re.compile(rf"-\s*(起始|结束)时间[：:]\s*({NUMBER})\s*秒\s*[。.]?")
INTERVAL = re.compile(rf"-\s*[^：:]+[：:]\s*从\s*({NUMBER})\s*秒开始[，,]\s*到\s*({NUMBER})\s*秒结束\s*[。.]?")
POINT = re.compile(rf"-\s*([^：:]+)[：:]\s*({NUMBER})\s*秒\s*[。.]?")
PLACEHOLDER = re.compile(r"(?:unknown|n/a|无|未知|缺失|无法(?:提供|确认|转写|判断|辨认).*)[。.!！]?", re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"non-JSON numeric constant {value}")


def object_from(raw):
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant,
                       parse_float=Decimal)
    require(isinstance(value, dict), "expected a JSON object")
    return value


def text(value):
    return isinstance(value, str) and bool(value.strip()) and not re.search(r"[\ud800-\udfff]", value)


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(SHA, value) is not None


def json_bytes(value):
    # Decimal values retain their source precision in derived numeric strings.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str,
                       allow_nan=False) + "\n").encode("utf-8", errors="backslashreplace")


def load_archive(input_path, input_sha, contract_path, read_artifact, validate_executor):
    require(input_path.suffix == contract_path.suffix == ".json", "input and contract must be JSON files")
    input_raw = input_path.read_bytes()
    require(is_sha256(input_sha) and digest(input_raw) == input_sha, "frozen input SHA-256 mismatch")
    released = object_from(input_raw)
    require(released.get("schema_version") == 1 and released.get("project") == "fanren-work",
            "frozen input identity mismatch")
    binding = {key: released.get(key) for key in ("task_id", "unit_id", "deliverable_kind", "executor")}
    require(all(text(binding[key]) for key in ("task_id", "unit_id", "deliverable_kind")),
            "missing frozen delivery identity")
    validate_executor(binding["executor"])

    contract_raw = contract_path.read_bytes()
    contract = object_from(contract_raw)
    require(contract.get("schema_version") == 1, "unsupported QA contract schema")
    review = contract.get("review")
    require(isinstance(review, dict), "missing source review identity")
    identity_keys = ("attempt", "workflow_task_id", "workflow_action_id")
    require(all(text(review.get(key)) for key in identity_keys), "missing source review identity field")
    review = {key: review[key] for key in identity_keys}
    require(type(contract.get("require_full_transcript")) is bool, "require_full_transcript must be explicit")
    clips = contract.get("clips")
    require(isinstance(clips, list) and clips, "nonempty clips required")
    required = set()
    ids = set()
    for clip in clips:
        require(isinstance(clip, dict) and text(clip.get("id")) and type(clip.get("ordinal")) is int
                and clip["ordinal"] > 0, "invalid clip identity")
        ordinal = clip["ordinal"]
        require(clip["id"] not in ids and f"{ordinal:03d}.input.json" not in required,
                "duplicate clip identity or ordinal")
        require("expected_tail" not in clip or text(clip["expected_tail"]), "empty expected_tail")
        ids.add(clip["id"])
        required.update(f"{ordinal:03d}.{suffix}" for suffix in CLIP_SUFFIXES)

    history = contract.get("history")
    if history is not None:
        require(isinstance(history, dict) and text(history.get("file")) and text(history.get("task_ref"))
                and text(history.get("attempt")), "invalid historical report identity")
        require(re.fullmatch(r"[\w.+-]*FINAL-QUALITY-REPORT\.json", history["file"]),
                "unsupported historical report filename")
        retained = history.get("retain_ordinals", [])
        require(isinstance(retained, list) and all(type(n) is int and n > 0 for n in retained),
                "invalid historical ordinals")
        required.add(history["file"])

    refs = released.get("inputs")
    require(isinstance(refs, list) and refs, "missing frozen input whitelist")
    artifacts = {}
    for ref in refs:
        require(isinstance(ref, dict) and text(ref.get("path")), "invalid frozen artifact reference")
        path = Path(ref["path"])
        name = path.name
        require(name in required or name in SUPPORT_FILES, f"unsupported whitelist entry {name}")
        require(name not in artifacts, f"duplicate whitelist entry {name}")
        require(path.is_absolute() and path.resolve() == path, f"{name}: expected a canonical local path")
        artifacts[name] = ref
    require(required <= artifacts.keys(), "missing whitelist entries: " + ", ".join(sorted(required - artifacts.keys())))

    documents, parse_errors = {}, {}
    for name, ref in artifacts.items():
        try:
            raw = read_artifact(ref)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"{name}: {exc}") from exc
        if name.endswith(".json"):
            try:
                documents[name] = object_from(raw)
            except (UnicodeError, ValueError, InvalidOperation, RecursionError) as exc:
                documents[name] = {}
                parse_errors[name] = str(exc)
    return binding, review, contract, digest(contract_raw), artifacts, documents, parse_errors


def check_links(record, expected, label, gaps):
    """Compare present trusted identity fields. Missing/malformed fields stay unknown."""
    for key, value in expected.items():
        observed = record.get(key)
        if type(observed) is not type(value) or (isinstance(value, str) and not observed.strip()):
            gaps.append(f"{label}.{key}")
        else:
            require(observed == value, f"{label}.{key}: identity mismatch")


def row_by_ordinal(report, field, ordinal, label, gaps, clip_id=None):
    rows = report.get("rows")
    numbered = [row for row in rows if isinstance(row, dict) and type(row.get(field)) is int
                ] if isinstance(rows, list) else []
    require(clip_id is None or all(row.get("id") != clip_id or row[field] == ordinal for row in numbered),
            f"{label}.rows[{ordinal}]: clip ordinal mismatch")
    matches = [row for row in numbered if row[field] == ordinal]
    if len(matches) != 1:
        gaps.append(f"{label}.rows[{ordinal}]")
        return {}
    return matches[0]


def check_audio_identity(audio, source, companion_rows, gaps):
    """Compare recorded audio identities without opening any referenced audio."""
    if not companion_rows:
        return "UNKNOWN"
    audio = audio if isinstance(audio, dict) else {}
    complete = True
    for field, valid in (
        ("path", text),
        ("bytes", lambda value: type(value) is int and value >= 0),
        ("sha256", is_sha256),
    ):
        declarations = [(f"{source}.input.{field}", audio.get(field))]
        for label, row in companion_rows:
            wave = row.get("wave")
            declarations.append((f"{label}.wave.{field}", wave.get(field) if isinstance(wave, dict) else None))
            if field != "path":
                key = f"actual_request_audio_{field}"
                declarations.append((f"{label}.{key}", row.get(key)))
        known = {}
        for label, value in declarations:
            if valid(value):
                known[label] = value
            else:
                gaps.append(label)
                complete = False
        require(len(set(known.values())) <= 1,
                f"audio identity mismatch ({field}): " + ", ".join(known))
    return "MATCHED" if complete else "UNKNOWN"


def duration_value(value):
    if isinstance(value, Decimal) or type(value) is int:
        if Decimal(value).is_finite() and value > 0:
            return Decimal(value)
    return None


def location_claims(section, duration, observations):
    claims, endpoints, unknown = [], [], []
    for raw_line in section.splitlines() if section else []:
        line = raw_line.strip()
        if not line:
            continue
        if match := ENDPOINT.fullmatch(line):
            endpoints.append((*match.groups(), raw_line))
        elif match := INTERVAL.fullmatch(line):
            start, end = match.groups()
            claims.append({"raw": raw_line, "kind": "INTERVAL", "start_seconds": start, "end_seconds": end})
        elif match := POINT.fullmatch(line):
            label, seconds = match.groups()
            label = label.strip()
            # A bare number on a prose line can describe something other than a location.
            phrase = label.strip("“”")
            if label in ("时间点", "位置", "时间") or (
                    phrase and any(phrase in observation for observation in observations)):
                claims.append({"raw": raw_line, "kind": "POINT", "seconds": seconds})
            else:
                unknown.append(raw_line)
        else:
            unknown.append(raw_line)
    if len(endpoints) == 2 and {name for name, _, _ in endpoints} == {"起始", "结束"}:
        seconds = {name: value for name, value, _ in endpoints}
        claims.append({"raw": "\n".join(line for _, _, line in endpoints), "kind": "INTERVAL",
                       "start_seconds": seconds["起始"], "end_seconds": seconds["结束"]})
    else:
        unknown.extend(line for _, _, line in endpoints)
    for claim in claims:
        if claim["kind"] == "POINT":
            start = end = Decimal(claim["seconds"])
        else:
            start = Decimal(claim["start_seconds"])
            end = Decimal(claim["end_seconds"])
        claim["range_status"] = ("UNKNOWN" if duration is None else
                                 "IN_BOUNDS" if 0 <= start <= end <= duration else "OUT_OF_BOUNDS")
    statuses = {claim["range_status"] for claim in claims}
    status = ("OUT_OF_BOUNDS" if "OUT_OF_BOUNDS" in statuses else
              "IN_BOUNDS" if statuses == {"IN_BOUNDS"} and not unknown else "UNKNOWN")
    return {"status": status, "raw_section": section, "claims": claims, "unparsed_lines": unknown,
            "accepted_position": "UNKNOWN", "actual_alignment": "UNKNOWN"}


def response_sections(content):
    sections = {}
    if not text(content):
        return sections
    headings = list(HEADER.finditer(content))
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        sections.setdefault(match[1].strip(), []).append(content[match.end():end].strip("\r\n"))
    return sections


def standalone(sections, name):
    blocks = sections.get(name, [])
    if len(blocks) == 1 and text(blocks[0]) and not PLACEHOLDER.fullmatch(blocks[0].strip()):
        return blocks[0]
    return None


def finish_record(reason, tokens):
    return {"reason": reason if text(reason) else None,
            "completion_tokens": tokens if type(tokens) is int and tokens >= 0 else None}


def validate_clip(clip, review, contract, artifacts, documents, history, companions):
    ordinal, clip_id = clip["ordinal"], clip["id"]
    names = [f"{ordinal:03d}.{suffix}" for suffix in CLIP_SUFFIXES]
    metadata, response, seal, comparison = (documents[name] for name in names)
    gaps = []
    identity = dict(review, id=clip_id)
    binding_gaps = []
    check_links(seal, identity, names[2], binding_gaps)
    check_links(metadata, dict(identity, original_ordinal=ordinal), names[0], binding_gaps)
    request_sha = metadata.get("request_sha256")
    if not is_sha256(request_sha):
        binding_gaps.append(f"{names[0]}.request_sha256")
    for key, expected in (("response_sha256", artifacts[names[1]]["sha256"]), ("request_sha256", request_sha)):
        if not is_sha256(seal.get(key)):
            binding_gaps.append(f"{names[2]}.{key}")
        elif is_sha256(expected):
            check_links(seal, {key: expected}, names[2], binding_gaps)
    gaps.extend(binding_gaps)
    check_links(comparison, dict(identity, original_ordinal=ordinal), names[3], gaps)

    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else {}
    message, usage = choice.get("message"), response.get("usage")
    content = message.get("content") if isinstance(message, dict) else None
    if text(content):
        check_links(comparison, {"model_observation": content}, names[3], gaps)
    else:
        gaps.append(f"{names[1]}.choices.message.content")
    finish = finish_record(choice.get("finish_reason"), usage.get("completion_tokens") if isinstance(usage, dict) else None)
    if finish["reason"] is not None:
        check_links(comparison, {"finish_reason": finish["reason"]}, names[3], gaps)
    if None in finish.values():
        gaps.append(f"{names[1]}.finish_reason or completion_tokens")

    duration = duration_value(metadata.get("audio_duration_seconds"))
    if duration is None:
        gaps.append(f"{names[0]}.audio_duration_seconds")
    compared_duration = duration_value(comparison.get("audio_duration_seconds"))
    if compared_duration is None:
        gaps.append(f"{names[3]}.audio_duration_seconds")
    elif duration is not None:
        require(compared_duration == duration, f"{names[3]}: sealed duration mismatch")
    companion_rows = []
    for label, report in companions.items():
        row = row_by_ordinal(report, "original_ordinal", ordinal, label, gaps, clip_id)
        companion_rows.append((f"{label}.rows[{ordinal}]", row))
        check_links(row, {"id": clip_id, "response_sha256": artifacts[names[1]]["sha256"]}, label, gaps)
        if is_sha256(request_sha):
            check_links(row, {"request_sha256": request_sha}, label, gaps)
        observed = duration_value(row.get("actual_audio_duration_seconds"))
        if observed is None:
            gaps.append(f"{label}.actual_audio_duration_seconds")
        elif duration is not None:
            require(observed == duration, f"{label}: sealed duration mismatch")

    audio_identity = check_audio_identity(metadata.get("input"), names[0], companion_rows, gaps)

    historical = None
    if history is not None:
        old = row_by_ordinal(history, "ordinal", ordinal, "history", gaps, clip_id)
        check_links(old, {"id": clip_id}, "history", gaps)
        old_usage = old.get("response_usage")
        historical = finish_record(old.get("response_finish_reason"),
                                   old_usage.get("completion_tokens") if isinstance(old_usage, dict) else None)
        if None in historical.values():
            gaps.append(f"history.rows[{ordinal}].finish_reason or completion_tokens")

    sections = response_sections(content)
    transcript = standalone(sections, "完整转写")
    transcript_status = "NOT_REQUESTED"
    if contract["require_full_transcript"]:
        transcript_status = ("PRESENT" if transcript is not None else
                             "MISSING" if sections and "完整转写" not in sections else "UNKNOWN")
    expected_tail = clip.get("expected_tail")
    closing = standalone(sections, "结尾观察")
    revealed = comparison.get("expected_text")
    tail_mentioned = None
    if expected_tail is not None:
        if not text(revealed) or expected_tail not in revealed:
            gaps.append(f"{names[3]}.expected_text tail anchor")
        elif closing is not None:
            tail_mentioned = expected_tail in closing
    tail_status = ("NOT_REQUESTED" if expected_tail is None else
                   "INSUFFICIENT" if tail_mentioned is False else "UNKNOWN")
    observations = [value for value in (standalone(sections, "开头观察"), closing, transcript)
                    if value is not None]
    location = location_claims(standalone(sections, "位置与依据"), duration, observations)
    return {
        "id": clip_id, "ordinal": ordinal, "sources": names, "unknown_fields": gaps,
        "seal_binding": {"status": "UNKNOWN" if binding_gaps else "MATCHED", "unknown_fields": binding_gaps},
        "audio_metadata_identity": audio_identity,
        "sealed_duration_seconds": str(duration) if duration is not None else None,
        "original_model_text": content if isinstance(content, str) else None, "location": location,
        "transcript": {"status": transcript_status, "actual_transcription": "UNKNOWN"},
        "tail": {"status": tail_status, "expected_tail": expected_tail,
                 "literal_mention_in_closing": tail_mentioned, "actual_tail": "UNKNOWN"},
        "finish": {"targeted": finish, "historical": historical},
        "quality": "UNKNOWN", "actual_listening": False,
    }


def derive(binding, review, contract, input_sha, contract_sha, artifacts, documents, parse_errors):
    gaps = []
    companions = {name: documents[name] for name in SUPPORT_FILES if name in documents}
    for label, report in companions.items():
        check_links(report, review, label, gaps)
    historical_config = contract.get("history")
    history, retained = None, []
    if historical_config is not None:
        history = documents[historical_config["file"]]
        check_links(history, {key: historical_config[key] for key in ("task_ref", "attempt")}, "history", gaps)
        for ordinal in historical_config.get("retain_ordinals", []):
            row = row_by_ordinal(history, "ordinal", ordinal, "history", gaps)
            retained.append({key: row.get(key) for key in ("ordinal", "id", "original_source_order_flag")})
    clips = [validate_clip(clip, review, contract, artifacts, documents, history, companions)
             for clip in sorted(contract["clips"], key=lambda clip: clip["ordinal"])]
    return {
        "schema_version": 1, **binding, "source_review": review, "frozen_input_sha256": input_sha,
        "contract_sha256": contract_sha, "source_artifacts": artifacts, "source_bytes_verified": len(artifacts),
        "unparseable_sources": parse_errors, "unknown_fields": gaps, "clips": clips,
        "recorded_counts": {"targeted": {name: report.get("counts") for name, report in companions.items()},
                            "historical": history.get("counts") if history is not None else None},
        "retained_historical_flags": retained, "phase_compared": "PROCESSING_ONLY",
        "quality": "UNKNOWN", "actual_listening_count": 0, "dispatch_count": 0,
    }


def render_notes(report):
    lines = [
        "# 封存听审证据离线校验",
        "",
        f"已核 {report['source_bytes_verified']} 份冻结工件的字节数和 SHA-256。实际听审为 0 次。",
        "",
        "| 片段序号 | 封存绑定 | 位置范围 | 全文转写字段 | 尾句证据 | 定向 finish | 历史 finish |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for clip in report["clips"]:
        finish = clip["finish"]
        targeted = finish["targeted"]["reason"] or "UNKNOWN"
        historical = (finish["historical"] or {}).get("reason") or "UNKNOWN"
        # finish_reason is source text. Keep it in JSON if it is not a simple token.
        targeted = targeted if re.fullmatch(r"[a-zA-Z_]+", targeted) else "见 JSON"
        historical = historical if re.fullmatch(r"[a-zA-Z_]+", historical) else "见 JSON"
        lines.append(f"| {clip['ordinal']} | {clip['seal_binding']['status']} | {clip['location']['status']} | "
                     f"{clip['transcript']['status']} | {clip['tail']['status']} | {targeted} | {historical} |")
    lines.extend([
        "", "封存绑定为 UNKNOWN 时，表中的位置和文本字段仅描述原响应的算术与结构。",
        "位置范围仅按封存时长做算术核验。真实对齐、尾句和听感均为 UNKNOWN。",
        "JSON 保留原声明、未解析字段和历史计数。COMPARED 记录处理阶段。",
        "全文、尾句、finish 和位置各自提供结构证据。音质与负责人决定沿原任务核收。",
        "",
    ])
    return "\n".join(lines).encode("utf-8")


def write_artifacts(output_dir, report, protected):
    output_dir = output_dir.resolve()
    require(not output_dir.is_relative_to(ROOT), "private output must be outside the source tree")
    require(not any(output_dir.is_relative_to(path.parent) for path in protected),
            "use a separate output directory outside the frozen input directories")
    if output_dir.exists():
        require(output_dir.is_dir() and {entry.name for entry in output_dir.iterdir()} <= set(OUTPUT_NAMES),
                "output directory already contains unrelated files")
    paths = [output_dir / name for name in OUTPUT_NAMES]
    payloads = [json_bytes(report), render_notes(report)]
    refs = [{"path": str(path), "bytes": len(raw), "sha256": digest(raw)}
            for path, raw in zip(paths, payloads)]
    manifest = {key: report[key] for key in ("schema_version", "task_id", "unit_id", "deliverable_kind", "executor")}
    manifest.update(kind="fanren-offline-qa-artifacts.v1", artifacts=refs,
                    summary="封存听审证据离线核验，音质 UNKNOWN。")
    payloads.append(json_bytes(manifest))
    for path, raw in zip(paths, payloads):
        require(not path.is_symlink() and (not path.exists() or path.is_file() and path.read_bytes() == raw),
                f"{path.name}: stored evidence conflicts with derived bytes")
    for path, raw in zip(paths, payloads):
        save_exact(path, raw)
    return paths[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        functions = definition_functions()
        binding, review, contract, contract_sha, artifacts, documents, parse_errors = load_archive(
            args.input, args.input_sha256, args.contract, functions["artifact_bytes"], functions["validate_identity"])
        report = derive(binding, review, contract, args.input_sha256, contract_sha, artifacts, documents, parse_errors)
        output_dir = args.output_dir.resolve()
        require(output_dir not in (args.input.resolve().parent, args.contract.resolve().parent),
                "use an output directory distinct from input and contract directories")
        print(write_artifacts(output_dir, report, [Path(ref["path"]) for ref in artifacts.values()]))
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, RecursionError) as exc:
        parser.exit(2, f"STOP: {exc}\n")


if __name__ == "__main__":
    main()
