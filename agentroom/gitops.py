"""Git worktree and merge helpers."""

from __future__ import annotations

import os

from . import util


class GitError(RuntimeError):
    pass


def _git(repo: str, *args: str, check: bool = True) -> util.subprocess.CompletedProcess:
    proc = util.run(["git", "-C", repo, *args])
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


def rev(repo: str, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def branch_exists(repo: str, branch: str) -> bool:
    proc = _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
    return proc.returncode == 0


def worktree_exists(repo: str, path: str) -> bool:
    proc = _git(repo, "worktree", "list", "--porcelain", check=False)
    target = util.expand(path)
    for line in proc.stdout.splitlines():
        if line.startswith("worktree ") and util.expand(line[len("worktree ") :]) == target:
            return True
    return False


def is_clean(repo: str, include_untracked: bool = False) -> tuple[bool, str]:
    """Content-based cleanliness check.

    `git status` flags files whose mtime/stat changed even when the content is
    identical (dev servers touch generated files). Diff against the index is the
    authority for tracked content; untracked files are ignored by default.
    """
    unstaged = _git(repo, "diff", "--quiet", check=False).returncode
    staged = _git(repo, "diff", "--cached", "--quiet", check=False).returncode
    clean = unstaged == 0 and staged == 0
    if include_untracked:
        others = _git(repo, "ls-files", "--others", "--exclude-standard", check=False).stdout.strip()
        if others:
            clean = False
    proc = _git(repo, "status", "--porcelain", check=False)
    return clean, proc.stdout.strip()


def add_worktree(repo: str, path: str, branch: str, base: str) -> str:
    path = util.expand(path)
    if os.path.exists(path):
        if worktree_exists(repo, path):
            raise GitError(
                f"worktree already exists at {path}. Finish it with `aroom merge`, "
                f"or remove it: git -C {repo} worktree remove --force {path}"
            )
        raise GitError(f"path already exists and is not a worktree: {path}")
    util.ensure_dir(os.path.dirname(path))
    if branch_exists(repo, branch):
        raise GitError(
            f"branch {branch} already exists. Delete it first: git -C {repo} branch -D {branch}"
        )
    _git(repo, "worktree", "add", "-b", branch, path, base)
    return path


def remove_worktree(repo: str, path: str, branch: str | None = None) -> None:
    target = util.expand(path)
    # A verifier or dev server may still be running from this worktree; it
    # would keep ports and files open after the worktree is removed.
    util.kill_cwd_processes(target)
    if worktree_exists(repo, target):
        _git(repo, "worktree", "remove", "--force", target, check=False)
    _git(repo, "worktree", "prune", check=False)
    if branch and branch_exists(repo, branch):
        _git(repo, "branch", "-D", branch, check=False)


def commit_count(worktree: str, base: str) -> int:
    proc = _git(worktree, "rev-list", "--count", f"{base}..HEAD", check=False)
    try:
        return int(proc.stdout.strip() or "0")
    except ValueError:
        return 0


def changed_files(worktree: str, base: str) -> list[str]:
    proc = _git(worktree, "diff", "--name-only", f"{base}...HEAD", check=False)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def merge_base(repo: str, base: str, branch: str) -> str:
    proc = _git(repo, "merge-base", base, branch, check=False)
    return proc.stdout.strip()


def diff_stat(worktree: str, base: str) -> dict:
    proc = _git(worktree, "diff", "--numstat", f"{base}...HEAD", check=False)
    files = insertions = deletions = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        files += 1
        try:
            insertions += int(parts[0])
        except ValueError:
            pass
        try:
            deletions += int(parts[1])
        except ValueError:
            pass
    return {"files": files, "insertions": insertions, "deletions": deletions}


def write_diff(worktree: str, base: str, path: str) -> dict:
    proc = _git(worktree, "diff", f"{base}...HEAD", check=False)
    util.ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout)
    return diff_stat(worktree, base)


def merge_squash(repo: str, branch: str, base: str, message: str) -> str:
    clean, status = is_clean(repo)
    if not clean:
        raise GitError(f"main checkout is not clean; commit or stash first:\n{status}")
    current = _git(repo, "branch", "--show-current").stdout.strip()
    if current != base:
        _git(repo, "checkout", base)
    proc = _git(repo, "merge", "--squash", branch, check=False)
    if proc.returncode != 0:
        # --squash does not create MERGE_HEAD, so `merge --abort` is a no-op.
        # Reset the base back to its clean pre-merge state; the branch keeps its work.
        _git(repo, "reset", "--hard", "HEAD", check=False)
        raise GitError(f"squash merge failed:\n{proc.stdout}\n{proc.stderr}")
    commit = _git(repo, "commit", "-m", message, check=False)
    if commit.returncode != 0:
        # A commit hook rejected the message. The squash is staged but uncommitted;
        # drop it so the base stays clean. The branch still has the work.
        _git(repo, "reset", "--hard", "HEAD", check=False)
        raise GitError(f"commit failed:\n{commit.stdout}\n{commit.stderr}")
    return rev(repo)


GIT_NET_ENV = {"GIT_TERMINAL_PROMPT": "0"}


def remote_exists(repo: str, remote: str = "origin") -> bool:
    proc = util.run(["git", "-C", repo, "remote", "get-url", remote], env=GIT_NET_ENV)
    return proc.returncode == 0


def remote_branch_sha(repo: str, remote: str, branch: str) -> str:
    proc = util.run(
        ["git", "-C", repo, "ls-remote", "--heads", remote, branch],
        env=GIT_NET_ENV,
        timeout=45,
    )
    if proc.returncode != 0:
        raise GitError(f"git ls-remote {remote} {branch} failed:\n{proc.stdout}\n{proc.stderr}")
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(f"refs/heads/{branch}"):
            return parts[0]
    return ""


