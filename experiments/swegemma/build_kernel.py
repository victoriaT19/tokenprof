"""Build a Kaggle script kernel for one experiment run.

Usage:
    python build_kernel.py runs/smoke.json            # writes kernels/<name>/
    kaggle kernels push -p kernels/<name>

A run file is JSON with: name, model, budget, and optionally submission_dir
(a local folder inlined into the script; omitted = official sample submission),
task_ids / stride / limit, concurrency and dump_sources.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
MODELS = [
    "google/gemma-4/Other/gemma-4-12b-it-qat-w4a16-ct/2",
    "google/gemma-4/Other/gemma-4-e4b-it-qat-w4a16-ct/2",
    "google/gemma-4/Other/gemma-4-e2b-it-qat-w4a16-ct/2",
    "google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2",
]
ALLOWED = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}


def main(run_file: str, username: str = "victoriatauanny") -> Path:
    run = json.loads(Path(run_file).read_text(encoding="utf-8"))
    files = {}
    if run.get("submission_dir"):
        root = (Path(run_file).parent / run["submission_dir"]).resolve()
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix in ALLOWED and p.suffix != ".safetensors":
                text = p.read_text(encoding="utf-8")
                if p.suffix in (".yaml", ".yml") and run.get("model"):
                    # One config folder serves every model size: the run file picks the model.
                    text = re.sub(r"^(\s*model:\s*).*$", lambda m: m.group(1) + run["model"], text, flags=re.M)
                files[p.relative_to(root).as_posix()] = text
    src = (HERE / "runner_template.py").read_text(encoding="utf-8")
    src = src.replace("__RUN__", repr(run)).replace("__SUBMISSION_FILES__", repr(files))
    slug = "tokenprof-swe-" + run["name"].replace("_", "-")
    out = HERE / "kernels" / run["name"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.py").write_text(src, encoding="utf-8")
    meta = {
        "id": f"{username}/{slug}",
        "title": slug,
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": False,
        "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
        "competition_sources": ["gemma-4-developer-agent"],
        "kernel_sources": [],
        "model_sources": MODELS,
        "machine_shape": "NvidiaL4",
        # Same image as the official starter notebook: the wheelhouse is built for Python 3.12.
        "docker_image": "gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461",
        "docker_image_pinning_type": "original",
    }
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(out)
    return out


if __name__ == "__main__":
    main(*sys.argv[1:])
