---
name: line-edit
description: View numbered lines of a repository file and replace a line range by number, without copying the old text. Refuses edits that break Python syntax.
---

# line-edit

Two scripts. You never retype old code: you give line numbers and the new text.

1. See numbered lines (`read_file` shows no numbers):

       run_skill_script(skill_name="line-edit", file_path="scripts/show_lines.py",
                        args={"file": "<path>", "start": "<first>", "end": "<last>"})

2. Replace lines `start`..`end` (inclusive) with new text:

       run_skill_script(skill_name="line-edit", file_path="scripts/replace_lines.py",
                        args={"file": "<path>", "start": "<first>", "end": "<last>",
                              "first": "<current text of line start>", "new": "<replacement lines>"})

- `file_path` is always `scripts/show_lines.py` or `scripts/replace_lines.py`; the repository file goes in `args` as `"file"`.
- Write `new` with its full indentation. An empty `new` deletes the lines.
- To insert without replacing, set `end` to `start - 1`; the new lines go before `start`.
- `first` is checked ignoring spaces; if it does not match, nothing changes and the real lines are shown.
- The reply prints the edited region with the new line numbers. Lines below the edit shift.
- On a Python syntax error nothing is written; fix the indentation or brackets and call again.
