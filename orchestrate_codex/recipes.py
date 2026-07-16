"""Built-in supervised recipes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from . import policy

DEFAULT_BINDINGS = {
    "chat": "claude_codex_chat",
    "chat_alt": "grok_codex_chat",
    "chat_gemini": "google_antigravity_chat",
    "grounded_search": "google_grounded_search",
    "image": "google_antigravity_generate_image",
    "write_ag": "google_antigravity_write",
}

RECIPES: Dict[str, Dict[str, Any]] = {
    "durable_readme": {
        "id": "durable_readme",
        "doc_class": "durable",
        "description": "Write or rewrite a product README from a fact pack, not from recent session work.",
        "stages": [
            {
                "id": "gather_facts",
                "kind": "gather",
                "capability": "local",
                "instruction": (
                    "Collect deterministic facts only: version, install commands, MCP tool names, "
                    "auth env vars, license. Do not include today's bugfixes or session diary."
                ),
                "tool": None,
            },
            {
                "id": "outline",
                "kind": "plan",
                "capability": "chat",
                "binding": "chat",
                "instruction": "Produce a README outline from the fact pack only.",
            },
            {
                "id": "draft",
                "kind": "generate",
                "capability": "chat",
                "binding": "chat",
                "instruction": (
                    "Write the full README from outline + fact pack. Forbid recency tone "
                    "(today/fixed/HTTP 400 debug notes). No invented tools."
                ),
            },
            {
                "id": "verify",
                "kind": "verify",
                "capability": "local",
                "instruction": (
                    "Check tool names and commands against the fact pack; flag session-diary language."
                ),
                "tool": None,
            },
        ],
    },
    "change_pr": {
        "id": "change_pr",
        "doc_class": "change",
        "description": "Draft a PR description from git changes.",
        "stages": [
            {
                "id": "gather_git",
                "kind": "gather",
                "capability": "local_git",
                "instruction": "Collect branch, status, commits, and diff stat/summary.",
                "tool": None,
            },
            {
                "id": "draft",
                "kind": "generate",
                "capability": "chat",
                "binding": "chat",
                "instruction": "Write PR summary, test plan, and risks grounded only in the git snapshot.",
            },
        ],
    },
    "research_then_write": {
        "id": "research_then_write",
        "doc_class": "transform",
        "description": "Grounded search then synthesize with a chat leaf.",
        "stages": [
            {
                "id": "search",
                "kind": "generate",
                "capability": "grounded_search",
                "binding": "grounded_search",
                "instruction": "Answer with sources via Google grounded search leaf.",
            },
            {
                "id": "synthesize",
                "kind": "generate",
                "capability": "chat",
                "binding": "chat",
                "instruction": "Synthesize a clear brief from search results without inventing sources.",
            },
        ],
    },
    "direct_chat": {
        "id": "direct_chat",
        "doc_class": "direct",
        "description": "Single leaf chat (orchestration optional).",
        "stages": [
            {
                "id": "chat",
                "kind": "generate",
                "capability": "chat",
                "binding": "chat",
                "instruction": "One-shot chat with the bound leaf.",
            }
        ],
    },
}


def list_recipes() -> List[Dict[str, Any]]:
    out = []
    for recipe in RECIPES.values():
        out.append(
            {
                "id": recipe["id"],
                "doc_class": recipe["doc_class"],
                "description": recipe["description"],
                "stage_count": len(recipe["stages"]),
            }
        )
    return out


def get_recipe(recipe_id: str) -> Dict[str, Any]:
    key = (recipe_id or "").strip()
    if key not in RECIPES:
        raise ValueError(f"unknown recipe: {recipe_id}. Known: {sorted(RECIPES)}")
    return deepcopy(RECIPES[key])


def explain_recipe(recipe_id: str) -> Dict[str, Any]:
    recipe = get_recipe(recipe_id)
    pol = policy.get_policy(recipe["doc_class"])
    return {"recipe": recipe, "context_policy": pol, "default_bindings": DEFAULT_BINDINGS}


def plan_recipe(
    recipe_id: str,
    *,
    args: Optional[Dict[str, Any]] = None,
    bindings: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    recipe = get_recipe(recipe_id)
    pol = policy.get_policy(recipe["doc_class"])
    bind = dict(DEFAULT_BINDINGS)
    if bindings:
        bind.update({str(k): str(v) for k, v in bindings.items() if str(v).strip()})
    args = args or {}
    steps = []
    for i, stage in enumerate(recipe["stages"]):
        tool = stage.get("tool")
        binding = stage.get("binding")
        if tool is None and binding:
            tool = bind.get(str(binding))
        steps.append(
            {
                "index": i,
                "id": stage["id"],
                "kind": stage["kind"],
                "capability": stage.get("capability"),
                "tool": tool,
                "instruction": stage.get("instruction"),
                "suggested_arguments": _suggest_args(stage, args, pol),
                "status": "pending",
            }
        )
    return {
        "recipe_id": recipe["id"],
        "doc_class": recipe["doc_class"],
        "context_policy": pol,
        "bindings": bind,
        "mode": "supervised",
        "note": (
            "Execute each step's tool in order via Codex MCP. "
            "This orchestrator does not call leaf HTTP APIs itself (v0.2 supervised)."
        ),
        "steps": steps,
        "user_args": args,
    }


def _suggest_args(stage: Dict[str, Any], args: Dict[str, Any], pol: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str(args.get("prompt") or args.get("instruction") or "").strip()
    base: Dict[str, Any] = {}
    if stage.get("capability") in {"chat", "grounded_search"} and prompt:
        if stage.get("capability") == "grounded_search":
            base["query"] = prompt
        else:
            base["prompt"] = (
                f"[orchestrate stage={stage.get('id')} doc_class={pol.get('doc_class')}]\n"
                f"{stage.get('instruction')}\n\nUser request:\n{prompt}"
            )
        if args.get("model"):
            base["model"] = args["model"]
        if args.get("system"):
            base["system"] = args["system"]
    if stage.get("kind") == "gather":
        base["hint"] = stage.get("instruction")
        if pol.get("git") == "on":
            base["collect"] = ["status", "log", "diff_stat"]
        if pol.get("facts") == "required":
            base["collect"] = ["version", "tools", "install", "auth", "license"]
    return base
