# Orchestrate Codex

**버전 0.2.0** · Codex용 **프로바이더 중립 오케스트레이션** 플러그인 + MCP.

Claude / Grok / Antigravity 같은 **leaf MCP는 직접 호출 가능**하게 두고,
이 플러그인은 **다단계 recipe 계획·컨텍스트 정책·검증 힌트**만 담당합니다 (감독형).

```text
Codex
  ├─ orchestrate-codex   ← recipes / policy / plan
  ├─ claude-codex        ← leaf chat
  ├─ grok-codex          ← leaf chat
  └─ google-antigravity-codex
```

## 설치

```bash
codex plugin marketplace add "/path/to/Orchestrate Codex"
# 또는 GitHub 클론 경로
codex plugin add orchestrate-codex@orchestrate-codex
```

## 사용 흐름 (v0.2)

```text
orchestrate_start_run
    → (local gather 자동)
    → next_action.call_tool  { tool, arguments }
    → Codex가 leaf MCP 호출 (claude/grok/antigravity)
    → orchestrate_continue_recipe { result_text, success }
    → … 반복 … → done
```

Leaf 실패 시 `success=false` → chat fallback: Claude → Grok → Antigravity.

## MCP 도구

| Tool | 역할 |
| --- | --- |
| `orchestrate_list_recipes` | 등록된 recipe 목록 |
| `orchestrate_explain_recipe` | stage·context policy 설명 |
| `orchestrate_plan_recipe` | 정적 플랜 (참고용) |
| `orchestrate_start_run` | 실행 시작 + local gather + next_action |
| `orchestrate_continue_recipe` | leaf 결과 반영 / fallback |
| `orchestrate_get_run` | run_id 조회 |
| `orchestrate_fallback_chains` | capability 폴백 체인 |
| `orchestrate_context_policy` | durable / change / transform / direct 정책 |

## Document classes

| class | git | session diary | 용도 |
| --- | --- | --- | --- |
| `durable` | off | off | README, product docs |
| `change` | on | allowed | PR, release notes |
| `transform` | off | off | polish, translate |
| `direct` | n/a | n/a | single-shot chat/image |

## v0.2 범위

- recipe + **stateful** start/continue
- local **gather** (fact pack / git) + **verify** heuristics
- chat **fallback** Claude → Grok → AG
- leaf HTTP는 이 MCP가 직접 호출하지 **않음** (Codex가 leaf 호출)
- 실행형 multi-MCP broker는 이후 버전

## 개발

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## 라이선스

MIT
