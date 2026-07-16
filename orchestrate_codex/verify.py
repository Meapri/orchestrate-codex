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
    warnings.extend(_completeness_warnings(body))
    blocking = ("empty", "recency", "unclosed_code_fence", "truncated")
    return {
        "ok": not any(w.startswith(blocking) for w in warnings),
        "warnings": warnings,
        "warning_count": len(warnings),
        "text": (
            "verify ok"
            if not warnings
            else "verify warnings:\n" + "\n".join(f"- {w}" for w in warnings)
        ),
    }


def _completeness_warnings(body: str) -> List[str]:
    """Detect a document that was cut off mid-generation (e.g. the leaf hit max_tokens).

    verify used to pass a truncated README as clean because it only checked tone/tools.
    """
    out: List[str] = []
    text = body.strip()
    # Only meaningful for real documents; skip short snippets to avoid false positives.
    if len(text) < 200:
        return out
    if text.count("```") % 2 == 1:
        out.append("unclosed_code_fence")
    terminal = ".!?:)]`\"'”』」…"
    # A trailing heading with no body, or a short unpunctuated fragment under it = cut section.
    headings = [m.start() for m in re.finditer(r"(?m)^#{1,6}\s", text)]
    if headings:
        nl = text.find("\n", headings[-1])
        after = text[nl + 1:].strip() if nl != -1 else ""
        if not after or (len(after) < 25 and after[-1] not in terminal):
            out.append("truncated_trailing_section")
    # Ends mid-sentence: last non-empty line isn't closed by punctuation / table / list / fence.
    last = text.splitlines()[-1].strip()
    if last and "|" not in last and not last.startswith(("#", "-", "*", ">", "```")):
        if last[-1] not in terminal:
            out.append("truncated_midsentence")
    return out
