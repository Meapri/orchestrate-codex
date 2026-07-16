"""Local verify heuristics for durable / change outputs."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

RECENCY_PATTERNS = [
    r"\btoday we\b",
    r"\bjust fixed\b",
    r"\brecently fixed\b",
    r"\bHTTP 400\b",
    r"\bsession diary\b",
    r"\bthis session\b",
    r"\b방금 수정\b",
    r"\b오늘 고친\b",
    r"\b최근 작업\b",
]


def verify_text(
    text: str,
    *,
    doc_class: str = "durable",
    fact_pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    warnings: List[str] = []
    body = text or ""
    if not body.strip():
        warnings.append("empty_output")
    # Recency / session-diary tone is only forbidden in durable and transform docs;
    # change docs (PR, release notes) are expected to describe recent work.
    if doc_class in {"durable", "transform"}:
        for pat in RECENCY_PATTERNS:
            if re.search(pat, body, re.I):
                warnings.append(f"recency_language:{pat}")
    if doc_class == "durable":
        if re.search(r"\b(git log|diff --stat|HEAD~)\b", body, re.I):
            warnings.append("git_internals_in_durable_doc")
        tools = []
        allowed: set = set()
        if isinstance(fact_pack, dict):
            tools = list(fact_pack.get("mcp_tools_detected") or [])
            # CLI commands / console scripts are legitimate references, not hallucinated tools.
            allowed = set(tools) | set(fact_pack.get("cli_commands") or [])
        # flag tool-like tokens not in fact pack when pack known
        if tools:
            claimed = set(re.findall(r"\b(?:google|claude_codex|grok_codex|orchestrate)_[a-z0-9_]+\b", body))
            unknown = sorted(t for t in claimed if t not in allowed)
            # only warn if we found claimed tools and some unknown — allow subset
            # unknown means claimed not in detected list
            for t in unknown:
                warnings.append(f"tool_not_in_fact_pack:{t}")
    ok = not any(w.startswith("empty") for w in warnings)
    return {
        "ok": ok and len([w for w in warnings if w.startswith("recency")]) == 0,
        "warnings": warnings,
        "warning_count": len(warnings),
        "text": (
            "verify ok"
            if not warnings
            else "verify warnings:\n" + "\n".join(f"- {w}" for w in warnings)
        ),
    }
