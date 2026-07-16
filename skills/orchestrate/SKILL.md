---
name: orchestrate
description: "Supervised multi-step recipes across Claude, Grok, and Antigravity leaf MCPs (start_run → leaf → continue)."
---

# Orchestrate (v0.2)

## Flow

1. `orchestrate_start_run` with `recipe_id`, `prompt`, optional `project_root`, `bindings`.
2. Read `next_action`:
   - `call_tool` → invoke that **leaf** MCP tool with `arguments` (do not invent tools).
   - `done` → finished.
3. After leaf returns: `orchestrate_continue_recipe` with `run_id`, `stage_id`, `result_text`, `success`.
4. On leaf failure: `success=false` — orchestrator rotates `fallback_tools` (chat: Claude→Grok→AG).
5. Pass full `state` back if the MCP process may restart.

## Recipes

| id | class | notes |
| --- | --- | --- |
| `durable_readme` | durable | auto fact pack; no git diary |
| `change_pr` | change | auto git snapshot |
| `research_then_write` | transform | AG grounded search then chat |
| `direct_chat` | direct | single leaf chat |

## Bindings

Default chat = `claude_codex_chat`. Override: `{"chat":"grok_codex_chat"}`.

## Do not

- Put session diary into durable README prompts.
- Call leaf HTTP yourself inside orchestrate — only plan/state.
