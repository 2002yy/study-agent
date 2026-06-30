# Model Routing

## Multi-Provider LLM Client

`src/llm_client.py` provides a unified interface across 5 LLM providers:

| Provider | Env Prefix | Default Base URL |
|---|---|---|
| DeepSeek | `DEEPSEEK_*` | `https://api.deepseek.com/v1` |
| OpenAI | `OPENAI_*` | — |
| OpenRouter | `OPENROUTER_*` | `https://openrouter.ai/api/v1` |
| SiliconFlow | `SILICONFLOW_*` | `https://api.siliconflow.cn/v1` |
| Local | `LOCAL_*` | `http://127.0.0.1:8000/v1` |

Selection via `LLM_PROVIDER_PROFILE` env var. Client instances are cached by config signature and automatically rebuilt when settings change.

## Model Profiles

Two model tiers:

- **flash**: Fast, low-cost model for daily chat and group replies
- **pro**: Higher-quality model for summaries, routing, and complex reasoning

Resolution logic (`src/wechat_generator.py:_resolve_model_profile`):

```
selected_model = pro     →  pro
selected_model = flash   →  flash
performance_mode = deep  →  pro
performance_mode = fast  →  flash
default                  →  flash
```

## LLM Router

`src/llm_router.py` performs LLM-based routing when `route_mode == "hybrid"` and `performance_mode != "fast"`. It calls the LLM with a JSON prompt to determine the best role, mode, and model for a user query.

Valid outputs:

- **role**: march7 (casual), keqing (project), nahida (concept), firefly (wrap-up)
- **mode**: 普通, 苏格拉底, 费曼, 项目
- **model**: flash, pro
- **confidence**: high, medium, low

`论文` and `概念地图` are task intents now, not learning modes. Paper-like requests route to `项目` with Keqing; concept-structure requests route to Nahida with an active learning mode chosen from the list above.

“为什么、本质、机制、原理” express desired content depth and route to a
normal, deep explanation. Automatic routing selects `苏格拉底` only for an
explicit learning-behavior intent such as “别直接告诉我，引导我思考”. A manual
Socratic selection always activates the protocol.

## Stateful pedagogy routing

`ChatService` turns the visible mode into a protocol-specific
`PedagogyTurnPlan`. For Socratic rediscovery, each turn selects one cognitive
move and an evidence disclosure level. External facts (dates, measured values,
API/version names, paper results) are supplied explicitly by the library;
derivable answers can be withheld while examples, counterexamples, or bounded
hints are disclosed.

The current phase is stored in `chat_threads.learning_state`; the plan,
before/after state, and evidence policy are stored in
`chat_turns.pedagogy_snapshot`. Session restoration therefore resumes the same
discovery phase instead of relying on trimmed chat history.

## Performance Budget

Main chat, WeChat, and news LLM paths are bounded by `src/performance_budget.py`:

| Call Point | Fast | Standard | Deep |
|---|---|---|---|
| Single chat | 700 | 1100 | 1600 |
| Group reply | 520 | 760 | 1050 |
| Opening | 420 | 620 | 850 |
| News digest | 650 | 950 | 1300 |
| News discussion | 520 | 760 | 1000 |
| History lines | 16 | 28 | 40 |

Auxiliary calls such as memory-candidate extraction may still rely on `llm_client.py` task defaults or environment/global defaults. Treat full coverage of every LLM call as a remaining hardening item, not a completed invariant.
