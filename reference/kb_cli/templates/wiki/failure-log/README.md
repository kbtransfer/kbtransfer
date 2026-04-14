# failure-log/

Things that broke and what was learned. **Experience — first-class
in this KB.**

Every page here captures one failure. The goal is to make the
failure teachable: a future reader should be able to recognize the
same situation before it bites them.

A good failure entry has:

1. **What broke.** One sentence; concrete symptoms, not abstractions.
2. **When.** Date or window; relevant environmental context.
3. **Trigger.** The change, load, or input that exposed the fault.
4. **Root cause.** Why the system was vulnerable to this trigger.
5. **Fix.** What was changed to resolve the immediate incident.
6. **Prevention.** What was changed to prevent recurrence (or why nothing could be).
7. **Related.** Links to affected patterns, decisions, and entities.

Failures distill into the `pages/failure-modes.md` section of an
AutoEvolve pack. They are often the most-cited part of a published
pack, because they describe hazards that consumers could not have
discovered without running into them.
