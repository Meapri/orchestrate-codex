"""Supervised run state machine: plan → (local auto) → leaf steps → continue."""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Dict, List, Optional

from . import gather, policy, recipes, verify

# capability → ordered fallback tools (first is primary unless bindings override)
FALLBACK_CHAINS: Dict[str, List[str]] = {
    "chat": ["claude_codex_chat", "grok_codex_chat", "google_antigravity_chat"],
    "grounded_search": ["google_grounded_search"],
    "image": ["google_antigravity_generate_image"],
    "write_ag": ["google_antigravity_write"],
}

_RUNS: Dict[str, Dict[str, Any]] = {}


def _bindings(overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    bind = dict(recipes.DEFAULT_BINDINGS)
    if overrides:
        bind.update({str(k): str(v) for k, v in overrides.items() if str(v).strip()})
    return bind


def _fallback_tools(capability: str, bindings: Dict[str, str]) -> List[str]:
    chain = list(FALLBACK_CHAINS.get(capability) or [])
    primary = bindings.get(capability)
    if primary:
        chain = [primary] + [t for t in chain if t != primary]
    # also honor chat_alt / chat_gemini as ordered extras for chat
    if capability == "chat":
        for key in ("chat_alt", "chat_gemini"):
            t = bindings.get(key)
            if t and t not in chain:
                chain.append(t)
    return chain


def _enrich_chat_args(
    step: Dict[str, Any],
    *,
    user_args: Dict[str, Any],
    pol: Dict[str, Any],
    artifacts: Dict[str, Any],
) -> Dict[str, Any]:
    args = dict(step.get("suggested_arguments") or {})
    prompt = str(user_args.get("prompt") or user_args.get("instruction") or "").strip()
    parts = [
        f"[orchestrate stage={step.get('id')} doc_class={pol.get('doc_class')}]",
        str(step.get("instruction") or ""),
    ]
    if artifacts.get("facts_text"):
        parts.append("FACT PACK:\n" + str(artifacts["facts_text"]))
    if artifacts.get("git_text") and pol.get("git") == "on":
        parts.append("GIT SNAPSHOT:\n" + str(artifacts["git_text"]))
    if artifacts.get("outline"):
        parts.append("OUTLINE:\n" + str(artifacts["outline"]))
    if artifacts.get("search"):
        parts.append("SEARCH RESULTS:\n" + str(artifacts["search"]))
    if prompt:
        parts.append("User request:\n" + prompt)
    if step.get("capability") == "grounded_search":
        args["query"] = prompt or args.get("query") or "status"
    else:
        args["prompt"] = "\n\n".join(p for p in parts if p)
    if user_args.get("model"):
        args["model"] = user_args["model"]
    if user_args.get("system"):
        args["system"] = user_args["system"]
    return args


def _build_steps(recipe: Dict[str, Any], bindings: Dict[str, str], user_args: Dict[str, Any], pol: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for i, stage in enumerate(recipe["stages"]):
        capability = str(stage.get("capability") or "")
        tool = stage.get("tool")
        binding = stage.get("binding")
        if tool is None and binding:
            tool = bindings.get(str(binding))
        fallbacks = _fallback_tools(capability, bindings) if capability in FALLBACK_CHAINS else []
        if tool and tool not in fallbacks and capability in FALLBACK_CHAINS:
            fallbacks = [tool] + [t for t in fallbacks if t != tool]
        step = {
            "index": i,
            "id": stage["id"],
            "kind": stage["kind"],
            "capability": capability,
            "tool": tool,
            "fallback_tools": fallbacks,
            "tool_attempt_index": 0,
            "instruction": stage.get("instruction"),
            "suggested_arguments": recipes._suggest_args(stage, user_args, pol),
            "status": "pending",
            "result_text": "",
            "error": "",
        }
        steps.append(step)
    return steps


def start_run(
    recipe_id: str,
    *,
    args: Optional[Dict[str, Any]] = None,
    bindings: Optional[Dict[str, str]] = None,
    project_root: str = ".",
    auto_local: bool = True,
) -> Dict[str, Any]:
    recipe = recipes.get_recipe(recipe_id)
    pol = policy.get_policy(recipe["doc_class"])
    bind = _bindings(bindings)
    user_args = dict(args or {})
    if project_root:
        user_args.setdefault("project_root", project_root)
    run_id = uuid.uuid4().hex[:12]
    state: Dict[str, Any] = {
        "run_id": run_id,
        "recipe_id": recipe["id"],
        "doc_class": recipe["doc_class"],
        "context_policy": pol,
        "bindings": bind,
        "fallback_chains": FALLBACK_CHAINS,
        "mode": "supervised",
        "version": "0.2.0",
        "created_at": time.time(),
        "user_args": user_args,
        "project_root": str(user_args.get("project_root") or project_root or "."),
        "steps": _build_steps(recipe, bind, user_args, pol),
        "artifacts": {},
        "cursor": 0,
        "status": "running",
        "note": (
            "Call leaf MCP tools for steps with a tool. "
            "Local gather/verify run automatically. "
            "Then orchestrate_continue_recipe with stage result."
        ),
    }
    if auto_local:
        _auto_local_forward(state)
    _RUNS[run_id] = state
    return _public_state(state)


def load_state(state_or_id: Any) -> Dict[str, Any]:
    if isinstance(state_or_id, str) and state_or_id in _RUNS:
        return _RUNS[state_or_id]
    if isinstance(state_or_id, dict) and state_or_id.get("steps"):
        return copy.deepcopy(state_or_id)
    raise ValueError("Provide run_id from start_run or a full state object")


def _public_state(state: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(state)
    out["current_step"] = _current_step(out)
    out["next_action"] = _next_action(out)
    out["done"] = out.get("status") in {"completed", "failed"}
    return out


def _current_step(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    steps = state.get("steps") or []
    cursor = int(state.get("cursor") or 0)
    if cursor < 0 or cursor >= len(steps):
        return None
    return steps[cursor]


def _next_action(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("status") == "completed":
        return {"type": "done", "message": "Recipe completed"}
    if state.get("status") == "failed":
        return {"type": "failed", "message": state.get("error") or "failed"}
    step = _current_step(state)
    if not step:
        return {"type": "done", "message": "No more steps"}
    if step.get("status") == "ready" or step.get("status") == "pending":
        # refresh chat args with artifacts
        pol = state.get("context_policy") or {}
        if step.get("capability") in {"chat", "grounded_search"}:
            step["suggested_arguments"] = _enrich_chat_args(
                step,
                user_args=state.get("user_args") or {},
                pol=pol,
                artifacts=state.get("artifacts") or {},
            )
        if step.get("tool"):
            tools = step.get("fallback_tools") or ([step["tool"]] if step.get("tool") else [])
            idx = int(step.get("tool_attempt_index") or 0)
            tool = tools[idx] if idx < len(tools) else step.get("tool")
            return {
                "type": "call_tool",
                "stage_id": step["id"],
                "tool": tool,
                "fallback_tools": tools,
                "arguments": step.get("suggested_arguments") or {},
                "instruction": step.get("instruction"),
            }
        return {
            "type": "local",
            "stage_id": step["id"],
            "kind": step.get("kind"),
            "message": "Local stage — will auto-run on continue if still pending",
        }
    return {"type": "continue", "stage_id": step.get("id")}


def _auto_local_forward(state: Dict[str, Any]) -> None:
    """Execute consecutive local gather/verify steps without leaf tools."""
    while True:
        step = _current_step(state)
        if not step or step.get("tool"):
            return
        if step.get("kind") not in {"gather", "verify"} and step.get("capability") not in {
            "local",
            "local_git",
        }:
            return
        if step.get("status") in {"completed", "failed"}:
            state["cursor"] = int(state.get("cursor") or 0) + 1
            if state["cursor"] >= len(state["steps"]):
                state["status"] = "completed"
            continue
        _run_local_step(state, step)
        if step.get("status") == "failed":
            state["status"] = "failed"
            state["error"] = step.get("error")
            return
        state["cursor"] = int(state.get("cursor") or 0) + 1
        if state["cursor"] >= len(state["steps"]):
            state["status"] = "completed"
            return


def _run_local_step(state: Dict[str, Any], step: Dict[str, Any]) -> None:
    root = str(state.get("project_root") or ".")
    try:
        if step.get("kind") == "gather" or step.get("capability") in {"local", "local_git"}:
            data = gather.run_gather(step, project_root=root, args=state.get("user_args") or {})
            step["status"] = "completed" if data.get("ok", True) else "failed"
            step["result_text"] = str(data.get("text") or "")
            if not data.get("ok", True):
                step["error"] = str(data.get("error") or "gather failed")
            artifacts = state.setdefault("artifacts", {})
            if step.get("id") == "gather_git" or step.get("capability") == "local_git":
                artifacts["git"] = data
                artifacts["git_text"] = data.get("text")
            else:
                artifacts["facts"] = data
                artifacts["facts_text"] = data.get("text")
            return
        if step.get("kind") == "verify":
            # verify previous draft/outline text
            artifacts = state.get("artifacts") or {}
            text = str(
                artifacts.get("draft")
                or artifacts.get("outline")
                or artifacts.get("last_leaf_text")
                or ""
            )
            result = verify.verify_text(
                text,
                doc_class=str(state.get("doc_class") or "durable"),
                fact_pack=artifacts.get("facts") if isinstance(artifacts.get("facts"), dict) else None,
            )
            step["status"] = "completed"
            step["result_text"] = result.get("text") or ""
            artifacts["verify"] = result
            if result.get("warnings"):
                state.setdefault("warnings", [])
                state["warnings"].extend(result["warnings"])
            return
        step["status"] = "completed"
        step["result_text"] = ""
    except Exception as exc:  # noqa: BLE001
        step["status"] = "failed"
        step["error"] = str(exc)


def continue_run(
    *,
    run_id: str = "",
    state: Optional[Dict[str, Any]] = None,
    stage_id: str = "",
    result_text: str = "",
    success: bool = True,
    error: str = "",
    auto_local: bool = True,
) -> Dict[str, Any]:
    st = load_state(state if state is not None else run_id)
    step = _current_step(st)
    if not step:
        st["status"] = "completed"
        out = _public_state(st)
        _store(st)
        return out

    sid = stage_id or str(step.get("id") or "")
    if sid and sid != step.get("id"):
        raise ValueError(f"stage_id mismatch: expected {step.get('id')}, got {sid}")

    # If current is still local pending, run it
    if not step.get("tool") and step.get("status") == "pending":
        _run_local_step(st, step)
        if step.get("status") == "failed":
            st["status"] = "failed"
            st["error"] = step.get("error")
            out = _public_state(st)
            _store(st)
            return out
        st["cursor"] = int(st.get("cursor") or 0) + 1
        if auto_local:
            _auto_local_forward(st)
        out = _public_state(st)
        _store(st)
        return out

    if success:
        step["status"] = "completed"
        step["result_text"] = result_text or ""
        artifacts = st.setdefault("artifacts", {})
        artifacts["last_leaf_text"] = result_text or ""
        # stash by stage id
        if step.get("id") == "outline":
            artifacts["outline"] = result_text
        elif step.get("id") in {"draft", "synthesize", "chat"}:
            artifacts["draft"] = result_text
        elif step.get("id") == "search":
            artifacts["search"] = result_text
        st["cursor"] = int(st.get("cursor") or 0) + 1
        if st["cursor"] >= len(st["steps"]):
            st["status"] = "completed"
        elif auto_local:
            _auto_local_forward(st)
            if st.get("cursor", 0) >= len(st["steps"]) and st.get("status") == "running":
                st["status"] = "completed"
    else:
        # try fallback tool
        tools = step.get("fallback_tools") or []
        idx = int(step.get("tool_attempt_index") or 0) + 1
        if idx < len(tools):
            step["tool_attempt_index"] = idx
            step["status"] = "pending"
            step["error"] = error or result_text or "leaf failed; trying fallback"
            step["tool"] = tools[idx]
        else:
            step["status"] = "failed"
            step["error"] = error or result_text or "leaf failed"
            st["status"] = "failed"
            st["error"] = step["error"]

    out = _public_state(st)
    _store(st)
    return out


def _store(state: Dict[str, Any]) -> None:
    rid = str(state.get("run_id") or "")
    if rid:
        _RUNS[rid] = state


def get_run(run_id: str) -> Dict[str, Any]:
    if run_id not in _RUNS:
        raise ValueError(f"unknown run_id: {run_id}")
    return _public_state(_RUNS[run_id])
