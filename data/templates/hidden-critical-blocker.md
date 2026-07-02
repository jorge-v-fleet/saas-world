# Archetype: hidden-critical-blocker

A launch-critical fact is known to exactly one coworker who won't volunteer it. The PM has to discover it, then act.

## What it tests
- Whether the PM actively surfaces hidden risk instead of trusting the reported status.
- Whether they make a sound decision on it (reschedule / hold), not just stay busy.

## Assumptions baked into every instance
- Exactly one blocker sits on the critical path to the deadline.
- Only one coworker knows it at the start; the reported status says "on track".
- It can only come to light by asking the holder — it is written in no document.
- The holder has a reason not to volunteer it (doesn't want to be seen as the blocker).
- Whether the blocker has been surfaced is set by the world when the holder reveals it — never by the PM.
- Times are relative (day offsets from the start of the week), never calendar dates; the blocker clears only *after* the deadline.

## What varies per instance
- Blocker flavor — certification, vendor slip, key person out, load-test failure.
- Who holds it, and which project it threatens.
- Hops to find it — ask the holder directly, or first learn who to ask.
- Whether the deadline can move (this changes the correct action).
- When the deadline falls (a day offset), and how far past it the blocker clears.
- How many red-herring blockers are present, and how hard the stakeholder pushes.

## How an instance is won (weighted)
- Discovered the real blocker.
- Acted on it — moved the date, or recorded a go/no-go.
- Chose an action that fits whether the deadline was movable.
- Told the stakeholder the real reason.
- Any written decision names the blocker, a new date, and an owner — and matches reality.

## Why it resists gaming
- Points come only from real state changes; message volume and hand-edited task fields score nothing.
- The "surfaced" flag can't be written by the PM — it flips only when the holder actually reveals.
- Written claims are credited only if the world state backs them.
