# Incomplete run: do not report its partial success rate

DeepSeek returned concurrency-limit errors (429) and insufficient balance (402).
The native runner flagged 40 infrastructure failures; diagnostics reveal four
additional provider failures caught as review errors in this version.
14 episodes completed; the remaining two stopped with no_candidates and
recommendation_error. Its partial-denominator macro score is not a full-run result.

Preserve these raw outputs for diagnosis. See
`outputs/recommended_workflow_20261127.md` for valid prior runs and limitations.
Final code propagates SDK provider errors so they retain infrastructure classification.
