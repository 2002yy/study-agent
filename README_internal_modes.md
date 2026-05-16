# Runtime mode reference

> This file describes the runtime mode fields that are currently used by the codebase.
> Since the v0.7.4 release, `config/runtime_state.yaml` is the machine source of truth.

## 1. Runtime fields

| field | meaning | values |
|------|---------|--------|
| `relationship_mode` | interaction atmosphere | `standard / warm / close` |
| `wechat_mode` | wechat thread state | `unread_feedback / first_user_join / interactive_group` |
| `memory_mode` | memory write permission | `readonly / preview / confirm_write / locked` |
| `route_mode` | routing mode | `auto_rule / hybrid` |
| `debug_mode` | debug surface on/off | `true / false` |
| `safe_mode` | memory write safety gate | `true / false` |
| `performance_mode` | runtime performance level | `fast / standard / deep` |
| `entry_mode` | main app entry surface | `wechat / single` |

## 2. State files

| file | role |
|------|------|
| `config/runtime_state.yaml` | machine-readable source of truth |
| `memory/internal_state.md` | mirrored human-readable runtime/version view |
| `memory/interaction_settings.md` | mirrored human-readable interaction view |
| `chat/wechat_state.md` | mirrored human-readable wechat state view |

## 3. Behavior notes

1. `safe_mode=true` blocks long-term memory writes
2. `preview` is not a formal write-enabled memory mode
3. `fast` mode disables the LLM router path
4. runtime state updates should go through `src/mode_manager.py`
5. markdown state files should be treated as mirrors, not as the primary store

