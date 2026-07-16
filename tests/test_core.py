from __future__ import annotations

from orchestrate_codex import catalog, errors, gather, policy, recipes, runner, store, verify
from orchestrate_codex.mcp_server import dispatch_tool, handle_request, tool_definitions


def test_advise_returns_latest_models_and_strengths():
    out = dispatch_tool("orchestrate_advise", {})
    assert out["success"] is True
    assert out["latest_models"]["claude_codex_chat"] == "claude-opus-4-8"
    assert out["latest_models"]["grok_codex_chat"] == "grok-4.5"
    roles = {c["role"] for c in out["capabilities"]}
    assert {"reasoning-claude", "reasoning-grok", "author-gemini"} <= roles
    assert out["do_directly"]


def test_step_delegation_resolves_latest_model_and_context(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "m.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    # host delegates architecture analysis to Claude with code context
    out = dispatch_tool("orchestrate_step", {
        "capability": "chat", "instruction": "Analyze architecture",
        "doc_class": "durable", "gather": "code", "project_root": str(tmp_path),
    })
    assert out["tool"] == "claude_codex_chat"
    assert out["model"] == "claude-opus-4-8"  # latest, not the leaf's stale default
    assert out["verify_after"] is True
    assert "CODE CONTEXT" in out["arguments"]["prompt"]
    assert out["fallback_tools"][0] == "claude_codex_chat"


def test_step_write_synthesis_uses_findings_as_source(tmp_path):
    out = dispatch_tool("orchestrate_step", {
        "capability": "write", "write_task": "readme", "instruction": "Write README",
        "doc_class": "durable", "context": "FINDINGS: an MCP plugin", "project_root": str(tmp_path),
    })
    assert out["tool"] == "google_antigravity_write"
    assert out["model"] == "gemini-3.1-pro-high"
    assert out["arguments"]["task"] == "readme"
    assert "FINDINGS" in out["arguments"]["source_text"]
    assert "prompt" not in out["arguments"]  # write schema shape


def test_step_can_force_leaf_and_model():
    out = dispatch_tool("orchestrate_step", {
        "capability": "chat", "instruction": "x", "leaf": "grok_codex_chat", "model": "grok-4.5",
    })
    assert out["tool"] == "grok_codex_chat"
    assert out["arguments"]["model"] == "grok-4.5"


def test_verify_tool_flags_hallucinated_tool(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    # a real detected tool so verify knows the fact-pack tool set (else it can't flag unknowns)
    (pkg / "mcp_server.py").write_text('TOOLS = [{"name": "claude_codex_chat"}]\n', encoding="utf-8")
    out = dispatch_tool("orchestrate_verify", {
        "text": "Today we shipped. Call google_madeup_tool.",
        "doc_class": "durable", "project_root": str(tmp_path),
    })
    assert any("recency" in w for w in out["warnings"])
    assert any("google_madeup_tool" in w for w in out["warnings"])


def test_catalog_latest_for():
    assert catalog.latest_for("claude_codex_chat") == "claude-opus-4-8"
    assert catalog.latest_for("unknown") is None


def test_ok_text_is_full_json_even_when_payload_has_text(tmp_path):
    # Regression: verify's payload carries its own "text" ("verify ok"); it must NOT clobber
    # the canonical JSON serialization that the stdio content[] and handoff depend on.
    import json as _json

    resp = handle_request({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "orchestrate_verify",
                   "arguments": {"text": "clean doc", "doc_class": "durable", "project_root": str(tmp_path)}},
    })
    content_text = resp["result"]["content"][0]["text"]
    parsed = _json.loads(content_text)  # must be valid JSON, not "verify ok"
    assert "warnings" in parsed
    # gather-bearing results have the same shape hazard
    out = dispatch_tool("orchestrate_step", {"capability": "chat", "instruction": "x", "gather": "facts",
                                             "project_root": str(tmp_path)})
    _json.loads(out["text"])  # round-trips


def test_run_survives_process_restart(tmp_path):
    state = runner.start_run("direct_chat", args={"prompt": "hi"}, project_root=str(tmp_path))
    rid = state["run_id"]
    assert store.load(rid) is not None  # mirrored to disk
    runner._RUNS.clear()  # simulate MCP process restart
    restored = runner.get_run(rid)
    assert restored["run_id"] == rid
    # and it can still be continued
    done = runner.continue_run(run_id=rid, stage_id="chat", result_text="ok", success=True)
    assert done["status"] == "completed"


def test_error_classification_and_no_rotate_on_bad_request(tmp_path):
    assert errors.classify("HTTP 429 rate limit") == "rate_limit"
    assert errors.classify("401 Unauthorized") == "auth"
    assert errors.classify("unknown property 'prompt'") == "bad_request"
    state = runner.start_run("direct_chat", args={"prompt": "hi"}, project_root=str(tmp_path))
    # bad_request must NOT rotate providers (a different leaf won't fix a schema error)
    out = runner.continue_run(run_id=state["run_id"], success=False, error="400 invalid argument")
    assert out["status"] == "failed"
    assert out["steps"][0]["error_category"] == "bad_request"


def test_list_recipes():
    items = recipes.list_recipes()
    ids = {r["id"] for r in items}
    assert "durable_readme" in ids
    assert "change_pr" in ids


def test_multi_domain_recipes_registered():
    ids = {r["id"] for r in recipes.list_recipes()}
    for rid in (
        "technical_doc", "proposal", "release_notes", "translate_doc", "polish_text",
        "summarize_text", "blog_post", "email_draft", "product_copy",
        "research_brief", "review_diff", "release_draft", "generate_image", "compare_models",
    ):
        assert rid in ids, rid


def test_domain_recipes_route_to_expected_leaf(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    cases = {
        "technical_doc": ("google_antigravity_write", {"task": "technical-doc"}),
        "translate_doc": ("google_antigravity_write", {"task": "translate"}),
        "generate_image": ("google_antigravity_generate_image", {}),
        "review_diff": ("google_antigravity_review_diff", {}),
        "release_draft": ("google_antigravity_release_draft", {}),
        "compare_models": ("google_antigravity_compare_models", {}),
    }
    for rid, (tool, must_have) in cases.items():
        state = runner.start_run(rid, args={"prompt": "go"}, project_root=str(tmp_path))
        na = state["next_action"]
        assert na["tool"] == tool, rid
        for k, v in must_have.items():
            assert na["arguments"].get(k) == v, (rid, k)
        assert "prompt" not in na["arguments"] or tool.endswith(("_image", "_compare_models"))


def test_research_brief_feeds_search_into_write_source(tmp_path):
    state = runner.start_run("research_brief", args={"prompt": "q"}, project_root=str(tmp_path))
    assert state["next_action"]["tool"] == "google_grounded_search"
    state2 = runner.continue_run(
        run_id=state["run_id"], stage_id="search", result_text="S1\nS2", success=True
    )
    na = state2["next_action"]
    assert na["tool"] == "google_antigravity_write"
    assert na["arguments"]["task"] == "summarize"
    assert na["arguments"]["source_text"] == "S1\nS2"


def test_transform_fallback_folds_source_text(tmp_path):
    state = runner.start_run(
        "translate_doc",
        args={"prompt": "translate", "source_text": "Bonjour", "target_language": "Korean"},
        project_root=str(tmp_path),
    )
    assert state["next_action"]["tool"] == "google_antigravity_write"
    state2 = runner.continue_run(run_id=state["run_id"], success=False, error="quota")
    na = state2["next_action"]
    assert na["tool"] == "claude_codex_chat"
    assert "task" not in na["arguments"]
    assert "SOURCE TEXT" in na["arguments"]["prompt"]


def test_verify_reruns_and_triggers_revision(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    state = runner.start_run("durable_readme", args={"prompt": "readme"}, project_root=str(tmp_path))
    # A draft full of recency/session-diary language must bounce back to the draft stage.
    bad = runner.continue_run(
        run_id=state["run_id"], stage_id="draft",
        result_text="Today we fixed the parser in this session.", success=True,
    )
    assert bad["status"] == "running"
    assert bad["next_action"]["stage_id"] == "draft"
    assert bad["revisions"] == 1
    assert "REVISE" in str(bad["next_action"]["arguments"])
    # A clean redraft completes; the revision budget prevents an infinite loop.
    good = runner.continue_run(
        run_id=state["run_id"], stage_id="draft",
        result_text="# Project\n\nInstall with pip. Does X.", success=True,
    )
    assert good["status"] == "completed"
    assert good["revisions"] <= good["revision_budget"]


def test_revision_budget_zero_disables_loop(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    state = runner.start_run(
        "durable_readme", args={"prompt": "r", "revision_budget": 0}, project_root=str(tmp_path)
    )
    out = runner.continue_run(
        run_id=state["run_id"], stage_id="draft",
        result_text="today we changed things this session", success=True,
    )
    assert out["status"] == "completed"  # no rewind when budget is 0
    assert out["revisions"] == 0
    assert any("recency" in w for w in out.get("warnings", []))  # still surfaced as a warning


def test_verify_allows_cli_commands(tmp_path):
    # A README that references a real CLI script/console-script must NOT be flagged as a
    # hallucinated tool (regression from a live multi-LLM run on Grok Codex).
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n\n[project.scripts]\ngrok_codex_mcp = "x:serve"\n', encoding="utf-8"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "grok_codex_login.py").write_text("# login\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mcp_server.py").write_text('T = [{"name": "grok_codex_chat"}]\n', encoding="utf-8")
    facts = gather.gather_durable_facts(tmp_path)
    assert "grok_codex_login" in facts["cli_commands"]
    assert facts["install_commands"]  # pip install -e . detected
    body = "Run `python3 scripts/grok_codex_login.py` and start grok_codex_mcp. Also grok_codex_chat."
    result = verify.verify_text(body, doc_class="durable", fact_pack=facts)
    assert not any("tool_not_in_fact_pack" in w for w in result["warnings"])
    # a genuinely invented tool is still flagged
    bad = verify.verify_text("Call grok_codex_teleport now.", doc_class="durable", fact_pack=facts)
    assert any("grok_codex_teleport" in w for w in bad["warnings"])


def test_change_doc_recency_not_flagged():
    result = verify.verify_text("today we fixed the parser", doc_class="change")
    assert not any("recency" in w for w in result["warnings"])


def test_user_recipe_from_config(tmp_path, monkeypatch):
    cfg = tmp_path / "recipes.json"
    cfg.write_text(
        '{"faq_doc": {"write_task": "technical-doc", "doc_class": "durable", "description": "FAQ"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCHESTRATE_CODEX_RECIPES", str(cfg))
    ids = {r["id"] for r in recipes.list_recipes()}
    assert "faq_doc" in ids
    recipe = recipes.get_recipe("faq_doc")
    draft = next(s for s in recipe["stages"] if s["id"] == "draft")
    assert draft["write_task"] == "technical-doc"


def test_resolve_bindings_discovery():
    # Only chat leaves connected: write degrades to chat (runnable), but review/release/compare block.
    res = runner.resolve_bindings(["claude_codex_chat", "grok_codex_chat"])
    assert res["bindings"]["chat"] == "claude_codex_chat"
    assert res["bindings"]["write"] == "claude_codex_chat"  # fell back to chat
    blocked = {b["id"] for b in res["blocked_recipes"]}
    assert "review_diff" in blocked and "compare_models" in blocked
    assert "direct_chat" in res["runnable_recipes"]


def test_mcp_prompts_and_resources(tmp_path):
    init = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
    )["result"]
    assert set(init["capabilities"]) >= {"tools", "prompts", "resources"}
    prompts = handle_request({"jsonrpc": "2.0", "id": 2, "method": "prompts/list", "params": {}})["result"]
    assert any(p["name"] == "durable_readme" for p in prompts["prompts"])
    state = runner.start_run("direct_chat", args={"prompt": "hi"}, project_root=str(tmp_path))
    rl = handle_request({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})["result"]
    uri = f"orchestrate://run/{state['run_id']}"
    assert any(r["uri"] == uri for r in rl["resources"])
    rr = handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": uri}}
    )["result"]
    import json as _json
    assert _json.loads(rr["contents"][0]["text"])["run_id"] == state["run_id"]


def test_passthrough_forwards_domain_args():
    out = dispatch_tool(
        "orchestrate_start_run",
        {"recipe_id": "compare_models", "prompt": "hi", "models": ["a", "b"], "project_root": "."},
    )
    assert out["success"] is True
    assert out["next_action"]["arguments"]["models"] == ["a", "b"]


def test_durable_policy_forbids_git():
    pol = policy.get_policy("durable")
    assert pol["git"] == "off"
    assert pol["session_diary"] == "off"


def test_durable_readme_routes_to_write_leaf():
    plan = recipes.plan_recipe("durable_readme", args={"prompt": "rewrite readme"})
    draft = next(s for s in plan["steps"] if s["id"] == "draft")
    assert draft["tool"] == "google_antigravity_write"
    assert draft["suggested_arguments"]["task"] == "readme"
    # write leaf schema forbids `prompt`; we must not send it.
    assert "prompt" not in draft["suggested_arguments"]


def test_chat_binds_claude_by_default():
    plan = recipes.plan_recipe("direct_chat", args={"prompt": "hi"})
    assert plan["steps"][0]["tool"] == "claude_codex_chat"


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
    assert nxt["tool"] == "google_antigravity_write"
    args = nxt.get("arguments") or {}
    assert args.get("task") == "readme"
    assert args.get("project_root")
    assert "prompt" not in args  # write leaf shape, not chat shape


def test_write_falls_back_to_chat_and_morphs_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "2.0.0"\n', encoding="utf-8")
    state = runner.start_run(
        "durable_readme",
        args={"prompt": "Write README"},
        project_root=str(tmp_path),
    )
    assert state["next_action"]["tool"] == "google_antigravity_write"
    # Antigravity write fails -> fallback rotates to a chat leaf; args must reshape.
    state2 = runner.continue_run(run_id=state["run_id"], success=False, error="quota")
    nxt = state2["next_action"]
    assert state2["status"] == "running"
    assert nxt["tool"] == "claude_codex_chat"
    assert "task" not in nxt["arguments"]
    assert "FACT PACK" in nxt["arguments"].get("prompt", "")


def test_manual_local_stage_completes_run(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    state = runner.start_run(
        "durable_readme",
        args={"prompt": "x"},
        project_root=str(tmp_path),
        auto_local=False,
    )
    # gather (local) not auto-run; advance it manually
    runner.continue_run(run_id=state["run_id"], auto_local=False)
    # draft (write) — complete it
    runner.continue_run(
        run_id=state["run_id"], stage_id="draft", result_text="# README", success=True, auto_local=False
    )
    # verify (local) is now current; continuing must complete the run, not hang in "running"
    final = runner.continue_run(run_id=state["run_id"], auto_local=False)
    assert final["status"] == "completed"
    assert final["done"] is True


def test_missing_prompt_is_warned(tmp_path):
    state = runner.start_run("direct_chat", args={}, project_root=str(tmp_path))
    assert any("missing_prompt" in w for w in state.get("warnings", []))


def test_tools_call_wraps_mcp_content():
    resp = handle_request(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "orchestrate_list_recipes", "arguments": {}}}
    )
    res = resp["result"]
    assert res["content"][0]["type"] == "text"
    assert res["isError"] is False
    assert res["success"] is True  # flat fields retained for supervised handoff


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
