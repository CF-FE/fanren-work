"""Read the owner's episode node-to-run registry without dispatching or importing code."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def overview(registry_path):
    registry = json.loads(Path(registry_path).read_bytes())
    if registry["schema_version"] != 1 or registry["workflow"] != "episode08-01-continuation":
        raise ValueError("unexpected episode registry")
    definition = json.loads((Path(__file__).resolve().parents[1] / "workflows" /
                             "episode08-01-continuation" / "definition.json").read_bytes())
    units = []
    seen = set()
    for unit in registry["units"]:
        if unit["task_id"] in seen:
            raise ValueError("duplicate task in episode registry")
        if unit["node"] not in definition["nodes"]:
            raise ValueError("unknown episode node")
        seen.add(unit["task_id"])
        state = Path(unit["state"]).resolve()
        with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True)) as db:
            run = json.loads(db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()[0])
        if run["task"] != unit["task_id"] or run["source_sha256"] != unit["source_sha256"]:
            raise ValueError("registered task or workflow revision mismatch")
        entrypoint = Path(unit["entrypoint"])
        if hashlib.sha256(entrypoint.read_bytes()).hexdigest() != run["outputs"]["prepare"]["entrypoint_sha256"]:
            raise ValueError("registered entrypoint revision mismatch")
        choice = run["decisions"].get("owner_acceptance", {}).get("choice")
        units.append({"node": unit["node"], "task_id": run["task"], "unit_id": run["input"]["unit_id"],
                      "status": run["status"], "step": run["step"], "owner_choice": choice,
                      "business_accepted": run["status"] == "FINISHED" and run["step"] == "accepted",
                      "scope": run["input"]["scope"], "deliverable_kind": run["input"]["deliverable_kind"],
                      "action": run["action"], "state": str(state), "entrypoint": str(entrypoint),
                      "source_sha256": run["source_sha256"]})
    final_task = registry.get("final_unit_task_id")
    final = next((unit for unit in units if unit["task_id"] == final_task), None)
    accepted = bool(final and final["node"] == "final.delivery" and final["business_accepted"]
                    and final["deliverable_kind"] == "episode_delivery")
    return {"workflow": registry["workflow"], "contact_ref": registry["contact_ref"],
            "domain_status": "ACCEPTED" if accepted else "IN_PROGRESS", "episode_accepted": accepted,
            "units": units, "completed_inputs": registry["completed_inputs"],
            "control": registry["control"], "remaining": registry["remaining"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    try:
        print(json.dumps(overview(parser.parse_args().registry), ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
