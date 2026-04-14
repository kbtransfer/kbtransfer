# examples/

Reference templates and end-to-end sample scenarios.

Planned contents (populated incrementally across phases):

- `kb-template/` — what `kb init` produces on a fresh machine:
  default `.kb/schema.yaml`, empty `wiki/` skeleton with `patterns/`,
  `decisions/`, `failure-log/`, `entities/`, a seed `log.md`, and
  starter policy files for each tier.

- `sample-packs/` — small but real signed packs used by the test
  suite and by the "getting started" walkthrough.

- `sample-registry/` — a minimal git-registry repo layout that
  mirrors the GitHub template used by `kb_registry`.

Nothing in `examples/` is load-bearing for production; these are
teaching artifacts.