def is_ancestor(repo: str, ancestor: str, descendant: str) -> bool:
    proc = util.run(
        ["git", "-C", repo, "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    return proc.returncode == 0


def push_branch(
    repo: str,
    remote: str,
    branch: str,
    set_upstream: bool = True,
    no_verify: bool = True,
) -> str:
    args = ["git", "-C", repo, "push"]
    if no_verify:
        args.append("--no-verify")
    if set_upstream:
        args.append("-u")
    args.extend([remote, branch])
    proc = util.run(args, env=GIT_NET_ENV, timeout=600)
    if proc.returncode != 0:
        raise GitError(f"git push {remote} {branch} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def current_branch(repo: str) -> str:
    return _git(repo, "branch", "--show-current", check=False).stdout.strip()


def status_summary(repo: str) -> dict:
    branch = current_branch(repo)
    clean, status = is_clean(repo, include_untracked=False)
    return {"branch": branch, "clean": clean, "status": status.splitlines()[:20], "head": rev(repo)}


def remote_link(url: str) -> str:
    """Best-effort web URL for a git remote (GitHub/GitLab/Bitbucket and friends)."""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("git@") and ":" in url:
        host, path = url[4:].split(":", 1)
        return f"https://{host}/{path.removesuffix('.git')}"
    if url.startswith("ssh://"):
        rest = url[len("ssh://") :]
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        host, _, path = rest.partition("/")
        return f"https://{host}/{path.removesuffix('.git')}"
    if url.startswith("http://") or url.startswith("https://"):
        return url.removesuffix(".git")
    return ""


def inventory(repo: str) -> dict:
    """Branches, worktrees and remotes for the git details modal."""
    remotes: list[dict] = []
    proc = util.run(["git", "-C", repo, "remote", "-v"], check=False)
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen:
            seen.add(parts[0])
            url = parts[1]
            remotes.append({"name": parts[0], "url": url, "link": remote_link(url)})

    fmt = (
        "%(refname:short)%x00%(objectname:short)%x00%(upstream:short)%x00"
        "%(upstream:track)%x00%(committerdate:relative)%x00%(subject)"
    )
    branches: list[dict] = []
    current = current_branch(repo)
    proc = util.run(["git", "-C", repo, "for-each-ref", f"--format={fmt}", "refs/heads"], check=False)
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        if len(parts) < 6:
            parts = line.split("\0")
        if len(parts) < 6:
            parts = (parts + [""] * 6)[:6]
        branches.append(
            {
                "name": parts[0],
                "sha": parts[1],
                "upstream": parts[2],
                "track": parts[3],
                "when": parts[4],
                "subject": parts[5],
                "current": parts[0] == current,
            }
        )
    branches.sort(key=lambda b: (not b["current"], b["name"]))

    worktrees: list[dict] = []
    proc = util.run(["git", "-C", repo, "worktree", "list", "--porcelain"], check=False)
    block: dict = {}
    for line in proc.stdout.splitlines() + [""]:
        if not line.strip():
            if block:
                worktrees.append(
                    {
                        "path": block.get("worktree", ""),
                        "head": block.get("HEAD", "")[:7],
                        "branch": (block.get("branch") or "").removeprefix("refs/heads/"),
                        "detached": "detached" in block,
                        "bare": "bare" in block,
                        "locked": block.get("locked", ""),
                    }
                )
                block = {}
            continue
        key, _, value = line.partition(" ")
        block[key] = value
    return {"remotes": remotes, "branches": branches, "worktrees": worktrees}


def detail(repo: str) -> dict:
    """Local git facts for the dashboard; no network calls."""
    branch = current_branch(repo)
    head = rev(repo)
    clean, status = is_clean(repo, include_untracked=False)
    lines = [line for line in status.splitlines() if line.strip()]

    def out(*args: str) -> str:
        return util.run(["git", "-C", repo, *args], check=False).stdout.strip()

    subject = out("log", "-1", "--pretty=%s")
    when = out("log", "-1", "--pretty=%cr")
    short = out("rev-parse", "--short", "HEAD")
    remote_url = out("remote", "get-url", "origin")
    upstream = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead = behind = None
    if upstream:
        counts = out("rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
    worktree_lines = out("worktree", "list", "--porcelain").splitlines()
    worktrees = sum(1 for line in worktree_lines if line.startswith("worktree "))
    branches = [
        line for line in out("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines() if line.strip()
    ]
    remote_name = "origin" if remote_url else ""
    if not remote_name:
        remotes = out("remote").splitlines()
        remote_name = remotes[0] if remotes else ""
        if remote_name:
            remote_url = out("remote", "get-url", remote_name)
    remote_label = remote_link(remote_url).replace("https://", "").removesuffix("/")
    return {
        "branch": branch,
        "head": head,
        "short": short,
        "subject": subject,
        "when": when,
        "clean": clean,
        "changes": len(lines),
        "status": lines[:20],
        "remote": remote_url,
        "remote_name": remote_name,
        "remote_link": remote_link(remote_url),
        "remote_label": remote_label,
        "branch_count": len(branches),
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "worktrees": worktrees,
    }


def stage_and_commit(repo: str, paths: list[str], message: str) -> bool:
    if paths:
        _git(repo, "add", "--", *paths)
    proc = _git(repo, "commit", "-m", message, check=False)
    return proc.returncode == 0
