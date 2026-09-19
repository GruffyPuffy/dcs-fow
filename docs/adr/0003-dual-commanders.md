# ADR 0003: Separate Red and Blue intelligence and decisions

Date: 2026-09-19  
Status: Proposed

## Context

The intended war continues without a player. Two commanders should plan from asymmetric knowledge. DCS provides [detected-target information](https://www.digitalcombatsimulator.com/en/support/faq/1268/), but what a coalition truly knows and how contact sharing works need live testing. A strict schema alone cannot prevent a model from selecting a bad but syntactically valid order.

## Proposed decision

Maintain one authoritative world model in Python and derive a separate intelligence view for each coalition before model calls. Keep prompts, strategic memory, budgets and recent orders separate. An order catalog describes permitted intent such as `hold_zone`, `move_to_zone` and `patrol_zone`; deterministic validation maps these to DCS actions. The initial cadence is about one minute, adjusted for state changes, order cooldowns and measured inference time. A failed or late model call yields no new order, leaving DCS's current task in place.

## Alternatives

- One omniscient model is easier to build but defeats the fog-of-war objective.
- Purely scripted commanders are useful as a baseline and fallback; they are the planned first test before LLM integration.

## Consequences and acceptance

Contact age, confidence, sensor provenance and unknown positions need explicit representation. Prove hidden enemies do not leak into the opposing prompt or decision trace, validate all submitted orders against side ownership and bounds, and demonstrate coherent behavior for an unattended session. Model choice and runtime remain open until measured locally.
