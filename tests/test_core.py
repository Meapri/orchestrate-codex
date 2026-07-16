from __future__ import annotations

from orchestrate_codex import policy, recipes
from orchestrate_codex.mcp_server import dispatch_tool, handle_request, tool_definitions


def test_list_recipes():
    items = recipes.list_recipes()
    ids = {r["id"] for r in items}
    assert "durable_readme" in ids
    assert "change_pr" in ids


def test_durable_policy_forbids_git():
    pol = policy.get_policy("durable")
    assert pol["git"] == "off"
    assert pol["session_diary"] == "off"


def test_plan_binds_claude_by_default():
    plan = recipes.plan_recipe("durable_readme", args={"prompt": "rewrite readme"})
    chat_steps = [s for s in plan["steps"] if s.get("tool")]
    assert any(s["tool"] == "claude_codex_chat" for s in chat_steps)


def test_plan_binding_override():
    plan = recipes.plan_recipe(
        "direct_chat",
        args={"prompt": "hi"},
        bindings={"chat": "grok_codex_chat"},
    )
    assert plan["steps"][0]["tool"] == "grok_codex_chat"


def test_mcp_tools():
    names = {t["name"] for t in tool_definitions()}
    assert "orchestrate_plan_recipe" in names
    listed = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert listed["result"]["tools"]
    out = dispatch_tool("orchestrate_list_recipes", {})
    assert out["success"] is True
