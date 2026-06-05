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
performance_mode = deep  →  pro
performance_mode = fast  →  flash
selected_model = pro     →  pro
default                  →  flash
```

## LLM Router

`src/llm_router.py` performs LLM-based routing when `route_mode == "hybrid"` and `performance_mode != "fast"`. It calls the LLM with a JSON prompt to determine the best role, mode, and model for a user query.

Valid outputs:

- **role**: march7 (casual), keqing (project), nahida (concept), firefly (wrap-up)
- **mode**: 普通, 苏格拉底, 费曼, 项目, 论文, 概念地图
- **model**: flash, pro
- **confidence**: high, medium, low

Route caching via `st.session_state.current_route` — cleared when settings change.

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
