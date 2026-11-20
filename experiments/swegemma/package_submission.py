"""Package a config folder as a competition submission.zip.

Usage:
    python package_submission.py submissions/full --model gemma-4-e4b-it-qat-w4a16-ct --out dist/full_e4b/submission.zip
    kaggle competitions submit gemma-4-developer-agent -f dist/full_e4b/submission.zip -m "..."

Sets every `model:` line to --model, writes eval_config.yaml with the per-task
budget below, and checks the rules from the harness README (allowed extensions,
no symlinks, root agent.yaml, < 3 GiB) before zipping. Kaggle rejects the
upload (HTTP 400) unless the file is named exactly submission.zip.
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
# Per-task budget used in Stage 1 inference. The scorer runs the hidden tasks one
# after another within 12 hours in total, so the time cap must fit that limit.
evaluation:
  timeout_seconds: {timeout}
  max_tool_calls: {calls}
  max_time_minutes: {minutes}
  max_turns: {turns}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--model", required=True, choices=sorted(ALLOWED_MODELS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--calls", type=int, default=100, help="max tool calls per task")
    parser.add_argument("--minutes", type=int, default=20, help="max wall-clock minutes per task")
    parser.add_argument("--timeout", type=int, default=300, help="seconds per command")
    parser.add_argument("--turns", type=int, default=500, help="max LLM turns per task")
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
    files["eval_config.yaml"] = EVAL_CONFIG.format(
        timeout=args.timeout, calls=args.calls, minutes=args.minutes, turns=args.turns
    ).encode("utf-8")
    assert total < MAX_BYTES, "submission over 3 GiB"
    models = {m for name, d in files.items() if name.endswith((".yaml", ".yml"))
              for m in re.findall(r"^\s*model:\s*(\S+)", d.decode("utf-8"), re.M)}
    assert models == {args.model}, models

    out = Path(args.out)
    if out.name != "submission.zip":
        raise SystemExit("--out must end in submission.zip (Kaggle rejects any other file name)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    print(f"{out}: {len(files)} files, model {args.model}")
    for name in files:
        print("  ", name)


if __name__ == "__main__":
    main()
