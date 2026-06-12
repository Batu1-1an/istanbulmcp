# Pitfalls Research

## Pitfalls

| Pitfall | Warning Sign | Prevention | Phase |
|---------|--------------|------------|-------|
| Scope explosion | Tool list mirrors every IBB dataset | Keep v0.1 to catalog plus 5-6 high-value services | All |
| Stale data presented as live | User sees "anlik" without timestamp | Require freshness in every envelope | 1 |
| Live API-dependent tests | Tests fail when IBB is slow/down | Use fixtures for unit tests; mark integration tests | 1 |
| SOAP brittleness | XML parse or nightly downtime breaks IETT tools | Raw snapshots, parser fixtures, stale fallback | 4 |
| Unsafe generic querying | LLM-triggered broad SQL or huge results | Use guarded query builder, max limits, pagination | 2 |
| Location ambiguity | Place names map to wrong coordinates | MVP prioritizes coordinates; resolver deferred | 3 |
| Secret leakage | `.env` or Railway tokens printed/committed | Read only when needed; never print or commit secrets | All |

## Key Guardrail

If a source does not provide a field, the tool must say so. It must not infer traffic incidents, parking availability, health advice, or arrivals beyond what the source returns.
