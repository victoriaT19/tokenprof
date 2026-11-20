"""Print a range of lines of a workspace file with their line numbers.

`read_file` returns raw text without numbers, and small models miscount lines.
Use this view before `replace_lines.py`.

    --file   path relative to the repository root (or absolute)
    --start  first line (default 1)
    --end    last line (default start + 79); at most 150 lines are shown
"""

import argparse
import os
import sys

MAX_LINES = 150


# Kept self-contained: the skill runner executes each script with runpy.run_path
# from a temporary directory, so sibling scripts cannot be imported.
def workspace_root() -> str:
    # Same lookup as replace_lines.py: ADK keeps the sandbox work dir in `_orig_cwd`.
    frame = sys._getframe()
    while frame is not None:
        orig = frame.f_locals.get("_orig_cwd")
        if isinstance(orig, str) and os.path.isdir(orig):
            return orig
        frame = frame.f_back
    pwd = os.environ.get("PWD")
    if pwd and os.path.isdir(pwd) and os.path.realpath(pwd) != os.path.realpath(os.getcwd()):
        return pwd
    for cand in ("/workspace", "/work", "/testbed"):
        if os.path.isdir(cand):
            return cand
    return os.getcwd()


def show(lines: list[str], lo: int, hi: int) -> str:
    lo, hi = max(1, lo), min(len(lines), hi)
    return "\n".join(f"{i:>5}: {lines[i - 1].rstrip(chr(10))}" for i in range(lo, hi + 1))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=None)
    aliases = {"path": "file", "filepath": "file", "file_path": "file", "filename": "file",
               "start_line": "start", "end_line": "end"}
    norm = []
    for tok in sys.argv[1:] if argv is None else argv:
        if tok.startswith("--"):
            key = tok[2:].strip().strip("\"'").lower()
            norm.append("--" + aliases.get(key, key))
        else:
            norm.append(tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'" else tok)
    a, _unknown = p.parse_known_args(norm)

    path = a.file if os.path.isabs(a.file) else os.path.join(workspace_root(), a.file)
    if not os.path.isfile(path):
        print(f"ERROR: file not found: {a.file}")
        return 1
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines(keepends=True)
    start = max(1, a.start)
    end = a.end if a.end is not None else start + 79
    end = min(len(lines), end, start + MAX_LINES - 1)
    print(f"{a.file}: lines {start}-{end} of {len(lines)}")
    print(show(lines, start, end))
    if end < len(lines):
        print(f"... more lines below; next: start={end + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
