# Testing

## Test Suite

**140 tests**, Ruff clean, running on GitHub Actions CI.

### Categories

| Area | File | Tests |
|---|---|---|
| **Packaging guards** | `test_packaging_guards.py` | 18 |
| **Performance budget** | `test_performance_budget.py` | 14 |
| **News entry flow** | `test_wechat_news_entry_flow.py` | 8 |
| **News service** | `test_wechat_service_news_flow.py` | 6 |
| **Architecture flows** | `test_architecture_flows.py` | — |
| **WeChat decoupling** | `test_wechat_decoupling.py` | 4 |
| **Sidebar rerun** | `test_sidebar_global_rerun.py` | 12 |
| Various unit tests | (spread across test directory) | — |

### Test Characteristics

- **Self-contained**: Tests use `monkeypatch` for LLM calls, file I/O isolation
- **Source-code checks**: Many tests verify source code patterns (e.g., "no direct file open in flush path")
- **Pure function tests**: Business logic extracted as pure functions where Streamlit dependencies make direct testing infeasible
- **State machine tests**: News phase rendering, group state transitions
- **Version sync guard**: Runtime version asserted across 3 files (mode_manager, YAML, memory view)

### Key Patterns

**FakeSessionState** for testing Streamlit session state logic:

```python
class _FakeSessionState(dict):
    def __getattr__(self, k): return self[k]
    def __setattr__(self, k, v): self[k] = v
    def __delattr__(self, k): self.pop(k, None)
```

**Source-code assertions** for behavioral invariants:

```python
def test_flush_uses_safe_writer():
    block = text[block_start:block_end]
    assert "safe_write_text(current_file, existing + chunk)" in block
    assert "with current_file.open(" not in block
```

## CI Pipeline

`.github/workflows/ci.yml` runs on every push and pull request:

| Step | Action | Gate |
|---|---|---|
| Install deps | `pip install -r requirements.txt -r requirements-dev.txt` | — |
| Lint | `ruff check .` | Hard |
| Type check | `mypy --explicit-package-bases src/` | Soft (continue-on-error) |
| Test | `pytest` | Hard |
| Package check | `python tools/package_project_helper.py` | Hard |
| Secret scan | `detect-secrets` | Hard |

## Running Tests

```bash
pytest tests/                # 140 tests
pytest tests/ -v             # Verbose
pytest tests/ --cov=src      # Coverage
ruff check src/ tests/       # Linting
```
