# 02: Workflows

Build a document pipeline using `chain`, `group`, and `chord`.

## Deliverables

- Sequential validation and transformation tasks using `chain` and explicit signature discipline (`.s()` vs `.si()`).
- Parallel processing (fan-out) with aggregation (fan-in) using `group` and `chord`.
- A defined policy for partial failure and callback failure (e.g., `link_error` errbacks and result envelopes to avoid hung chords).
- A dedicated result backend (e.g., Redis) configured for chord synchronization with sensible `result_expires` TTL.
- Tests proving task ordering, fan-out, fan-in, and error behavior.
- JSON-safe task boundaries with no live database or request objects.

## Evidence

Include a workflow diagram and timing comparison between sequential and parallel execution.
