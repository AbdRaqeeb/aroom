"""Agent runner adapters: Claude Code, OpenCode, and a deterministic mock."""

from __future__ import annotations

import json
import os
import select
import shlex
import signal
import subprocess
import time
from typing import Any

from . import util


def emit(run_dir: str, run: dict, actor: str, kind: str, text: str, detail: Any = None) -> None:
    text = " ".join((text or "").split())
    if len(text) > 300:
        text = text[:299] + "…"
    event: dict[str, Any] = {"ts": util.now_iso(), "actor": actor, "kind": kind, "text": text}
    if detail:
        event["detail"] = detail
    util.append_jsonl(os.path.join(run_dir, "events.ndjson"), event)
    run["updated"] = util.now_iso()
    run["last_event"] = f"{actor}: {text}"[:300]
    run["events_count"] = int(run.get("events_count", 0)) + 1
    util.write_json(os.path.join(run_dir, "run.json"), run)


_HEARTBEATS: dict[str, float] = {}


def _heartbeat(run_dir: str, run: dict, actor: str, text: str = "thinking…") -> None:
    """Mark a long model call as alive without flooding the event stream."""
    key = f"{run_dir}:{actor}"
    now = time.time()
    if now - _HEARTBEATS.get(key, 0) < 8:
        return
    _HEARTBEATS[key] = now
    run["updated"] = util.now_iso()
    run["last_event"] = f"{actor}: {text}"
    util.write_json(os.path.join(run_dir, "run.json"), run)


def summarize_error(log_path: str) -> str:
    """Pull the useful failure reason out of a runner log."""
    lines = util.tail(log_path, 400).splitlines()
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "error":
            err = obj.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            if message:
                return str(message)[:400]
        if obj.get("type") == "rate_limit_event":
            info = obj.get("rate_limit_info") or {}
            if info.get("status") in {"rejected", "allowed_warning"} and float(info.get("utilization") or 0) >= 1:
                return "rate limit reached; wait for the reset or switch models"
        if obj.get("type") == "result":
            text = str(obj.get("result") or "")
            if obj.get("is_error") or "limit" in text.lower():
                return text[:400]
        message = obj.get("message") or {}
        if obj.get("type") == "assistant" and message.get("model") == "<synthetic>":
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    return str(block["text"])[:400]
    return ""


def _tool_text(name: str, data: dict) -> str:
    data = data or {}
    raw = name or ""
    name = {
        "read": "Read",
        "write": "Write",
        "edit": "Edit",
        "multiedit": "MultiEdit",
        "bash": "Bash",
        "shell": "Bash",
        "grep": "Grep",
        "glob": "Glob",
        "webfetch": "WebFetch",
        "websearch": "WebSearch",
        "task": "Task",
        "todowrite": "TodoWrite",
        "notebookedit": "NotebookEdit",
    }.get(raw.lower(), raw)
    path = data.get("file_path") or data.get("path") or data.get("notebook_path") or data.get("filePath") or ""
    if name in {"Edit", "MultiEdit", "Write", "Read", "NotebookEdit"}:
        return f"{name} {path or ''}".strip()
    if name == "Bash":
        command = str(data.get("command") or data.get("cmd") or data.get("script") or "")
        return f"Bash {command}"[:220]
    if name in {"Glob", "Grep"}:
        return f"{name} {data.get('pattern', '')}".strip()
    if name in {"WebFetch", "WebSearch"}:
        return f"{name} {data.get('url') or data.get('query') or ''}".strip()
    if name == "Task":
        return f"Task {data.get('description', '')}".strip()
    if name == "TodoWrite":
        return "Plan updated"
    if name:
        return name
    return "tool"


