"""Package a config folder as a competition submission.zip.

Usage:
    python package_submission.py submissions/full --model gemma-4-e4b-it-qat-w4a16-ct --out dist/full_e4b.zip

Sets every `model:` line to --model, writes eval_config.yaml with the per-task
budget below, and checks the rules from the harness README (allowed extensions,
no symlinks, root agent.yaml, < 3 GiB) before zipping.
"""

import argparse
import re
import zipfile
from pathlib import Path

ALLOWED_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}
ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
MAX_BYTES = 3 * 1024**3
EVAL_CONFIG = """\
# Per-task budget used in Stage 1 inference. Our profiled runs needed a median of
# 10 tool calls and under 3 minutes per task, far below these limits.
evaluation:
  timeout_seconds: 300
  max_tool_calls: 100
  max_time_minutes: 20
  max_turns: 500
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--model", required=True, choices=sorted(ALLOWED_MODELS))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.config)
    roots = [p for p in root.iterdir() if p.name in {"agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml"}]
    assert len(roots) == 1, f"need exactly one root config, found {roots}"
    files: dict[str, bytes] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"symlinks are not allowed: {path}")
        if not path.is_file() or path.name == "eval_config.yaml":
            continue
        if path.suffix not in ALLOWED_EXT:
            raise SystemExit(f"extension not allowed: {path}")
        data = path.read_bytes()
        if path.suffix in {".yaml", ".yml"}:
            text = re.sub(r"^(\s*model:\s*).*$", lambda m: m.group(1) + args.model,
                          data.decode("utf-8"), flags=re.M)
            data = text.encode("utf-8")
        files[path.relative_to(root).as_posix()] = data
        total += len(data)
    files["eval_config.yaml"] = EVAL_CONFIG.encode("utf-8")
    assert total < MAX_BYTES, "submission over 3 GiB"
    models = {m for name, d in files.items() if name.endswith((".yaml", ".yml"))
              for m in re.findall(r"^\s*model:\s*(\S+)", d.decode("utf-8"), re.M)}
    assert models == {args.model}, models

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    print(f"{out}: {len(files)} files, model {args.model}")
    for name in files:
        print("  ", name)


if __name__ == "__main__":
    main()
