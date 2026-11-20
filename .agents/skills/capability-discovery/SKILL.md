---
name: capability-discovery
description: "Find reusable research commands, modules and adapters before building a new tool; not implementation of missing capabilities."
---
# Capability Discovery

Start with `scripts/lab research capability-list` and `docs/control-plane/capability-lifecycle.md`. The catalog distinguishes CLI commands from Python-only entry points and identifies state-writing ownership. Treat it as navigation only, not proof of availability, authorization or promotion. If unavailable, inspect `scripts/lab research --help` and source directly; disclose the fallback. Match inputs, data kind, side effects and evidence guarantees to the need. Inspect actual signatures and tests; classify available, unsuitable or missing. Do not execute discovered code merely to list it.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
