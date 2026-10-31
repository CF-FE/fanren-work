"""Compare the complete installed distribution set with the documented lock.

Uses only the standard library. Does not import ML packages or verify their bytes.
"""

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path):
    expected = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--"):
            if line not in {"--index-url https://pypi.org/simple", "--require-hashes",
                            "--only-binary=:all:", "--no-binary=sox"}:
                raise ValueError(f"Unsupported lock option on line {number}")
            continue
        match = re.fullmatch(r"(.+?)\s+--hash=sha256:[0-9a-f]{64}", line)
        if not match:
            raise ValueError(f"Unsupported lock entry on line {number}")
        requirement = match[1]
        pin = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", requirement)
        wheel = re.fullmatch(r"([A-Za-z0-9_.-]+)\s+@\s+(https://\S+)", requirement)
        if pin:
            name, version = pin.groups()
        elif wheel:
            name, url = wheel.groups()
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            parts = filename[:-4].split("-") if filename.endswith(".whl") else []
            if len(parts) != 5 or normalize(parts[0]) != normalize(name):
                raise ValueError(f"Unsupported direct wheel on line {number}")
            version = parts[1]
        else:
            raise ValueError(f"Unpinned requirement on line {number}")
        key = normalize(name)
        if key in expected:
            raise ValueError(f"Duplicate normalized lock name: {key}")
        expected[key] = version
    if len(expected) != 92:
        raise ValueError(f"Expected the complete 92-package lock, got {len(expected)}")
    return expected


def read_installed():
    installed = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.version
        if not name or not version:
            raise ValueError("Distribution has missing Name or Version metadata")
        key = normalize(name)
        if key in installed:
            raise ValueError(f"Duplicate installed distribution: {key}")
        installed[key] = version
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        expected = read_lock(args.lock)
        installed = read_installed()
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    missing = sorted(expected.keys() - installed.keys())
    extra = sorted(installed.keys() - expected.keys())
    changed = {
        name: {"expected": expected[name], "installed": installed[name]}
        for name in sorted(expected.keys() & installed.keys())
        if expected[name] != installed[name]
    }
    result = {"expected_count": len(expected), "installed_count": len(installed),
              "missing": missing, "extra": extra, "version_mismatch": changed}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if missing or extra or changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
