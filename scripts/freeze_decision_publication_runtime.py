"""Freeze the Mac managed publication binding for a new Fanren work unit."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from episode_delivery import ROOT, save_exact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("store frozen runtime inputs outside the repository")

    managed = Path.home() / "Library/Application Support/ProjectWorkflowTools/developer-inputs/fanren-work"
    current = managed / "current.json"
    if current.stat().st_mode & 0o077:
        parser.error("managed binding must be private")
    profile = json.loads(current.read_bytes())
    consumer = profile["consumer"]
    publisher = profile["publisher"]
    config = Path(publisher["config_ref"])
    if config.stat().st_mode & 0o077:
        parser.error("publication configuration must be private")
    for interpreter in (consumer["python"], publisher["python"]):
        path = Path(interpreter)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            parser.error("managed interpreter is unavailable")
    release = Path(consumer["release"])
    if not release.is_absolute() or not (release / "app/scripts/decision_service_client.py").is_file():
        parser.error("managed consumer release is unavailable")

    runtime = {"project": "fanren-work", "task_id": args.task, "unit_id": args.unit,
               "consumer": consumer, "publisher": publisher}
    raw = (json.dumps(runtime, indent=2, sort_keys=True) + "\n").encode()
    save_exact(output, raw)
    print(json.dumps({"path": str(output), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}))


if __name__ == "__main__":
    main()
