# easy-ref

A referee for agent loops. You write a work order. easy-ref hands it to a builder agent, runs your checks itself, hands the result to a reviewer agent, and repeats until the work is approved or a decision needs you.

It drives different harnesses through small adapters: Claude Code, Codex CLI, and Pi to start.

It never pushes, opens pull requests, or merges. You get a branch that is ready for a PR, plus a record of every round.

Status: in development. See [work-orders/](work-orders/) for the build plan.
