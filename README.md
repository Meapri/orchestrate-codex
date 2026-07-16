# Orchestrate Codex

**버전 0.5.0** · Codex용 **프로바이더 중립 오케스트레이션** 플러그인 + MCP.

> v0.5: **호스트(GPT)가 지휘자.** `orchestrate_advise`로 라우팅 브리핑(최신 모델·강점)을 받아
> GPT가 배분을 판단하고, `orchestrate_step`으로 위임(최신모델·컨텍스트·정책 자동 주입),
> `orchestrate_verify`로 가드. 레시피/자율 브로커는 그대로 옵션.

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

Durable/change 문서 초안은 **Antigravity `write` leaf**(task=readme / pr-description)로 라우팅되어
프로젝트 전체를 스스로 그라운딩합니다. leaf 실패 시 `success=false` → chat fallback으로 저하되며
인자 모양이 `write` → `chat`(prompt+fact pack)로 자동 변환됩니다.

## 도메인 (recipe)

README 외에도 여러 도메인을 오케스트레이션합니다. 태스크별 recipe는 `_WRITE_RECIPES` 테이블
한 줄로 추가됩니다.

- **문서(durable)**: `durable_readme`, `technical_doc`, `proposal`
- **변경(change)**: `change_pr`, `release_notes`, `review_diff`, `release_draft`
- **변환(transform)**: `translate_doc`, `polish_text`, `rewrite_text`, `summarize_text`, `research_brief`
- **단발(direct)**: `announcement`, `blog_post`, `email_draft`, `product_copy`, `generate_image`, `compare_models`, `direct_chat`

`orchestrate_start_run`에 넘긴 여분 인자(`source_text`, `target_language`, `models`, `version`,
`aspect_ratio` 등)는 leaf 툴로 그대로 전달됩니다. 전체 목록은 `orchestrate_list_recipes` 참고.

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
| `orchestrate_resolve_bindings` | 연결된 leaf 툴 기준 capability/recipe 실행가능성 판정 |
| `orchestrate_advise` | **라우팅 브리핑**: 최신 모델 id·강점 가이드·정책·recipe (GPT가 판단) |
| `orchestrate_step` | **위임 준비**: leaf+최신모델 해석, 컨텍스트/정책 주입한 호출 반환 |
| `orchestrate_verify` | 가드레일: 산출물 환각/최근어투/툴명 검증 |
| `orchestrate_probe_models` | leaf별 최신 모델 id 실측 확인(핑) |
| `orchestrate_run` | **자율 실행(opt-in)**: 브로커가 leaf를 직접 띄워 recipe를 끝까지 실행 |
| `orchestrate_check_leaves` | 자율 브로커 프리플라이트: 설정된 leaf 스폰·tools 확인 |

또한 recipe는 MCP **prompts**로, run 상태는 MCP **resources**(`orchestrate://run/<id>`)로 노출됩니다.

## 자율 브로커 (v0.4, opt-in)

기본은 감독형(Codex가 leaf 호출)입니다. `orchestrate_run`은 **브로커가 leaf MCP 서버를
서브프로세스로 직접 띄워** recipe를 끝까지 실행하고 최종 산출물만 반환합니다. 감독형과 같은
상태머신·폴백·verify 재생성 루프를 그대로 사용합니다.

- leaf 실행 커맨드는 `~/.orchestrate_codex/leaves.json`(또는 env `ORCHESTRATE_CODEX_LEAVES`)에서 읽습니다.
- **각 leaf는 자기 consent/auth를 스스로 강제** — 브로커가 우회 불가. 미동의 leaf는 leaf가 거부하고, 브로커는 에러 분류·폴백으로 처리합니다.

```json
{
  "claude_codex_chat": {
    "command": "python3", "args": ["./scripts/claude_codex_mcp.py"],
    "cwd": "/abs/path/Claude Codex"
  },
  "grok_codex_chat": {
    "command": "python3", "args": ["./scripts/grok_codex_mcp.py"],
    "cwd": "/abs/path/Grok Codex"
  },
  "google_antigravity": {
    "command": "python3", "args": ["./scripts/google_antigravity_mcp.py"],
    "cwd": "/abs/path/Antigravity Codex"
  }
}
```

키는 정확한 tool 이름 또는 프로바이더 프리픽스(`google_antigravity` → `google_antigravity_*` 전체)입니다.
먼저 `orchestrate_check_leaves`로 스폰 가능한지 확인하세요.

## Document classes

| class | git | session diary | 용도 |
| --- | --- | --- | --- |
| `durable` | off | off | README, product docs |
| `change` | on | allowed | PR, release notes |
| `transform` | off | off | polish, translate |
| `direct` | n/a | n/a | single-shot chat/image |

## v0.4 범위

- 다도메인 recipe(20+) + **stateful** start/continue
- durable/change 초안을 **write leaf**로 라우팅(task 구조화) + chat 폴백
- **verify → 자동 재생성 제어 루프**(budget 제한): 경고 감지 시 draft로 되돌려 교정
- **영속성**: run이 파일에 저장되어 MCP 프로세스 재시작 후에도 resume
- **에러 분류** 기반 폴백(auth/rate_limit/timeout/transient; bad_request는 회전 안 함)
- **설정 기반 recipe**(`ORCHESTRATE_CODEX_RECIPES` JSON) + **capability 자동 발견**
- MCP **prompts/resources** 노출, `content[]` 준수
- **자율 브로커**(`orchestrate_run`, opt-in): leaf MCP를 직접 스폰해 recipe 끝까지 실행
- 감독형(`orchestrate_start_run`)은 여전히 기본 — leaf HTTP를 직접 호출하지 않음

### 설정 파일 예 (`~/.orchestrate_codex/recipes.json`)

```json
{
  "faq_doc": { "write_task": "technical-doc", "doc_class": "durable", "description": "Project FAQ" }
}
```

환경변수: `ORCHESTRATE_CODEX_RECIPES`(recipe JSON 경로), `ORCHESTRATE_CODEX_STATE_DIR`(run 저장 위치).

## 개발

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## 라이선스

MIT
