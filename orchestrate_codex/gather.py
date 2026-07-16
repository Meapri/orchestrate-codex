"""Local gather stages: durable fact packs and git snapshots."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _run(cmd: List[str], cwd: Path, timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return (proc.stdout or proc.stderr or "").strip()
    return (proc.stdout or "").strip()


def gather_git(project_root: str | Path = ".") -> Dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    git_root = _run(["git", "rev-parse", "--show-toplevel"], root)
    if not git_root:
        return {"ok": False, "error": "not a git repository", "root": str(root)}
    repo = Path(git_root)
    return {
        "ok": True,
        "root": str(repo),
        "branch": _run(["git", "branch", "--show-current"], repo) or "[detached]",
        "head": _run(["git", "rev-parse", "--short", "HEAD"], repo),
        "status": _run(["git", "status", "--short"], repo) or "clean",
        "log": _run(["git", "log", "--oneline", "-12"], repo),
        "diff_stat": _run(["git", "diff", "--stat", "HEAD"], repo)
        or _run(["git", "diff", "--stat"], repo),
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _version_from_tree(root: Path) -> str:
    plugin = root / ".codex-plugin" / "plugin.json"
    data = _read_json(plugin)
    if isinstance(data, dict) and data.get("version"):
        return str(data["version"])
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    init_files = list(root.glob("*/__init__.py"))
    for init in init_files[:5]:
        text = init.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return ""


def _list_skills(root: Path) -> List[str]:
    skills = root / "skills"
    if not skills.is_dir():
        return []
    return sorted(p.name for p in skills.iterdir() if p.is_dir() and not p.name.startswith("."))


def _mcp_tools_from_config(root: Path) -> List[str]:
    names: List[str] = []
    for rel in ("mcp_config.json", ".mcp.json"):
        data = _read_json(root / rel)
        if not isinstance(data, dict):
            continue
        # tools not always listed; fall through
    # Scan mcp_server.py tool name strings if present
    for path in root.glob("*/mcp_server.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"name":\s*"([a-z0-9_]+)"', text):
            name = m.group(1)
            if name not in names and ("codex" in name or name.startswith("google_") or name.startswith("orchestrate_")):
                names.append(name)
        for m in re.finditer(r'"(claude_codex_[a-z0-9_]+|grok_codex_[a-z0-9_]+|google_[a-z0-9_]+|orchestrate_[a-z0-9_]+)"', text):
            if m.group(1) not in names:
                names.append(m.group(1))
    return sorted(set(names))


def gather_durable_facts(project_root: str | Path = ".") -> Dict[str, Any]:
    """Deterministic product facts — no git diary / recent commits."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    version = _version_from_tree(root)
    tools = _mcp_tools_from_config(root)
    skills = _list_skills(root)
    has_license = (root / "LICENSE").is_file() or (root / "LICENSE.md").is_file()
    readme = root / "README.md"
    readme_preview = ""
    if readme.is_file():
        readme_preview = readme.read_text(encoding="utf-8", errors="replace")[:1500]
    facts = {
        "ok": True,
        "root": str(root),
        "name": root.name,
        "version": version or "[unknown]",
        "skills": skills,
        "mcp_tools_detected": tools,
        "has_license": has_license,
        "install_hints": [
            f'codex plugin marketplace add "{root}"',
            f"codex plugin add <name>@<marketplace>",
        ],
        "readme_preview_chars": len(readme_preview),
        "forbidden_in_output": [
            "session diary",
            "today we fixed",
            "HTTP 400 debug notes",
            "recent commits as product features",
        ],
        "text": _facts_as_text(
            root=root,
            version=version,
            skills=skills,
            tools=tools,
            has_license=has_license,
            readme_preview=readme_preview,
        ),
    }
    return facts


def _facts_as_text(
    *,
    root: Path,
    version: str,
    skills: List[str],
    tools: List[str],
    has_license: bool,
    readme_preview: str,
) -> str:
    lines = [
        "DURABLE FACT PACK (use only these product facts; ignore session diary)",
        f"Project root: {root}",
        f"Version: {version or '[unknown]'}",
        f"License file present: {has_license}",
        f"Skills: {', '.join(skills) if skills else '[none detected]'}",
        f"MCP tools detected: {', '.join(tools) if tools else '[none detected in tree]'}",
        "Do not invent tools, env vars, or install commands not listed here or in source_file.",
    ]
    if readme_preview:
        lines.append("Existing README preview (may be outdated; prefer facts above):")
        lines.append(readme_preview)
    return "\n".join(lines)


def run_gather(stage: Dict[str, Any], *, project_root: str = ".", args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = args or {}
    root = str(args.get("project_root") or project_root or ".")
    cap = str(stage.get("capability") or "")
    if cap == "local_git" or stage.get("id") == "gather_git":
        data = gather_git(root)
        data["text"] = json.dumps(data, ensure_ascii=False, indent=2)
        return data
    # default durable / local facts
    return gather_durable_facts(root)