def _handle_claude(line: str, run_dir: str, run: dict, actor: str) -> None:
    try:
        obj = json.loads(line)
    except ValueError:
        if line.strip():
            emit(run_dir, run, actor, "log", line)
        return
    kind = obj.get("type")
    if kind == "system" and obj.get("subtype") == "init":
        emit(run_dir, run, actor, "start", f"session {obj.get('session_id', '')[:8]} · {obj.get('model', '')}")
        run["session"] = obj.get("session_id")
        return
    if kind == "assistant":
        for block in (obj.get("message") or {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                emit(run_dir, run, actor, "say", block["text"])
            elif btype == "tool_use":
                emit(
                    run_dir,
                    run,
                    actor,
                    "tool",
                    _tool_text(block.get("name", ""), block.get("input") or {}),
                    {"tool": block.get("name"), "input": block.get("input")},
                )
        return
    if kind == "user":
        for block in (obj.get("message") or {}).get("content", []):
            if block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                text = content if isinstance(content, str) else json.dumps(content)[:300]
                emit(run_dir, run, actor, "warn", f"tool error: {text}")
        return
    if kind == "result":
        cost = obj.get("total_cost_usd") or obj.get("cost_usd") or 0
        if cost:
            run["cost_usd"] = round(float(run.get("cost_usd", 0)) + float(cost), 4)
        emit(
            run_dir,
            run,
            actor,
            "done",
            f"finished in {round((obj.get('duration_ms') or 0) / 1000)}s"
            + (f" · ${float(cost):.2f}" if cost else ""),
        )
        return
    text = obj.get("text") or obj.get("message")
    if isinstance(text, str) and text.strip():
        emit(run_dir, run, actor, "log", text)


def _handle_opencode(line: str, run_dir: str, run: dict, actor: str) -> None:
    try:
        obj = json.loads(line)
    except ValueError:
        if line.strip():
            emit(run_dir, run, actor, "log", line)
        return

    part = obj.get("part") if isinstance(obj.get("part"), dict) else {}
    ntype = obj.get("type") or ""
    ptype = part.get("type") or ""

    if ntype == "text" or ptype == "text":
        text = part.get("text") or obj.get("text")
        if isinstance(text, str) and text.strip():
            emit(run_dir, run, actor, "say", text)
        return
    if ntype in {"tool_use", "tool"} or ptype == "tool":
        tool = part.get("tool") or obj.get("tool") or obj.get("name") or "tool"
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        payload = state.get("input") or part.get("input") or obj.get("input") or {}
        if isinstance(payload, str):
            payload = {"path": payload}
        emit(run_dir, run, actor, "tool", _tool_text(tool, payload), {"tool": tool})
        return
    if ntype == "step_finish":
        cost = part.get("cost") or obj.get("cost") or 0
        if cost:
            run["cost_usd"] = round(float(run.get("cost_usd", 0)) + float(cost), 4)
        return
    if ntype in {"step_start", "reasoning"} or ptype == "reasoning":
        _heartbeat(run_dir, run, actor)
        return
    text = obj.get("text") or obj.get("message")
    if isinstance(text, str) and text.strip():
        emit(run_dir, run, actor, "log", text)


def build_command(runner: str, prompt: str, model: str, run_dir: str, repo: str) -> list[str]:
    if runner == "claude":
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--add-dir",
            run_dir,
            "--add-dir",
            repo,
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd
    if runner == "opencode":
        cmd = ["opencode", "run", prompt, "--format", "json", "--auto"]
        if model:
            cmd.extend(["--model", model])
        return cmd
    raise SystemExit(f"unknown runner: {runner}")


def _spawn(cmd: list[str], cwd: str, env: dict[str, str], run_dir: str, run: dict, actor: str, runner: str) -> int:
    log_path = os.path.join(run_dir, f"{actor}.log")
    emit(run_dir, run, actor, "start", f"$ {runner} session")
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        run["pid"] = proc.pid
        util.write_json(os.path.join(run_dir, "run.json"), run)
        deadline = time.time() + float(run.get("_timeout_min", 60)) * 60
        timed_out = False
        assert proc.stdout is not None
        while True:
            if proc.poll() is not None:
                # drain whatever is buffered
                rest = proc.stdout.read()
                if rest:
                    for line in rest.splitlines():
                        log.write(line + "\n")
                break
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                line = proc.stdout.readline()
                if line == "":
                    break
                log.write(line)
                log.flush()
                line = line.rstrip("\n")
                if runner == "opencode":
                    _handle_opencode(line, run_dir, run, actor)
                else:
                    _handle_claude(line, run_dir, run, actor)
            if time.time() > deadline:
                timed_out = True
                emit(run_dir, run, actor, "warn", "timeout — stopping the session")
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except OSError:
                    pass
                time.sleep(2)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                break
        code = proc.wait()
        if timed_out:
            code = -9
        emit(run_dir, run, actor, "exit", f"exit {code}")
        return code


def run_agent(
    kind: str,
    prompt: str,
    cwd: str,
    run_dir: str,
    run: dict,
    cfg: dict,
    timeout_min: float | None = None,
) -> dict:
    spec = cfg["agents"].get(kind, {})
    runner = spec.get("runner", "claude")
    model = spec.get("model", "") or ""
    timeout = timeout_min or spec.get("timeout_min", 45)
    run[f"{kind}_runner"] = runner
    run[f"{kind}_model"] = model
    if kind == "builder":
        run["runner"] = runner
        run["model"] = model
    run["_timeout_min"] = timeout
    util.write_json(os.path.join(run_dir, "run.json"), run)

    if runner == "mock":
        result = mock_agent(kind, prompt, cwd, run_dir, run, cfg)
        run.pop("_timeout_min", None)
        util.write_json(os.path.join(run_dir, "run.json"), run)
        return result

    env = dict(os.environ)
    env.update(
        {
            "AR_PROJECT": run.get("project", ""),
            "AR_TASK": run.get("task", ""),
            "AR_RUN_ID": run.get("run_id", ""),
            "AR_WORKTREE": cwd,
            "AR_RUN_DIR": run_dir,
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
        }
    )
    cmd = build_command(runner, prompt, model, run_dir, cfg["repo"])
    env_script = cfg.get("isolation", {}).get("env_script")
    prefix = ""
    if env_script and os.path.isfile(os.path.join(cwd, env_script)):
        prefix = f"set -a; source {shlex.quote(env_script)}; set +a; "
    # Login shell so nvm/fnm/asdf paths are present for the agent and its hooks.
    inner = shlex.join(cmd)
    cmd = ["bash", "-lc", f"{prefix}exec {inner}"]

    started = time.time()
    code = _spawn(cmd, cwd, env, run_dir, run, kind, runner)
    run["last_duration_s"] = round(time.time() - started)
    run.pop("_timeout_min", None)
    util.write_json(os.path.join(run_dir, "run.json"), run)
    return {"returncode": code, "cost_usd": float(run.get("cost_usd", 0)), "runner": runner}


def mock_agent(kind: str, prompt: str, cwd: str, run_dir: str, run: dict, cfg: dict) -> dict:
    """A deterministic stand-in used by tests and `--mock`."""
    task = run.get("task", "task")
    emit(run_dir, run, kind, "start", f"mock {kind}")
    delay = float(
        os.environ.get(f"AR_MOCK_{kind.upper()}_DELAY")
        or os.environ.get("AR_MOCK_DELAY", "0")
        or 0
    )
    if delay:
        time.sleep(delay)
    if kind == "builder":
        target = os.path.join(cwd, "agent-room-mock", f"{util.slug(task)}.md")
        util.ensure_dir(os.path.dirname(target))
        round_no = run.get("round", 1)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"# mock output for {task} (round {round_no})\n\n{prompt[:400]}\n")
        emit(run_dir, run, kind, "tool", f"Write agent-room-mock/{util.slug(task)}.md")
        util.run(["git", "-C", cwd, "add", "."], check=False)
        proc = util.run(
            ["git", "-C", cwd, "commit", "-m", f"feat(mock): {task} (round {round_no})"],
            check=False,
        )
        if proc.returncode == 0:
            emit(run_dir, run, kind, "tool", f"Commit feat(mock): {task}")
        time.sleep(0.2)
    elif kind == "verifier":
        fail_first = os.environ.get("AR_MOCK_FAIL_FIRST") == "1"
        round_no = run.get("round", 1)
        verdict = "FAIL" if (fail_first and round_no <= 1) else "PASS"
        body = (
            f"# Verify {task}\n\nVerdict: {verdict}\n\n"
            f"- [x] mock criterion one — evidence: mock file\n"
            f"- [x] mock criterion two — evidence: mock file\n\n"
            f"Checks: mock ok\n"
        )
        if verdict == "FAIL":
            body += "\n## Issues\n\n- [blocker] agent-room-mock/mock.md:1 — mock failure for the fix loop\n"
        with open(os.path.join(run_dir, "verify.md"), "w", encoding="utf-8") as fh:
            fh.write(body)
        emit(run_dir, run, kind, "say", f"verdict {verdict}")
        time.sleep(0.2)
    elif kind == "researcher":
        target = run.get("output") or run.get("research_output") or os.path.join(cwd, "docs", "research", "mock-research.md")
        util.ensure_dir(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(f"# Mock research\n\nPrompt: {prompt[:200]}\n\nSources checked on {util.today()}.\n")
        emit(run_dir, run, kind, "tool", f"Write {os.path.relpath(target, cwd)}")
    emit(run_dir, run, kind, "done", "mock finished")
    return {"returncode": 0, "cost_usd": 0.0, "runner": "mock"}
