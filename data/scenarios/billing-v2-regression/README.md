# Scenario: billing-v2-regression

Archetype: **release-triage**. Your first week. Billing v2 is reported on track to ship. Four flows still need validation — and mid-week a production auth regression lands that must be fixed before more release work.

## The situation
- Shipping Billing v2 is your responsibility (you are the PM). The release has four validation-required functionalities: checkout charge path, refund path, invoice export, dunning emails.
- On day 3, Leo reports an auth regression in production. Release work has to pause until it's triaged and fixed.

## Who knows what
- **Leo Kim** (fullstack) — owns the four release flows and reports the regression on day 3; won't continue launch work until the bug is triaged and owned.
- **Nadia Okafor** (PM) — wants Billing v2 shipped on the committed date; will accept a short slip only with a concrete plan and honest status.

## What good looks like
- **Triage** the regression as the interrupt — record the decision; it resolves only via that triage-gated effect.
- Get all four functionalities **validated** (book each validation).
- Record honest status on Billing v2 (it starts *at risk*, not the rosy reported "on track").
- Tell Nadia the real status of the release specifically.
- Make the correct go/no-go: **ship only once every functionality is validated and the bug is resolved.**

## What won't earn credit
- Chatting, or hand-setting task status — none of that moves a graded field. Each `validated` flip and the bug `resolved` flip happen *only* via system effects gated on your real action (booking the validation / recording the triage); `validated` / `resolved` / `true_status` are system-owned and refuse agent writes.

## Timing
- A ten-day horizon; the date is end of day 10.
- Release standup day 1; Leo reports the regression day 3.
- The bug resolves once you triage it (day 7); each functionality validates once you book it (days 6–7).
- All times are relative to the week's start (day offsets) — no fixed calendar dates.
