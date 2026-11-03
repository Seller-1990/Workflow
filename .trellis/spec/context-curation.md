# Context Curation

Governance contract for Spec and Research under `.trellis/`.
Adoption marker: **`spec-research-context-v1`** (2026-07-24).

## Spec leaf rule

A Spec leaf contains one contract that can be selected independently.

Before writing or extending a Spec, ask:

> Could a plausible task require this contract without requiring another
> contract currently in the same file?

If yes, place the contracts in separate leaf files. Independent applicability,
not line count, is the split criterion. Line count is only an audit signal that
may prompt a review for independently applicable contracts.

## Spec index rule

An `index.md` is a router. It contains only:

- scope;
- applicability questions;
- links to leaf contracts;
- required validation entry points.

It must not duplicate the body of a leaf contract, historical investigation, or
implementation narrative.

## Leaf structure

Each leaf contains:

1. Applicability: when this contract must be read;
2. Required behavior;
3. Forbidden behavior;
4. Required validation;
5. Related contracts, linked rather than copied.

## Complex Research triggers

Use the complex Research structure when any of these observable conditions
apply:

- the result is expected to guide future implementation;
- the investigation evaluates multiple hypotheses or alternatives;
- tests, measurements, source references, or rejected reasoning may need a
  later audit;
- the topic has unresolved questions that must remain visible after the current
  task.

Conciseness is an editorial goal, not a numeric threshold. Line count alone does
not determine whether Research is complex.

## Research structure

Complex Research uses:

```text
research/
|-- index.md
|-- <topic>-summary.md
`-- evidence/
    `-- <topic>-investigation.md
```

Research summary filenames must use the `<topic>-summary.md` form.

## Research index

`research/index.md` is a discovery router containing only:

- confirmed conclusions;
- rejected hypotheses;
- current decisions;
- unresolved questions;
- paths to summaries and evidence.

When a conclusion or decision changes, update the index and its corresponding
summary in the same change.

## Research summary

A `<topic>-summary.md` contains:

- the conclusion;
- the selected decision;
- implementation consequences;
- constraints that remain true;
- conditions that require reading full evidence.

Keep it concise. A Research summary is the only Research artifact eligible for
default implementation or checking context.

## Research evidence

`research/evidence/*` contains the full timeline, source references, tests,
alternatives, measurements, and discarded reasoning. Read full evidence
manually only to challenge a conclusion, resolve a conflict, or investigate an
unresolved question.

Interactive discovery may inspect Research indexes and evidence to identify the
right summary or verify a conclusion. Discovery does not make those files
eligible for task manifests.

## JSONL rule

Task `implement.jsonl` and `check.jsonl` files may reference only:

- exact Spec leaf files;
- Research files named `<topic>-summary.md`.

They must never reference `AGENTS.md`, Spec indexes, Research indexes,
compatibility routers, `research/evidence/*`, source code, or task planning
artifacts. Resolve discovery through indexes interactively, then place only the
selected leaves and summaries in the manifests.

## Adoption boundary

This contract applies prospectively from the
`spec-research-context-v1` governance adoption marker. Task artifacts created
before adoption are frozen audit records and must not be migrated to satisfy
this contract.

A compatibility router may preserve discovery for a pre-adoption path, but it
is non-authoritative. It must not duplicate leaf authority, is not eligible for
implementation or checking manifests, and does not make historical context
replay equivalent to the original pre-adoption content.

## Relation to other memory layers

| Layer | Role |
|-------|------|
| Spec / Research (this contract) | Project-level reusable contracts and research conclusions |
| planning-with-files | Per-task disk working memory (`task_plan.md` / `findings.md` / `progress.md`) |
| memory-palace | Cross-project durable facts |

Do not put planning-with-files task files into `implement.jsonl` / `check.jsonl`.
