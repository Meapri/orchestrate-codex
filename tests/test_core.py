from __future__ import annotations

from orchestrate_codex import gather, policy, recipes, runner, verify
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
    assert "orchestrate_start_run" in names
    assert "orchestrate_continue_recipe" in names
    listed = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert listed["result"]["tools"]
    out = dispatch_tool("orchestrate_list_recipes", {})
    assert out["success"] is True


def test_gather_durable_facts(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "demo").mkdir()
    facts = gather.gather_durable_facts(tmp_path)
    assert facts["ok"] is True
    assert facts["version"] == "1.2.3"
    assert "demo" in facts["skills"]
    assert "DURABLE FACT PACK" in facts["text"]


def test_verify_flags_recency():
    result = verify.verify_text("today we fixed HTTP 400 in this session", doc_class="durable")
    assert result["warning_count"] >= 1
    assert any("recency" in w for w in result["warnings"])


def test_start_run_auto_gather_and_next_leaf(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "9.9.9"\n', encoding="utf-8")
    state = runner.start_run(
        "durable_readme",
        args={"prompt": "Write a short README"},
        project_root=str(tmp_path),
    )
    assert state["run_id"]
    # gather auto-completed
    gather_step = state["steps"][0]
    assert gather_step["status"] == "completed"
    assert "9.9.9" in (state.get("artifacts") or {}).get("facts_text", "")
    nxt = state["next_action"]
    assert nxt["type"] == "call_tool"
    assert nxt["tool"] == "claude_codex_chat"
    assert "FACT PACK" in (nxt.get("arguments") or {}).get("prompt", "")


def test_continue_with_fallback_on_failure(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    state = runner.start_run(
        "direct_chat",
        args={"prompt": "hi"},
        project_root=str(tmp_path),
    )
    assert state["next_action"]["tool"] == "claude_codex_chat"
    state2 = runner.continue_run(
        run_id=state["run_id"],
        success=False,
        error="capacity",
    )
    # still same step, fallback tool
    assert state2["status"] == "running"
    assert state2["next_action"]["tool"] == "grok_codex_chat"


def test_continue_success_completes_direct(tmp_path):
    state = runner.start_run("direct_chat", args={"prompt": "hi"}, project_root=str(tmp_path))
    state2 = runner.continue_run(
        run_id=state["run_id"],
        stage_id="chat",
        result_text="hello world",
        success=True,
    )
    assert state2["done"] is True
    assert state2["status"] == "completed"
