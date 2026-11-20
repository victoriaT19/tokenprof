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


# Keys small models used instead of ours in the Kaggle smoke run.
ALIASES = {
    "path": "file", "filepath": "file", "file_path": "file", "filename": "file", "target": "file",
    "start_line": "start", "line_start": "start", "from": "start",
    "end_line": "end", "line_end": "end", "to": "end",
    "new_string": "new", "new_text": "new", "content": "new", "text": "new", "replacement": "new",
    "code": "new", "new_lines": "new",
    "first_line": "first", "old": "first", "old_string": "first", "expected": "first",
}
SEARCH_WINDOW = 10


def normalize_argv(argv: list[str]) -> list[str]:
    """Map alias keys to ours and strip quotes the model wrapped around values."""
    out = []
    for tok in argv:
        if tok.startswith("--"):
            key = tok[2:].strip().strip("\"'").lower()
            out.append("--" + ALIASES.get(key, key))
        else:
            v = tok
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out.append(v)
    return out


def unescape(text: str) -> str:
    """Models sometimes send literal backslash-n instead of newlines."""
    if "\n" not in text and ("\\n" in text or "\\t" in text):
        text = (text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
                .replace('\\"', '"').replace("\\'", "'"))
    return text


def anchor(lines: list[str], start: int, first: str) -> int | None:
    """Line number holding `first` (first line only, spaces ignored): `start` if it
    matches, else the nearest match within SEARCH_WINDOW lines, else a unique match
    anywhere in the file, else None."""
    want = "".join(first.strip("\n").split("\n")[0].split())
    if not want:
        return start

    def same(i: int) -> bool:
        return 1 <= i <= len(lines) and "".join(lines[i - 1].split()) == want

    if same(start):
        return start
    for d in range(1, SEARCH_WINDOW + 1):
        for i in (start - d, start + d):
            if same(i):
                return i
    hits = [i for i in range(1, len(lines) + 1) if same(i)]
    return hits[0] if len(hits) == 1 else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--start", required=True, type=int)
    p.add_argument("--end", required=True, type=int)
    p.add_argument("--new", default="")
    p.add_argument("--first", default=None)
    a, _unknown = p.parse_known_args(normalize_argv(sys.argv[1:] if argv is None else argv))
    a.new = unescape(a.new)
    if a.first is not None:
        a.first = unescape(a.first)

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
    note = ""
    if a.first is not None and a.start <= n:
        found = anchor(lines, a.start, a.first)
        if found is None:
            print(f"ERROR: line {a.start} is not what you expected. Nothing changed. Current lines:")
            print(show(lines, a.start - CONTEXT, a.end + CONTEXT))
            return 1
        if found != a.start:
            shift = found - a.start
            note = f" (your line {a.start} is line {found} now; the range was shifted by {shift:+d})"
            a.start, a.end = found, min(n, a.end + shift)

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
          f"(file now has {len(updated)} lines){note}. Line numbers below are the new ones:")
    print(show(updated, a.start - CONTEXT, a.start + len(new_lines) - 1 + CONTEXT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
