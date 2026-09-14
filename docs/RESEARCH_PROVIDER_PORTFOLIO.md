# Research Provider Portfolio 2.0

> Status: **POST-RQ1-C DESIGN / NOT ACTIVE IN CURRENT QUALIFICATION**  
> Owner boundary: this document owns the **provider-portfolio architecture and post-RQ1-C expansion plan**. It does **not** own current project status, qualification thresholds, or execution authorization; those remain in `docs/PROJECT_STATUS.md`.

## 1. Purpose

RQCE must not depend on one web-search provider, nor should it treat several providers behind the same network/failure domain as true redundancy.

The target architecture is a **claim-driven, evidence-grounded, budget-aware research planner** whose discovery layer can choose among multiple provider classes while preserving the existing truth pipeline:

```text
Claim / Evidence Gap
        ↓
Gap Planner
        ↓
Provider Portfolio Scheduler
        ↓
Candidate Pool
        ↓
Candidate Assessment
   ┌───────────────┐
   ↓               ↓
Lead            Evidence Candidate
   ↓               ↓
Discovery         Read
   ↓               ↓
Better Candidate  Extract
                   ↓
                 Evidence
                   ↓
                  Gate
                   ↓
                 Answer
```

The portfolio exists to improve **candidate discovery and recall**. It must never replace Evidence qualification, Evidence Gate, or claim-support binding.

## 2. Why the current three-provider shape is insufficient

The current bounded-research discovery path has primarily used:

- Bing RSS;
- SearXNG;
- DuckDuckGo HTML.

This gives nominal provider diversity, but not necessarily independent failure domains.

A self-hosted SearXNG instance still calls external search engines from the deployment/network egress. DDG HTML is also an unauthenticated web-scraping style integration. Under a degraded or reputation-limited egress, SearXNG engines and DDG can fail together through challenge, timeout, 403/429, or other anti-automation behavior.

Therefore:

```text
three provider names
≠
three independent failure domains
```

Bing RSS has been comparatively stable in current RQ1-C diagnostics, but relying on it as the only consistently available general-web source creates a discovery-quality ceiling.

The architecture must instead support a **portfolio** with different provider capabilities, latency/cost classes, and failure domains.

## 3. Design principles

### 3.1 Search Result ≠ Evidence

Every provider returns discovery candidates only.

No provider result may bypass:

```text
Candidate Assessment
→ eligibility
→ bounded scheduling
→ Read
→ Extract
→ Evidence Gate
```

A provider marked "semantic", "AI", "research", or "official" receives no Evidence privilege.

### 3.2 Provider Failure ≠ Research Failure

A degraded provider should reduce recall, not consume the entire research budget or crash the run.

The existing timeout/deadline invariants remain mandatory:

- provider aggregate wall-clock budget;
- research-window deadline;
- retry budget checks;
- run-scoped degraded/circuit state;
- explicit skip/failure audit reasons.

### 3.3 Failure-domain diversity matters more than provider count

The scheduler should prefer providers that add an independent discovery path rather than mechanically calling every enabled backend.

### 3.4 Lead ≠ Weak Evidence

The existing Lead architecture remains unchanged.

Provider expansion should improve the supply of useful candidates and leads, but `lead_only` remains a discovery asset and never becomes support merely because it came from a stronger provider.

### 3.5 Specialized sources should beat generic web search when the domain is known

If the claim clearly belongs to a structured or authoritative ecosystem, use an appropriate specialized resolver instead of forcing every query through general web search.

Examples:

- repository/code claim → GitHub resolver/search;
- package/version claim → package registry resolver;
- academic claim → academic metadata/search resolver;
- known government/standards owner → authoritative domain resolver.

## 4. Target provider layers

### 4.1 Layer A — General Web Search

Purpose: broad web recall, fresh pages, official pages, documentation, announcements, policies, product information.

Planned portfolio:

| Provider | Role | Portfolio status |
|---|---|---|
| Bing RSS | low-cost general lexical discovery | existing |
| Brave Search API | independent authenticated general-web index | **first expansion target** |
| SearXNG | configurable metasearch / recall expansion | existing, opportunistic |
| DuckDuckGo HTML | fallback lexical discovery | existing, opportunistic |

The key expansion is not "one more search engine"; it is adding a **separate authenticated general-web failure domain** so that Bing degradation does not immediately collapse discovery quality.

### 4.2 Layer B — Semantic / Agent-oriented Search

Purpose: queries where lexical search repeatedly returns dictionary/aggregator noise or where the target is easier to describe semantically than with exact keywords.

Candidates:

| Provider | Intended role | Priority |
|---|---|---|
| Exa | semantic discovery, domain-constrained discovery, deep-page finding | **second expansion target** |
| Tavily | agent-oriented search / optional extraction-crawl capabilities | later candidate |

These providers are discovery accelerators only. Their own answer/research products must not replace RQCE's Claim → Evidence → Gate pipeline.

### 4.3 Layer C — Specialized Resolvers

Purpose: route high-confidence domain-specific claims to the system that owns the relevant corpus.

Potential examples:

```text
GitHub                 → repositories / release / code claims
PyPI                   → Python package metadata
crates.io              → Rust package metadata
academic resolvers     → papers / DOI / publication metadata
government resolvers   → official statistics / policy publications
standards resolvers    → standards bodies / specifications
```

This layer should grow from concrete benchmark needs, not from a goal of integrating every available service.

## 5. Provider capability model

Do not model providers as a flat string list forever.

The scheduler should eventually operate on explicit capability metadata similar to:

