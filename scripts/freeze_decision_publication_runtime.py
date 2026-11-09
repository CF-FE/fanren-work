"""Freeze the Mac managed publication binding for a new Fanren work unit."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from episode_delivery import ROOT, save_exact


def fixed_release(root, release):
    if (release.parent != root or re.fullmatch(r"[0-9a-f]{40}", release.name) is None
            or release.resolve(strict=True) != release):
        raise ValueError("managed binding must use a fixed release directory")
    record = json.loads((release / "install-receipt.json").read_bytes())
    if record["source_commit"] != release.name:
        raise ValueError("managed release does not match its installation receipt")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("store frozen runtime inputs outside the repository")

    support = Path.home().resolve() / "Library/Application Support"
    managed = support / "ProjectWorkflowTools/developer-inputs/fanren-work"
    current = managed / "current.json"
    if current.stat().st_mode & 0o077:
        parser.error("managed binding must be private")
    profile = json.loads(current.read_bytes())
    release = Path(profile["consumer"]["release"])
    consumer_python = Path(profile["consumer"]["python"])
    publisher_python = Path(profile["publisher"]["python"])
    config = Path(profile["publisher"]["config_ref"])
    if not config.is_absolute() or config.stat().st_mode & 0o077:
        parser.error("publication configuration must be an absolute private reference")
    try:
        consumer_receipt = fixed_release(support / "HerdrDecisionConsumer.releases", release)
        publisher_release = publisher_python.parents[2]
        publisher_receipt = fixed_release(support / "DecisionOutcomePublisher/releases", publisher_release)
    except (IndexError, OSError, ValueError) as error:
        parser.error(str(error))
    if (consumer_python != Path(consumer_receipt["python"])
            or publisher_python != Path(publisher_receipt["python"])
            or publisher_python != publisher_release / ".venv/bin/python"
            or publisher_python.parent.resolve() != publisher_python.parent):
        parser.error("managed interpreter does not match its installation receipt")
    for interpreter in (consumer_python, publisher_python):
        if not interpreter.is_absolute() or not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            parser.error("managed interpreter is unavailable")
    if not (release / "app/scripts/decision_service_client.py").is_file():
        parser.error("managed consumer release is unavailable")

    runtime = {"project": "fanren-work", "task_id": args.task, "unit_id": args.unit,
               "consumer": {"release": str(release), "python": str(consumer_python)},
               "publisher": {"python": str(publisher_python), "config_ref": str(config)}}
    raw = (json.dumps(runtime, indent=2, sort_keys=True) + "\n").encode()
    save_exact(output, raw)
    print(json.dumps({"path": str(output), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}))


if __name__ == "__main__":
    main()
