# entities/

One page per significant entity referenced anywhere else in the wiki.
Entities are the nouns the rest of the wiki talks about: people,
organizations, systems, repositories, products, regulations, etc.

A good entity page has:

1. **Identity.** Canonical name, type, stable external identifiers
   (DIDs, URLs, employee IDs where appropriate).
2. **Aliases.** Every other name this entity appears under so the
   crosswalk can find it.
3. **Summary.** One paragraph on what the entity is and why it
   matters for this KB.
4. **Back-references.** Pages in `patterns/`, `decisions/`,
   `failure-log/` that mention this entity. Usually maintained
   by the agent and refreshed by `kb lint`.

Entities are load-bearing for the distiller: they are the spans
redaction policies operate on. Mislabeling an entity (treating a
person as an organization, say) can defeat redaction.
