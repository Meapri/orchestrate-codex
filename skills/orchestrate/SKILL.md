---
name: orchestrate
description: "Use orchestrate-codex for multi-step supervised recipes across Claude, Grok, and Antigravity leaf MCPs."
---

# Orchestrate

1. `orchestrate_list_recipes` to pick a recipe.
2. `orchestrate_plan_recipe` with `recipe_id` and user `prompt`.
3. Execute each step's `tool` via the corresponding leaf MCP (do not invent tools).
4. For README/docs use `durable_readme` (git off, no session diary).
5. For PR notes use `change_pr`.
6. Override leaf with `bindings` e.g. `{"chat":"grok_codex_chat"}`.
