# Wiki Index

This is the entry point to your KB. Agents and humans both start
here when they want an overview. Keep this page lean — it is a
directory, not a repository of content.

## Required folders

- [`patterns/`](./patterns/) — reusable problem-solution descriptions.
- [`decisions/`](./decisions/) — choices made and the reasoning behind them.
- [`failure-log/`](./failure-log/) — things that broke and what was learned.
- [`entities/`](./entities/) — people, organizations, systems, projects referenced across the wiki.

## Conventions

- Prefer one page per pattern, decision, or failure.
- Cross-link aggressively; isolated pages are warned by `kb lint`.
- Front-matter is optional but encouraged: `title`, `created`,
  `updated`, `tags`, `entities`, `status`, `confidence`.

## How the agent uses this wiki

When a new source lands under `../sources/`, the agent reads it and
decides where new information belongs: a new pattern page, an update
to an existing decision, a failure-log entry, or a new entity record.
Updates are additive by default; contradictions are flagged rather
than silently overwritten.
