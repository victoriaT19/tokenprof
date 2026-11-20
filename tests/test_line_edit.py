"""Tests for the line-edit skill script used by the E4B competition config."""

import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "experiments/swegemma/submissions/lineedit/"
          "skills/line-edit/scripts/replace_lines.py")
spec = importlib.util.spec_from_file_location("replace_lines", SCRIPT)
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)

SRC = "def f(x):\n    a = 1\n    b = 2\n    return a + b\n"


def run(tmp_path, capsys, *args, content=SRC, name="m.py"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    code = rl.main(["--file", str(p), *args])
    return code, p.read_text(encoding="utf-8"), capsys.readouterr().out


def test_replace_a_range(tmp_path, capsys):
    code, text, out = run(tmp_path, capsys, "--start", "2", "--end", "3", "--new", "    a = 10\n    b = 20")
    assert code == 0 and text == "def f(x):\n    a = 10\n    b = 20\n    return a + b\n"
    assert "OK: replaced 2 line(s) with 2" in out and "    2:     a = 10" in out


def test_insert_before_a_line(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "4", "--end", "3", "--new", "    c = 3")
    assert code == 0 and text.splitlines()[3] == "    c = 3" and text.count("\n") == 5


def test_delete_lines(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "3", "--end", "3", "--new", "")
    assert code == 0 and "b = 2" not in text and text.count("\n") == 3


def test_last_line_keeps_trailing_newline(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "4", "--end", "4", "--new", "    return a * b")
    assert code == 0 and text.endswith("    return a * b\n")


def test_append_at_end(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "5", "--end", "4", "--new", "\nY = 1")
    assert code == 0 and text.endswith("    return a + b\n\nY = 1\n")


def test_bad_range_changes_nothing(tmp_path, capsys):
    code, text, out = run(tmp_path, capsys, "--start", "9", "--end", "9", "--new", "x")
    assert code == 1 and text == SRC and "the file has 4 lines" in out


def test_first_line_check_ignores_whitespace_and_refuses_mismatch(tmp_path, capsys):
    ok, _, _ = run(tmp_path, capsys, "--start", "2", "--end", "2", "--new", "    a = 5", "--first", "a=1")
    assert ok == 0
    code, text, out = run(tmp_path, capsys, "--start", "2", "--end", "2", "--new", "    a = 5", "--first", "c = 3")
    assert code == 1 and text == SRC and "not what you expected" in out and "    3:     b = 2" in out


def test_python_syntax_error_is_refused(tmp_path, capsys):
    code, text, out = run(tmp_path, capsys, "--start", "2", "--end", "2", "--new", "  a = (1")
    assert code == 1 and text == SRC and "break Python syntax" in out


def test_non_python_files_skip_the_syntax_check(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "1", "--end", "1", "--new", "key: (",
                        content="key: 1\n", name="c.yaml")
    assert code == 0 and text == "key: (\n"


def test_multi_line_first_is_checked_on_its_first_line_only(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "2", "--end", "3", "--new", "    a = 9\n    b = 9",
                        "--first", "    a = 1\n    b = 2")
    assert code == 0 and "a = 9" in text


def test_off_by_a_few_lines_is_shifted_to_the_expected_line(tmp_path, capsys):
    code, text, out = run(tmp_path, capsys, "--start", "1", "--end", "1", "--new", "    b = 5",
                          "--first", "b = 2")
    assert code == 0 and text == "def f(x):\n    a = 1\n    b = 5\n    return a + b\n"
    assert "is line 3 now" in out


def test_literal_backslash_n_is_turned_into_newlines(tmp_path, capsys):
    code, text, _ = run(tmp_path, capsys, "--start", "2", "--end", "3", "--new", "    a = 3\\n    b = 4")
    assert code == 0 and text == "def f(x):\n    a = 3\n    b = 4\n    return a + b\n"


def test_alias_keys_and_quoted_values_are_accepted(tmp_path, capsys):
    p = tmp_path / "m.py"
    p.write_text(SRC, encoding="utf-8")
    code = rl.main(["--path", f'"{p}"', "--start_line", '"2"', "--end_line", "2",
                    "--new_string", "    a = 8", "--unknown", "x"])
    assert code == 0 and "a = 8" in p.read_text(encoding="utf-8")


def test_show_lines_numbers_the_requested_range(tmp_path, capsys):
    spec2 = importlib.util.spec_from_file_location("show_lines", SCRIPT.with_name("show_lines.py"))
    sl = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(sl)
    p = tmp_path / "m.py"
    p.write_text(SRC, encoding="utf-8")
    assert sl.main(["--file", str(p), "--start", "2", "--end", "3"]) == 0
    out = capsys.readouterr().out
    assert "lines 2-3 of 4" in out and "    2:     a = 1" in out and "    3:     b = 2" in out
    assert "next: start=4" in out


def test_scripts_run_the_way_the_adk_skill_runner_runs_them(tmp_path):
    """Mimic SkillToolset: copy scripts to a temp dir, chdir there, runpy with --key value argv."""
    import subprocess
    import sys

    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "m.py").write_text(SRC, encoding="utf-8")
    files = {f"scripts/{p.name}": p.read_text(encoding="utf-8") for p in SCRIPT.parent.glob("*.py")}
    argv = ["scripts/replace_lines.py", "--file", "pkg/m.py", "--start", "2", "--end", "2",
            "--new", "    a = 42", "--first", "a = 1"]
    # Same shape as google.adk.tools.skill_toolset._build_wrapper_code (ADK 1.36.1).
    wrapper = (
        "import os, sys, runpy, tempfile\n"
        f"_files = {files!r}\n"
        "def _materialize_and_run():\n"
        "  _orig_cwd = os.getcwd()\n"
        "  with tempfile.TemporaryDirectory() as td:\n"
        "    for rel, content in _files.items():\n"
        "      full = os.path.join(td, rel); os.makedirs(os.path.dirname(full), exist_ok=True)\n"
        "      open(full, 'w', encoding='utf-8').write(content)\n"
        "    os.chdir(td)\n"
        "    try:\n"
        f"      sys.argv = {argv!r}\n"
        "      try:\n"
        "        runpy.run_path(sys.argv[0], run_name='__main__')\n"
        "      except SystemExit as e:\n"
        "        if e.code is not None and e.code != 0: raise e\n"
        "    finally:\n"
        "      os.chdir(_orig_cwd)\n"
        "_materialize_and_run()\n"
    )
    # A misleading PWD: the script must find the work dir through ADK's _orig_cwd.
    env = {**__import__("os").environ, "PWD": str(tmp_path / "elsewhere")}
    res = subprocess.run([sys.executable, "-c", wrapper], cwd=ws, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK: replaced 1 line(s)" in res.stdout
    assert "a = 42" in (ws / "pkg" / "m.py").read_text(encoding="utf-8")


def test_relative_path_resolves_against_the_workspace(tmp_path, capsys, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(SRC, encoding="utf-8")
    monkeypatch.setenv("PWD", str(tmp_path))
    assert rl.main(["--file", "pkg/m.py", "--start", "2", "--end", "2", "--new", "    a = 7"]) == 0
    assert "a = 7" in (tmp_path / "pkg" / "m.py").read_text(encoding="utf-8")
