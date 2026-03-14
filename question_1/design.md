# Design Notes

## Threat model

LLM output is treated as adversarial input. The validator whitelists known fields,
constructs a new dict from scratch, and never passes the original payload through.
This is the same posture you'd apply to user-facing API input.

## Key trade-offs

**Clamp `k` vs reject** — Clamping with a warning. An out-of-range `k` from an LLM
is almost always a formatting artifact, not a semantic error. Rejecting forces a
retry that costs latency and tokens for no real safety benefit. If strict mode is
needed later, a `strict=True` flag is a one-line addition.

**Case-fold `action`** — LLMs frequently emit `"Search"` or `"SEARCH"`. Normalising
to lowercase avoids pointless retries. Recorded as a warning for observability.

**Reject booleans for `k`** — `isinstance(True, int)` is `True` in Python. Silently
accepting `True → 1` hides bugs. Explicit rejection is safer.

**Lossless float coercion only** — `3.0 → 3` is safe. `3.7 → 3` is lossy truncation
that could change behaviour. We reject lossy and fall back to the default.

**Errors list, not logging** — The function is pure: it returns `(clean, errors)`.
The caller decides whether to log, emit metrics, or retry. Embedding logging
inside the validator would couple it to infrastructure.

**Errors list carries both fatal errors and warnings** — The spec returns a single
`List[str]`. In practice, messages like "unknown keys ignored" and "coerced string
to int" are warnings, not errors — the call still succeeds. In production I'd
separate these into `errors` and `warnings`, or attach a severity level to each.

## What I'd change at scale

- At 10+ fields, move to Pydantic with custom pre-validators instead of hand-rolled logic.
- Track unknown-key frequency as a metric — high rates signal prompt drift.
- Fuzz the validator with property-based tests (Hypothesis) in CI.
- Add input size limits (max string length for `q`) to guard against hallucinated payloads.