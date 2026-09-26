# DCS FoW Campaign Doctrine

**This is the source of truth for game rules.** When a change alters any rule
described here, update this document in the same commit. `AGENTS.md` points
here instead of duplicating — keeping one authoritative copy.

Status: as of 2026-09-26. All values live in `fow/scenarios/caucasus_pve.json`
(single source of truth for numbers) — tune there, not in code.

## Economy

- Starting resources: 2000 per side.
- Income every 300 s: base stipend 40 + sum of owned objective income,
  multiplied by side factor (Blue ×1.5, Red ×0.9). The factors create the
  tipping point: Blue starts behind but overtakes as it captures territory.
- Opening endowments (credited by `new_game()`, spent during setup):
  Red 900 (pre-existing fortifications), Blue 500 (war chest so the underdog
  can push early).
- Token bucket: generals decide every 60 s; bucket capacity 300, refill
  1.5 credit/s. Urgent reactions (threatened/lost objectives, support
  replacement, counter-doctrine) may overdraw the bucket — war does not wait
  for payday.

## Capture

- **Contested capture**: an objective flips only after an attacker holds
  exclusive ground presence (owner has none inside the 3.5 km awareness
  radius) for 120 s (`capture_hold_seconds`). First sight starts the contest
  clock (`contested_since` on ObjectiveState); the owner may reinforce during
  the contest. A walk-in does not take a base.
- Players get `[FoW] <base> is CONTESTED` intel when a fight starts.

## Actions and target ownership

| Action | Cost | Legal target |
| --- | --- | --- |
| assault | 250 | `not_friendly` (enemy- or neutral-held), connected |
| reinforce | 180 | `friendly`, below defense ceiling |
| cap | 150 | `friendly` |
| cas / sead / strike | 200/225/200 | `enemy` — enemy-HELD only; never neutral ground |
| awacs / tanker | 300/250 | `friendly` |
| jtac | 50 | `not_friendly`, connected (player request) |

- Ownership semantics: `friendly` = owned by side; `not_friendly` = anything
  not owned by side (includes neutral); `enemy` = currently held by the other
  side only. Air strikes need confirmed troops/bases, not empty zones.

## Limits

- Max 40 offensive ground groups per side. Only groups named " Assault "
  count; garrisons are opening posture, not runaway spawning.
- Max 1 assault package per objective at a time (`live_assault_targets`) —
  no steamroll stacking; a second wave waits until the first resolves.
- Defense ceilings by objective difficulty: easy 1, normal 2, hard 3.
  Bases cannot be stacked into fortresses; reinforce is a patch.
- Reinforce wins at most ~50% of routine decision rounds (it is the safe
  bet; the battlefield must stay offensive).

## Doctrine (general behavior)

- **Standing rules**: a side without AWACS or tanker replaces it before
  anything else (ignores the reserve floor — blind/unfuelled is worse than
  broke). One free CAP escort per airborne AWACS (service refunds the cost).
  Tanker also gets CAP escort priority.
- **Air doctrine**: 40% of routine rounds launch an air mission; deep
  missions (strike/SEAD) preferred 70% over CAS; SEAD prefers hard
  (SAM-heavy) objectives. Offensive air (strike/SEAD/CAS) uses the same
  token floor as assaults (100) — it is a push, not a luxury.
- **Ground doctrine**: 70% of routine rounds prefer assaults when available.
- **Counter-doctrine**: active enemy assaults trigger urgent strike/CAS/CAP
  or a counter-assault on the contested objective.
- **Reserve floors**: expensive actions keep the side reserve (Blue keeps
  half of it — the underdog must push); cheap actions (≤150) need only half
  the reserve; reinforce needs 50; assault and offensive air (strike/SEAD/
  CAS) need 100.
- **Failed deployments refund** their cost — a bad spawn spot must not burn
  budget.
- **No scripted behavior**: outcomes emerge from doctrine weights + economy.
  To make a behavior likely, fund it and weight it; never hardcode sequences.

## Fog of war intel (Blue players)

- Blue sees: its own orders and takeoffs, threats at Blue-owned objectives,
  contested objectives, and Red assaults only when Blue has eyes on the
  target (target in Blue's threatened set). Never full enemy truth.
- Dedup via `_sent_intel` keys; messages via bridge `message` op to
  coalition 2.

## Callsigns

- Blue: cap=Enfield/Dodge/Chevy/Ford, cas=Hawg, sead=Weasel, strike=Anvil/
  Hammer, awacs=Wizard, tanker=Texaco/Shell.
- Red: cap=Boris/Vlad/Yuri/Dmitri, cas=Grozny, sead=Zver, strike=Orel/Sokol,
  awacs=Bark, tanker=Lanister.
- Ground groups keep descriptive names.

## Roadmap

1. **LLM generals**: swap `AlgorithmicGeneral.choose_action` for a qwen call.
   The general already receives everything an LLM needs (decision_log,
   live_support, threatened/lost/enemy_assaults, bucket, legal options with
   costs). The token bucket stays as the hard spending governor regardless of
   what the model wants. Current weighted preferences are doctrine the LLM
   will later express in natural language.
2. **Logistics missions** affecting income (transport presets exist:
   Hercules/Globemaster/C-130, IL-76/An-26) — "land and supply a base".
3. **Dynamic AWACS station fallback** per-base ownership (partially done via
   `_reposition_support`).