```text
SearchProviderCapabilities
- provider_id
- provider_family
- failure_domain
- authenticated_api
- lexical_search
- semantic_search
- domain_filter
- freshness_filter
- content_fetch
- latency_class
- cost_class
```

The exact implementation shape is intentionally not frozen here. The stable requirement is that scheduling can reason about **capabilities, cost, and failure independence**, not merely provider names.

## 6. Scheduling model

Provider Portfolio 2.0 must not reintroduce the old anti-pattern:

```text
for every query:
    call every enabled provider
```

Instead, provider selection should be staged and intent-aware.

### 6.1 Example policy

```text
ordinary general-web gap
→ Bing + Brave

sufficient candidate quality / recall reached
→ stop provider expansion

mostly aggregator / off-target results
→ semantic provider escalation (e.g. Exa)

known trusted primary domain
→ domain-targeted provider query

clear specialized domain
→ specialized resolver

extra recall still required and budget available
→ SearXNG / opportunistic fallback
```

This policy must remain bounded by the shared research window, read/model-call budgets, provider aggregate deadlines, and finalization reserve.

### 6.2 Scheduler objectives

For each provider action, the scheduler should consider:

```text
expected discovery value
+ failure-domain diversity
+ source-quality potential
- latency cost
- monetary/API cost
- remaining research budget risk
```

No adaptive scoring system is required for the first implementation. A deterministic policy with auditable reasons is preferred first.

## 7. Relationship to existing Lead paths

Provider Portfolio 2.0 feeds the existing research graph; it does not replace it.

### Candidate Lead path

```text
provider result
→ Candidate
→ lead_only
→ bounded Lead Read
→ DiscoveryAsset
→ Better Candidate
```

### Evidence-stage Lead path

```text
read Evidence Candidate
→ extraction relation="lead"
→ Evidence Lead Follow-up
→ deeper URL / trusted-domain hint / follow-up query
→ Better Candidate
```

A richer provider portfolio gives these loops better raw material, but all current Lead caps, depth guards, provenance, and Evidence eligibility remain intact.

## 8. Why this is not part of the current RQ1-C qualification run

RQ1-C is currently closing a frozen qualification contract. Activating new providers now would change multiple independent variables at once:

- candidate distribution;
- source-role distribution;
- provider latency;
- failure behavior;
- primary-source hit rate;
- search-phase cost;
- Lead activation frequency.

That would invalidate clean attribution against the current A→B→A calibration and frozen Live12 baseline.

Therefore:

> **Provider Portfolio 2.0 is a post-RQ1-C expansion. New adapters may be developed behind disabled configuration and fake/integration tests, but they must not enter the current frozen qualification configuration before RQ1-C closure.**

## 9. Delivery order

### Phase 1 — Brave Search API

Goal: add a second stable, authenticated, general-web discovery failure domain.

Acceptance should compare at least:

```text
Bing only
Brave only
Bing + Brave
```

using existing frozen/holdout cases and measuring:

- off_target rate;
- topic_only rate;
- answer_relevant rate;
- primary / authoritative source hit rate;
- eligible Evidence yield;
- support-cluster yield;
- provider latency and failure rate;
- incremental research cost.

The adapter must remain disabled in the current RQ1-C qualification preset until the qualification is closed.

### Phase 2 — Exa semantic discovery

Goal: add semantic/deep-page discovery where lexical providers repeatedly return weak aggregators or fail to find deeper official pages.

Important evaluation question:

> Does semantic escalation increase primary/deeper-page yield enough to justify its latency/cost under bounded research?

### Phase 3 — Specialized resolvers

Add resolvers only where benchmark evidence shows that domain-aware routing materially improves reliability or cost.

### Phase 4 — Optional Tavily / additional providers

Evaluate only after the first two provider classes are measured. Additional provider count is not itself a success criterion.

## 10. Benchmark and attribution requirements

Provider additions must use the measurement discipline established during RQ1-C hardening:

- environment fingerprint;
- exact SHA / clean tree;
- fixed case sets;
- raw provider latency/status telemetry;
- paired or otherwise attribution-safe comparison when performance claims are made;
- qualification evidence kept separate from diagnostics.

A provider should not be accepted merely because one live run improved the final answer.

## 11. Non-goals

Provider Portfolio 2.0 does **not** authorize:

- relaxing Evidence Gate;
- treating provider snippets as Evidence by default;
- allowing `rejected` candidates to become Lead automatically;
- bypassing Candidate Assessment for semantic/API providers;
- replacing RQCE with a third-party "research answer" endpoint;
- increasing the frozen RQ1-C 60s / read / model-call budgets to accommodate new providers;
- calling all providers for every query;
- activating new providers in current qualification before RQ1-C closure.

## 12. Stable architectural summary

The intended long-term discovery model is:

```text
                 RQCE Gap Planner
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     General Web   Semantic Web   Specialized
          │            │            │
     Bing RSS          Exa         GitHub
     Brave API         Tavily      Package registries
     SearXNG                       Academic resolvers
     DDG HTML                      Official-domain resolvers
          │            │            │
          └────────────┴────────────┘
                       ↓
                 Candidate Pool
                       ↓
                    Assessor
                       ↓
                Lead / Evidence
                       ↓
                      Gate
                       ↓
                     Answer
```

The desired degradation behavior is:

```text
one provider is poor
→ use independent portfolio recall
→ improve query / choose semantic or specialized discovery
→ follow Leads toward primary Evidence
→ if Evidence remains insufficient, Gate fails closed
```

The central invariant remains:

> **Providers improve discovery; only the RQCE evidence pipeline establishes truth.**
