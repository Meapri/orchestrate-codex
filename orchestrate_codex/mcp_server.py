"""MCP stdio server for supervised orchestration v0.2."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from . import __version__, policy, recipes, runner

SERVER_NAME = "orchestrate-codex"
SERVER_VERSION = __version__
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


class RpcError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _empty() -> Dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "orchestrate_list_recipes",
            "description": "List built-in supervised orchestration recipes.",
            "inputSchema": _empty(),
        },
        {
            "name": "orchestrate_explain_recipe",
            "description": "Explain a recipe: stages, doc_class, context policy, default leaf bindings.",
            "inputSchema": {
                "type": "object",
                "properties": {"recipe_id": {"type": "string"}},
                "required": ["recipe_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_context_policy",
            "description": "Return context policy for a doc_class (durable|change|transform|direct).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doc_class": {
                        "type": "string",
                        "enum": sorted(policy.DOC_CLASSES.keys()),
                    }
                },
                "required": ["doc_class"],
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_plan_recipe",
            "description": "Build a static plan (steps + suggested tools). Prefer start_run for stateful execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "instruction": {"type": "string"},
                    "model": {"type": "string"},
                    "system": {"type": "string"},
                    "bindings": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["recipe_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_start_run",
            "description": (
                "Start a supervised run. Auto-executes local gather stages. "
                "Returns next_action (call_tool with leaf name+args, or done). "
                "Does not call other MCP servers — Codex must invoke the leaf tool."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "instruction": {"type": "string"},
                    "model": {"type": "string"},
                    "system": {"type": "string"},
                    "project_root": {
                        "type": "string",
                        "description": "Workspace root for gather_facts / gather_git.",
                        "default": ".",
                    },
                    "bindings": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": 'e.g. {"chat":"grok_codex_chat"}',
                    },
                    "auto_local": {"type": "boolean", "default": True},
                },
                "required": ["recipe_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_continue_recipe",
            "description": (
                "Advance a run after a leaf tool result. Pass run_id and/or full state. "
                "On leaf failure set success=false to try fallback_tools (Claude→Grok→AG)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "state": {"type": "object"},
                    "stage_id": {"type": "string"},
                    "result_text": {"type": "string"},
                    "success": {"type": "boolean", "default": True},
                    "error": {"type": "string"},
                    "auto_local": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_get_run",
            "description": "Fetch run state by run_id (same process only).",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrate_fallback_chains",
            "description": "Show default capability→fallback leaf tool chains.",
            "inputSchema": _empty(),
        },
    ]


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": True,
        "provider": "orchestrate",
        "backend": "supervised-local",
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "text": json.dumps(payload, ensure_ascii=False, indent=2)[:120000],
        **payload,
    }


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "orchestrate_list_recipes":
            return _ok({"recipes": recipes.list_recipes()})
        if name == "orchestrate_explain_recipe":
            return _ok(recipes.explain_recipe(str(arguments.get("recipe_id") or "")))
        if name == "orchestrate_context_policy":
            return _ok(policy.get_policy(str(arguments.get("doc_class") or "")))
        if name == "orchestrate_plan_recipe":
            rid = str(arguments.get("recipe_id") or "")
            bindings = arguments.get("bindings") if isinstance(arguments.get("bindings"), dict) else None
            args = {
                k: arguments.get(k)
                for k in ("prompt", "instruction", "model", "system")
                if arguments.get(k)
            }
            plan = recipes.plan_recipe(rid, args=args, bindings=bindings)
            plan["note"] = (
                "Static plan. Prefer orchestrate_start_run for stateful supervised execution (v0.2)."
            )
            return _ok(plan)
        if name == "orchestrate_start_run":
            rid = str(arguments.get("recipe_id") or "")
            bindings = arguments.get("bindings") if isinstance(arguments.get("bindings"), dict) else None
            args = {
                k: arguments.get(k)
                for k in ("prompt", "instruction", "model", "system")
                if arguments.get(k)
            }
            return _ok(
                runner.start_run(
                    rid,
                    args=args,
                    bindings=bindings,
                    project_root=str(arguments.get("project_root") or "."),
                    auto_local=bool(arguments.get("auto_local", True)),
                )
            )
        if name == "orchestrate_continue_recipe":
            return _ok(
                runner.continue_run(
                    run_id=str(arguments.get("run_id") or ""),
                    state=arguments.get("state") if isinstance(arguments.get("state"), dict) else None,
                    stage_id=str(arguments.get("stage_id") or ""),
                    result_text=str(arguments.get("result_text") or ""),
                    success=bool(arguments.get("success", True)),
                    error=str(arguments.get("error") or ""),
                    auto_local=bool(arguments.get("auto_local", True)),
                )
            )
        if name == "orchestrate_get_run":
            return _ok(runner.get_run(str(arguments.get("run_id") or "")))
        if name == "orchestrate_fallback_chains":
            return _ok({"fallback_chains": runner.FALLBACK_CHAINS, "default_bindings": recipes.DEFAULT_BINDINGS})
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "provider": "orchestrate",
            "backend": "supervised-local",
            "text": str(exc),
            "error": str(exc),
            "error_type": type(exc).__name__,
            "warnings": [],
        }


def handle_request(message: Dict[str, Any]) -> Dict[str, Any] | None:
    request_id = message.get("id")
    if request_id is None:
        return None
    method = message.get("method")
    try:
        if method == "initialize":
            params = message.get("params") or {}
            requested = str(params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION)
            selected = requested if requested in LEGACY_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
            result = {
                "protocolVersion": selected,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_definitions()}
        elif method == "tools/call":
            params = message.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise RpcError(-32602, "tool arguments must be an object")
            if name not in {t["name"] for t in tool_definitions()}:
                raise RpcError(-32602, f"unknown tool: {name}")
            result = dispatch_tool(name, arguments)
        else:
            raise RpcError(-32601, f"unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except RpcError as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("id") is None and message.get("method"):
            continue
        response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
