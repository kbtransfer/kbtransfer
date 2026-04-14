# tests/

Two suites:

- `adversarial/` — attack scenarios that must be rejected by the
  verifier. Named per spec convention: `T1`–`T8` (single-pack) and
  `D1`–`D6` (dependency chain). See `reports/02-v0.1.1-dogfood-report.md`
  and `reports/03-dep-chain-report.md` for the canonical test matrix.

- `integration/` — end-to-end dogfood scripts that build a real pack
  with real Ed25519 keys, publish it, subscribe from a second KB, and
  query across both. No mocks.

Run with `pytest` from the repo root. Adversarial tests are expected
to pass (each attack is caught at the declared verification step).
