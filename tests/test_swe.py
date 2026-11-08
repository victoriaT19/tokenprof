import json

from tokenprof.cli import main
from tokenprof.swe import (detect, fit_overhead, load_results_dir, load_run, max_output_from_submission,
                           profile, split_task_prompt)

TASK = (
    "You are evaluating a software engineering task for repository o/r.\n\n"
    "Problem Statement:\nBug in foo.\n\n"
    "## Task Budget (Session terminates when any budget is exhausted)\n- Time allowance: 30 min\n\n"
    "## Execution Environment Rules\n- Command output limit: 5000 characters\n\n"
    "## Instructions:\n0. Work under /workspace\n\n"
    "## Workspace Layout\n```\n./pkg\n./pkg/a.py\n```\n"
)


def obs(payload, tool):
    return {"content": json.dumps(payload), "extra": {"tool_name": tool}}


def step(i, tools, observation, pt, ct, message="thinking", author="root"):
    return {
        "step_id": i, "source": "agent", "message": message,
        "tool_calls": [{"tool_call_id": f"c{i}", "function_name": n, "arguments": a} for n, a in tools],
        "observation": observation,
        "metrics": {"prompt_tokens": pt, "completion_tokens": ct, "cached_tokens": 0},
        "extra": {"event_type": "thinking", "author": author},
    }


def trace(task=TASK, extra_steps=None):
    big = {"status": "ok", "content": "x" * 4000, "is_truncated": True}
    steps = [
        {"step_id": 1, "source": "system", "message": "S" * 700, "extra": {"event_type": "system_instruction"}},
        {"step_id": 2, "source": "user", "message": task, "extra": {"event_type": "task_prompt"}},
        step(3, [("read_file", {"filepath": "pkg/a.py"})], obs(big, "read_file"), 1000, 100),
        step(4, [("edit_file", {"filepath": "pkg/a.py", "old_string": "a", "new_string": "b"})],
             obs({"status": "error", "error_message": "old_string not found"}, "edit_file"), 2400, 2500),
        step(5, [("read_file", {"filepath": "pkg/a.py"})], obs(big, "read_file"), 3300, 50),
        step(6, [("edit_file", {"filepath": "pkg/a.py", "old_string": "x", "new_string": "y"})],
             obs({"status": "ok"}, "edit_file"), 4600, 80),
        step(7, [("submit_patch", {})], obs({"status": "ok", "patch_size": 10}, "submit_patch"), 4700, 20),
        step(8, [], {}, 4800, 30),
        {"step_id": 9, "source": "agent", "message": "done", "extra": {"event_type": "final", "author": "root"}},
    ]
    return {"schema_version": "ATIF-v1.7", "steps": steps + (extra_steps or [])}


def test_split_task_prompt_sections():
    sections = split_task_prompt(TASK)
    assert list(sections) == ["header", "problem", "budget", "rules", "instructions", "layout"]
    assert sum(sections.values()) == len(TASK)


def test_load_run_keeps_root_calls_and_counts_sub_agent():
    sub = [step(10, [], {}, 900, 100, author="analyzer")]
    run = load_run(trace(extra_steps=sub), instance_id="t1", resolved=False)
    assert len(run.calls) == 6
    assert run.sub_agent_tokens == 1000
    assert run.calls[1].tool_calls[0].status == "error"
    assert run.calls[0].tool_calls[0].truncated
    assert run.submit_index() == 4


def test_detectors():
    run = load_run(trace(), instance_id="t1", resolved=False)
    kinds = [f.kind for f in detect(run)]
    assert kinds.count("unscoped_truncated_read") == 2
    # The edit in between failed, so the file did not change: the second read is a repeat.
    assert "repeated_read" in kinds
    assert "thinking_burst" in kinds
    assert "tool_error" in kinds
    post = next(f for f in detect(run) if f.kind == "post_submit_calls")
    assert post.tokens == 4830
    assert "unverified_submit" in kinds


def test_successful_edit_resets_repeated_read_and_verified_submit():
    t = trace()
    t["steps"][3]["observation"] = obs({"status": "ok"}, "edit_file")
    t["steps"][6]["tool_calls"] = [{"tool_call_id": "v", "function_name": "run_command",
                                    "arguments": {"command": "pytest tests/test_a.py"}},
                                   {"tool_call_id": "s", "function_name": "submit_patch", "arguments": {}}]
    run = load_run(t, instance_id="t1", resolved=True)
    kinds = [f.kind for f in detect(run)]
    assert "repeated_read" not in kinds
    assert "unverified_submit" not in kinds


def test_fit_overhead_recovers_intercept_and_profile_sums_to_reported():
    runs = []
    for n, chars in enumerate([1000, 3000, 6000]):
        t = trace(task=TASK + "y" * chars)
        total = 700 + len(TASK) + chars
        t["steps"][2]["metrics"]["prompt_tokens"] = round(500 + total / 3.2)
        runs.append(load_run(t, instance_id=f"t{n}"))
    overhead, slope = fit_overhead(runs)
    assert abs(overhead - 500) < 2
    assert abs(1 / slope - 3.2) < 0.01
    profile(runs)
    for run in runs:
        for call, parts in zip(run.calls, run.anatomy):
            assert abs(sum(parts.values()) - call.prompt_tokens) < 1e-6


