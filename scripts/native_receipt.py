"""Snapshot one completed native Codex turn as user/final evidence, without model analysis."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def snapshot(transcript, thread_id, turn_id, contact_ref, *, request_only=False):
    path = Path(transcript).resolve()
    raw = path.read_bytes()
    records = [(number, json.loads(line)) for number, line in enumerate(raw.splitlines(), 1) if line.strip()]
    sessions = [row["payload"]["id"] for _, row in records if row.get("type") == "session_meta"]
    if not sessions or set(sessions) != {thread_id}:
        raise ValueError("native transcript session mismatch")
    active = False
    started = False
    context_seen = False
    users = []
    finals = []
    completions = []
    selected = []
    for number, row in records:
        payload = row.get("payload", {})
        event = payload.get("type")
        if row.get("type") == "event_msg" and event == "task_started":
            active = payload.get("turn_id") == turn_id
            if active:
                if started:
                    raise ValueError("duplicate native turn start")
                started = True
                selected.append(number)
        if not active:
            continue
        if row.get("type") == "turn_context":
            if payload.get("turn_id") != turn_id:
                raise ValueError("native turn context mismatch")
            context_seen = True
        elif row.get("type") == "response_item" and event == "message":
            text = "\n".join(item.get("text", "") for item in payload.get("content", [])
                             if item.get("type") in ("input_text", "output_text"))
            if payload.get("role") == "user" and contact_ref in text:
                users.append({"type": "userMessage", "content": [{"type": "text", "text": text}]})
                selected.append(number)
            elif payload.get("role") == "assistant" and payload.get("phase") in ("final", "final_answer") and text.strip():
                finals.append({"type": "agentMessage", "phase": "final_answer", "text": text})
                selected.append(number)
        elif row.get("type") == "event_msg" and event == "task_complete":
            if payload.get("turn_id") != turn_id:
                raise ValueError("native completion turn mismatch")
            completions.append(payload.get("last_agent_message", ""))
            selected.append(number)
            active = False
    if not started or not context_seen or not users:
        raise ValueError("native task or contact not confirmed")
    if not request_only and (len(finals) != 1 or len(completions) != 1):
        raise ValueError("native task, contact or completed final not confirmed")
    def visible(text):
        # The native completion event omits this renderer-owned trailing metadata.
        return re.sub(r"\s*<oai-mem-citation>.*?</oai-mem-citation>\s*$", "", text, flags=re.DOTALL).strip()
    if not request_only and visible(finals[0]["text"]) != visible(completions[0]):
        raise ValueError("native final and completion message mismatch")
    return {"source_kind": "codex_transcript_request.v1" if request_only else "codex_transcript_snapshot.v1",
            "thread": {"id": thread_id},
            "turns": [{"id": turn_id, "items": users if request_only else [*users, finals[0]]}],
            "provenance": {"source": {"path": str(path), "bytes": len(raw),
                                       "sha256": hashlib.sha256(raw).hexdigest()},
                           "observed_at": datetime.now(timezone.utc).isoformat(),
                           "selected_line_numbers": selected,
                           "comparison_normalization": "trailing_oai_memory_citation_removed"}}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--turn", required=True)
    parser.add_argument("--contact-ref", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--request-only", action="store_true", help="snapshot the native request for binding before completion")
    args = parser.parse_args()
    try:
        output = Path(args.output).resolve()
        if output.is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("store private native evidence outside the repository")
        value = snapshot(args.transcript, args.thread, args.turn, args.contact_ref, request_only=args.request_only)
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with output.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"source_kind": value["source_kind"], "path": str(output), "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest(), "thread": args.thread, "turn": args.turn}))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
