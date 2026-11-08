"""Download a finished Kaggle run and keep what the analysis needs.

Usage:
    python fetch_run.py base_e4b [--from-dir DIR]

Writes:
    data/<name>/...                      full output, unpacked (git-ignored), for `tokenprof swe`
    results/<name>/run_meta.json         run settings and resolution rate
    results/<name>/run_results.jsonl     one line per task: resolved, patch, test output, errors
    results/<name>/traces.tar.gz         ATIF traces + per-task logs (reproduce every number)
"""

import argparse
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).parent
USER = "victoriatauanny"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--from-dir", help="already downloaded kernel output (skip the download)")
    args = parser.parse_args()

    data = HERE / "data" / args.name
    if args.from_dir:
        src = Path(args.from_dir)
    else:
        src = HERE / "data" / f"_download_{args.name}"
        src.mkdir(parents=True, exist_ok=True)
        slug = "tokenprof-swe-" + args.name.replace("_", "-")
        subprocess.run(["kaggle", "kernels", "output", f"{USER}/{slug}", "-p", str(src)], check=True)
    run_dir = src / args.name
    if data.exists():
        shutil.rmtree(data)
    shutil.copytree(run_dir, data)

    out = HERE / "results" / args.name
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(run_dir / "run_meta.json", out / "run_meta.json")
    with (run_dir / "run_results.jsonl").open(encoding="utf-8") as f_in, \
            (out / "run_results.jsonl").open("w", encoding="utf-8") as f_out:
        for line in f_in:
            row = json.loads(line)
            row.pop("trace", None)  # repr of a Python object, not data
            f_out.write(json.dumps(row, ensure_ascii=False) + "\n")
    with tarfile.open(out / "traces.tar.gz", "w:gz") as tar:
        for sub in ("traces", "logs"):
            if (run_dir / "results" / sub).exists():
                tar.add(run_dir / "results" / sub, arcname=sub)
    if (run_dir / "submission").exists():
        shutil.copytree(run_dir / "submission", out / "submission", dirs_exist_ok=True)
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    print(f"{args.name}: {meta['resolved']}/{meta['tasks']} resolved -> {out}")


if __name__ == "__main__":
    main()
