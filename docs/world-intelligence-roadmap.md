# Entity World Intelligence Roadmap

This is the canonical implementation plan for Entity's global intelligence
system. It is deliberately separate from Entity's identity as a personal
agent.

## Product boundary

- **Entity Core** owns wake word, conversation, memory, calendar, alarms,
  notifications, room control, planning, and personal autonomy.
- **World Intelligence** owns public-source collection, evidence evaluation,
  event understanding, hypotheses, forecasts, and calibration.
- **Jarvis Mode** will be an optional operations interface over World
  Intelligence. Requests to take action must still pass through Entity Core's
  planner, permissions, confirmations, and durable task systems.

Jarvis Mode must never replace the primary assistant, bypass action controls,
or turn raw intelligence signals directly into physical actions.

## Fifteen-step implementation plan

1. [x] Add the universal world-event graph.
2. [x] Add the licensed source registry and connector contracts.
3. [x] Integrate conflict, humanitarian, and emergency feeds.
4. [ ] Add global weather and infrastructure layers.
5. [ ] Add maritime activity intelligence.
6. [ ] Fuse observations into evolving world events.
7. [ ] Learn bounded regional activity baselines.
8. [ ] Generate evidence-linked world change signals.
9. [ ] Add the autonomous predictive world engine.
10. [ ] Calibrate forecasts by domain, region, and horizon.
11. [ ] Add the separate Jarvis timeline and intelligence-map interface.
12. [ ] Add Jarvis viewport briefings and watchlists.
13. [ ] Deliver selected intelligence alerts through Entity Core.
14. [ ] Add historical replay, bias, and false-alert evaluations.
15. [ ] Enforce source licensing, security, and workload limits end to end.

## Non-negotiable epistemic rules

- Observation, report, inference, hypothesis, and forecast remain distinct.
- Repetition and syndication do not create independent corroboration.
- Proximity and temporal order do not establish causation.
- Movement tracks never imply hostile or criminal intent by themselves.
- Corrections, deletions, source versions, and evidence cutoffs are retained.
- Every conclusion and relationship carries provenance, method, and confidence.
- Missing coverage is represented as unknown, not as evidence of absence.
- Model calls are bounded and occur only after deterministic prioritization.

## Delivery rule

Each numbered step is delivered as a reviewable commit with migrations,
bounded backfills, tests, operational configuration, and rollback-safe database
handling where applicable. This checklist is updated only when its acceptance
tests pass.
