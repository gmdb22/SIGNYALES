"""
Signyales — Freeze Manifest
=============================
Records exactly what is about to be evaluated, for the freeze step before
participant field testing (roadmap Phase 9): the git commit, the SHA-256 of
each model file, the hub's config.py values, and the software versions on
this machine. Run it on the device that will run the sessions (normally the
Pi), right before the first participant, and keep the JSON with the results.

Read-only: it changes no files except the manifest it writes.

Usage (from pi-side/, venv active):
    python tools/freeze_manifest.py --model-dir model --out results/freeze_manifest.json
    python tools/freeze_manifest.py --model-dir model --strict   # exit 1 on any warning

Re-run it at the end of testing: if the hashes, commit or config differ from
the first manifest, something changed mid-study.
"""

import argparse
import dataclasses
import datetime
import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.config import HubConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_FILES = ("model.tflite", "labels.json", "scaler.json", "train_report.json")
PACKAGES = ("numpy", "pyserial", "tflite-runtime", "ai-edge-litert", "tensorflow", "tensorflow-cpu",
            "pyttsx3", "pyfiglet", "gpiozero")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def package_versions() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(model_dir: Path, note: str = "") -> dict:
    warnings = []
    cfg = HubConfig()

    commit = git("rev-parse", "HEAD")
    dirty = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    if not commit:
        warnings.append("not inside a git checkout (or git is not installed): commit unknown")
    if dirty:
        warnings.append(f"{len(dirty)} uncommitted change(s) in the repo; commit or discard "
                        f"them before freezing")

    files = {}
    for name in MODEL_FILES:
        path = model_dir / name
        if path.is_file():
            files[name] = {"sha256": sha256_of(path), "bytes": path.stat().st_size}
        else:
            files[name] = None
            if name != "train_report.json":
                warnings.append(f"{name} missing from {model_dir}")

    labels = None
    if files.get("labels.json"):
        try:
            labels = json.loads((model_dir / "labels.json").read_text())
        except ValueError as exc:
            warnings.append(f"labels.json is not valid JSON ({exc})")

    model_check = {"loaded": False}
    if all(files.get(n) for n in ("model.tflite", "labels.json", "scaler.json")):
        from signyales_hub.model_runtime import GestureClassifier
        clf = GestureClassifier(str(model_dir), expected_window=cfg.window_size_samples,
                                expected_features=cfg.feature_count)
        if clf.available:
            inp = clf.input_details[0]
            model_check = {
                "loaded": True,
                "input_shape": [int(d) for d in inp["shape"]],
                "input_dtype": getattr(inp["dtype"], "__name__", str(inp["dtype"])),
                "classes": len(clf.labels),
                "silent_labels_present": sorted(set(cfg.silent_labels) & set(clf.labels)),
            }
        else:
            warnings.append("the hub could not load the model (see the log warning for why)")

    train_report = None
    if files.get("train_report.json"):
        try:
            r = json.loads((model_dir / "train_report.json").read_text())
            train_report = {
                "created": r.get("created"),
                "git_commit": r.get("git", {}).get("commit"),
                "seed": r.get("args", {}).get("seed"),
                "quantized_int8": r.get("export", {}).get("quantized_int8"),
                "test_accuracy": r.get("test", {}).get("accuracy"),
                "data_fingerprint_sha256": r.get("data", {}).get("fingerprint_sha256"),
                "samples_per_label": r.get("data", {}).get("samples_per_label"),
            }
        except ValueError as exc:
            warnings.append(f"train_report.json is not valid JSON ({exc})")

    config = dataclasses.asdict(cfg)
    config = {k: (list(v) if isinstance(v, tuple) else v) for k, v in config.items()}

    return {
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
        "git": {
            "commit": commit or None,
            "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
            "describe": git("describe", "--tags", "--always", "--dirty") or None,
            "uncommitted_changes": dirty,
        },
        "model_dir": str(model_dir.resolve()),
        "model_files": files,
        "labels": labels,
        "model_check": model_check,
        "train_report": train_report,
        "config": config,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "packages": package_versions(),
        },
        "warnings": warnings,
    }


def main():
    p = argparse.ArgumentParser(description="Record the commit, model hashes and config before testing")
    p.add_argument("--model-dir", default="model")
    p.add_argument("--out", default="results/freeze_manifest.json",
                    help="Where to write the manifest JSON (default: results/freeze_manifest.json)")
    p.add_argument("--note", default="", help="Free text stored in the manifest, e.g. 'pilot session'")
    p.add_argument("--strict", action="store_true", help="Exit with code 1 if there are any warnings")
    args = p.parse_args()

    manifest = build_manifest(Path(args.model_dir), args.note)

    out = Path(args.out)
    if out.exists():
        print(f"Refusing to overwrite {out}. Pass a new --out name.")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2))

    print(f"Commit:   {manifest['git']['commit']} ({manifest['git']['describe']})")
    model_sha = (manifest["model_files"].get("model.tflite") or {}).get("sha256")
    print(f"Model:    {model_sha or 'MISSING'}")
    print(f"Labels:   {manifest['labels']}")
    print(f"Loads in hub: {manifest['model_check']['loaded']}")
    for w in manifest["warnings"]:
        print(f"WARNING: {w}")
    print(f"Manifest written to {out}")
    return 1 if (args.strict and manifest["warnings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
