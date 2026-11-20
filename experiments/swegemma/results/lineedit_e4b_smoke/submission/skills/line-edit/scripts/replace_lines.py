"""Replace a range of lines in a workspace file, addressed by line numbers.

Small models fail `edit_file` because they cannot reproduce `old_string` exactly.
Here they only give line numbers (as shown by `read_file`) and the new text.

    --file   path relative to the repository root (or absolute)
    --start  first line to replace (1-indexed, inclusive)
    --end    last line to replace (inclusive); use start-1 to insert before `start`
    --new    replacement text (may be empty to delete the lines)
    --first  optional: expected text of line `start`, checked ignoring whitespace

Python files are compiled after the edit; on a syntax error the file is restored
and nothing changes. The edited region is printed with its new line numbers.
"""

import argparse
import os
import sys

CONTEXT = 3


def workspace_root() -> str:
    # ADK's skill runner saves the sandbox work dir in `_orig_cwd`, then chdirs to a
    # temporary directory and runs this file with runpy, so the variable is on the
    # call stack. The work dir differs between sandboxes (/work, /workspace, a temp dir).
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
    p.add_argument("--start", required=True, type=int)
    p.add_argument("--end", required=True, type=int)
    p.add_argument("--new", default="")
    p.add_argument("--first", default=None)
    a = p.parse_args(argv)

    path = a.file if os.path.isabs(a.file) else os.path.join(workspace_root(), a.file)
    if not os.path.isfile(path):
        print(f"ERROR: file not found: {a.file}")
        return 1
    with open(path, encoding="utf-8") as f:
        original = f.read()
    lines = original.splitlines(keepends=True)
    n = len(lines)

    if not (1 <= a.start <= n + 1) or not (a.start - 1 <= a.end <= n):
        print(f"ERROR: bad range {a.start}-{a.end}; the file has {n} lines. "
              "Use the line numbers from your latest read_file of this file.")
        return 1
    if a.first is not None and a.start <= n:
        want = "".join(a.first.split())
        got = "".join(lines[a.start - 1].split())
        if want and want != got:
            print(f"ERROR: line {a.start} is not what you expected. Nothing changed. Current lines:")
            print(show(lines, a.start - CONTEXT, a.end + CONTEXT))
            return 1

    new = a.new.replace("\r\n", "\n")
    new_lines = new.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n") and a.end < n:
        new_lines[-1] += "\n"
    if a.end == n and n and lines[-1].endswith("\n") and new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    updated = lines[: a.start - 1] + new_lines + lines[a.end:]
    text = "".join(updated)

    if path.endswith(".py"):
        try:
            compile(text, path, "exec")
        except SyntaxError as e:
            print(f"ERROR: the edit would break Python syntax (line {e.lineno}: {e.msg}). "
                  "Nothing changed. Check indentation and brackets, then retry.")
            return 1

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    removed = a.end - a.start + 1
    print(f"OK: replaced {removed} line(s) with {len(new_lines)} in {a.file} "
          f"(file now has {len(updated)} lines). Line numbers below are the new ones:")
    print(show(updated, a.start - CONTEXT, a.start + len(new_lines) - 1 + CONTEXT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
