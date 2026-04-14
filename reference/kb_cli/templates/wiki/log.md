# Wiki Activity Log

Append-only record of every meaningful change to this wiki. Written
by the agent (or by hand) whenever a source is ingested, a page is
materially revised, or a lint finding is acknowledged. Reading this
log tail-first gives a recent history without having to diff the
whole wiki.

Entry format:

```
## YYYY-MM-DDTHH:MM:SSZ — <short summary>
- source: <path or url, if applicable>
- pages_touched: [wiki/...]
- notes: <one sentence>
```

---
