---
name: orchestrate
description: "Multi-LLM orchestration via the orchestrate-codex MCP: you (Claude) are the conductor — advise → plan → step → leaf → verify. Use when the user asks to orchestrate models (Claude/Grok/Gemini) for docs, research, review, or any multi-model pipeline."
---

# Orchestrate (Claude Code host)

**You (Claude) are the orchestrator.** The `orchestrate-codex` MCP supplies the routing
brief, prepares each delegated leaf call (latest model + context + policy), and guards
quality — but the plan is YOUR judgment: which sub-tasks exist, which model handles
each, and what you simply do yourself.

## Host-driven flow

1. `orchestrate_advise` — routing brief: available leaves, **latest confirmed model ids**
   (leaf `list_models` catalogs are stale — trust the brief, not leaf defaults), strength
   guide, doc-class policies.
2. **You plan** the sub-tasks and assignments.
3. Per delegation: `orchestrate_step { capability, instruction, doc_class, gather?,
   context?, write_task?, model? }` → `{tool, arguments, fallback_tools, verify_after}`.
4. Invoke that leaf tool with the prepared arguments. In Claude Code the leaf MCP
   servers may not be attached to the session — execute the call via the broker's
   leaf client instead:
   `.venv/bin/python -c "from orchestrate_codex.leaf_client import ..."` or
   `orchestrate_run` (autonomous, needs `~/.orchestrate_codex/leaves.json`).
5. On failure try the next `fallback_tools` entry. If `verify_after`, run
   `orchestrate_verify { text, doc_class, project_root }` and re-delegate on warnings.
6. Synthesize results yourself; pass earlier findings forward via `context`.

## Routing guide (defaults — override with judgment)
- **Claude leaf (opus)** — depth, architecture analysis, rigorous review. (You may also
  simply do this reasoning yourself — you ARE a Claude model; delegate when you want an
  independent pass or to preserve your own context.)
- **Grok** — fast, broad, genuinely independent second opinion.
- **Gemini write leaf** — final structured authoring (readme/pr/release/translate);
  self-grounds durable facts. Takes `task/instruction/source_text`, never raw `prompt`.
- **grounded_search** — current/external facts with sources.
- **image / review_diff / compare** — image gen, git-diff review, multi-model comparison.
- **Do yourself**: planning, file edits, running commands/tests, simple transforms.

## Also available
- Recipes (proven patterns): `orchestrate_start_run` → follow `next_action` → report via
  `orchestrate_continue_recipe`. Includes `deep_readme` (multi-LLM), `durable_readme`,
  `change_pr`, `research_brief`, `review_diff`, `translate_doc`, ….
- `orchestrate_run` — autonomous broker end-to-end run (spawns leaf servers itself).
- `orchestrate_probe_models` — live-confirm latest model ids.

## Do not
- Trust leaf `list_models` for "latest" — stale. Use advise/probe.
- Put recency/session-diary tone into durable docs; verify will flag it.