def test_cli_swe(tmp_path, capsys):
    results = tmp_path / "run" / "results"
    (results / "traces").mkdir(parents=True)
    (results / "traces" / "trace_t1.json").write_text(json.dumps(trace()), encoding="utf-8")
    (tmp_path / "run" / "run_results.jsonl").write_text(
        json.dumps({"instance_id": "t1", "resolved": "True", "repo": "o/r"}) + "\n", encoding="utf-8")
    assert load_results_dir(results)[0].resolved is True
    out = tmp_path / "s.json"
    main(["swe", str(results), "--label", "base", "--json", str(out)])
    summary = json.loads(out.read_text(encoding="utf-8"))[0]
    assert summary["resolved"] == 1 and summary["llm_calls"] == 6
    assert "| Resolved | 1 (100.0%) |" in capsys.readouterr().out


def test_context_overflow_and_nudges():
    t = trace()
    t["steps"].insert(5, {"step_id": 99, "source": "system", "message": "Please continue",
                          "extra": {"event_type": "continuation_nudge", "author": "harness"}})
    err = ("Sandbox execution error: litellm.BadRequestError: ContextWindowExceededError: "
           "This model's maximum context length is 32768 tokens.")
    run = load_run(t, instance_id="t1", resolved=False, error=err)
    kinds = {f.kind: f for f in detect(run)}
    assert kinds["continuation_nudge"].detail.startswith("the harness had to nudge the agent 1 time")
    assert "4800 tokens" in kinds["context_overflow"].detail
    other = load_run(trace(), instance_id="t2", error="Agent exceeded session timeout (30.0 min)")
    assert [f.kind for f in detect(other) if f.kind == "agent_error"] == ["agent_error"]
    assert load_run(trace(), instance_id="t3", error="None").error is None


def test_sub_agent_result_and_compaction_in_anatomy():
    t = trace()
    t["steps"][2]["tool_calls"] = [{"tool_call_id": "a", "function_name": "code_analyzer_agent", "arguments": {}}]
    t["steps"][2]["observation"] = {}
    t["steps"].insert(3, {"step_id": 50, "source": "system", "observation": {"content": "R" * 900}})
    t["steps"][7]["metrics"]["prompt_tokens"] = 1500  # call 4 shrank: history was compacted
    run = load_run(t, instance_id="t1")
    assert run.calls[0].tool_calls[0].output == "R" * 900
    profile([run])
    assert "tool_output:code_analyzer_agent" in run.anatomy[1]
    assert run.anatomy[4].get("compacted_history", 0) > 0
    assert "tool_output:read_file" not in run.anatomy[4]
    for call, parts in zip(run.calls, run.anatomy):
        assert abs(sum(parts.values()) - call.prompt_tokens) < 1e-6


def test_output_cap_hit_flags_repetition_loops(tmp_path):
    t = trace()
    t["steps"][3]["message"] = "I will check the file again. " * 400
    t["steps"][3]["metrics"]["completion_tokens"] = 6144
    run = load_run(t, instance_id="t1")
    cap = [f for f in detect(run, max_output_tokens=6144) if f.kind == "output_cap_hit"]
    assert len(cap) == 1 and "repetition loop" in cap[0].detail
    assert not [f for f in detect(run) if f.kind == "output_cap_hit"]  # cap unknown: not judged
    cfg = tmp_path / "submission" / "configs"
    cfg.mkdir(parents=True)
    (cfg / "sampling.yaml").write_text("temperature: 0.2\nmax_output_tokens: 6144\n", encoding="utf-8")
    assert max_output_from_submission(tmp_path / "results") == 6144


def test_no_submit_and_submit_without_edit():
    t = trace()
    t["steps"] = [s for s in t["steps"] if not any(
        c.get("function_name") == "submit_patch" for c in s.get("tool_calls") or [])]
    kinds = [f.kind for f in detect(load_run(t, instance_id="t1"))]
    assert "no_submit" in kinds and "post_submit_calls" not in kinds
    t = trace()
    t["steps"] = [s for s in t["steps"] if not any(
        c.get("function_name") == "edit_file" for c in s.get("tool_calls") or [])]
    kinds = [f.kind for f in detect(load_run(t, instance_id="t2"))]
    assert "submit_without_edit" in kinds and "unverified_submit" not in kinds


def test_results_dir_reads_packed_traces(tmp_path):
    import tarfile
    src = tmp_path / "src" / "traces"
    src.mkdir(parents=True)
    (src / "trace_t1.json").write_text(json.dumps(trace()), encoding="utf-8")
    packed = tmp_path / "run"
    packed.mkdir()
    with tarfile.open(packed / "traces.tar.gz", "w:gz") as tar:
        tar.add(src, arcname="traces")
    (packed / "run_results.jsonl").write_text(json.dumps({"instance_id": "t1", "resolved": True}) + "\n",
                                              encoding="utf-8")
    runs = load_results_dir(packed)
    assert [r.instance_id for r in runs] == ["t1"] and runs[0].resolved is True
