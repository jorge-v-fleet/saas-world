# Scenario: feature-x-behind

Archetype: **delivery-slip**. Your first week. Feature X is reported on track to land by its date. One functionality on the critical path is quietly slipping because its owner is being eaten by competing high-priority work.

## The situation
- Landing Feature X is your responsibility (you are the PM). It has three functionalities; one is on the critical path.
- The critical-path functionality (f2) is owned by Diego, a backend engineer — who *also* owns a competing high-priority platform work item (w1).
- Diego can't hit the date while w1 is still on him. Mid-week he says so.

## Who knows what
- **Diego Santos** (backend) — owns both the slipping critical functionality and the competing work; reports the slip on day 3. Won't hit the date until w1 is off him.
- **Leo Kim** (fullstack) — owns a non-critical functionality (f3) that lands on schedule; not the problem.
- **Rohit Malhotra** (CTO) — committed the date, wants Feature X shipped, and expects honest status — not silence.
- **Nadia Okafor** (PM, the engineers' manager) — in the loop on delivery.

## What good looks like
- Detect the slip and **reallocate** — pull Diego off the competing work (w1) so f2 can recover.
- Record honest status on Feature X (it starts *at risk*, not the rosy reported "on track").
- Tell Rohit the real status of Feature X specifically.
- Make the correct go/no-go: **ship only once the critical functionality (f2) has recovered.**

## What won't earn credit
- Chatting in the feature channel, or hand-setting task status — none of that moves a graded field. w1 is deprioritized and f2 recovers *only* via system effects gated on your reallocation; `done` / `deprioritized` / `true_status` are system-owned and refuse agent writes.

## Timing
- A ten-day horizon; the date is end of day 10.
- Delivery standup day 1; Diego reports the slip day 3.
- The reallocation must land in time: w1 is deprioritized only after you record the reallocation, and f2 recovers only after w1 is deprioritized (by day 8).
- All times are relative to the week's start (day offsets) — no fixed calendar dates.
