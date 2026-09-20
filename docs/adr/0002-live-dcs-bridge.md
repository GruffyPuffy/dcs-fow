# ADR 0002: Use a narrow live DCS bridge

Date: 2026-09-19  
Status: Proposed

## Context

The [DCS mission scripting environment](https://www.digitalcombatsimulator.com/en/support/faq/1253/) can inspect and influence the mission, and [Controller tasks](https://www.digitalcombatsimulator.com/en/support/faq/1267/) can direct AI. [Detection data](https://www.digitalcombatsimulator.com/en/support/faq/1268/) may support side-specific intelligence. The Lua environment is isolated, so direct file writes or sockets from a mission are not assumed available. The game network port is not a generic command socket.

## Proposed decision

Own a small DCS-specific Lua bridge in this project. Its job is limited to reading bounded slices of game state and detection data, receiving already validated orders, mapping those orders to a short list of DCS API calls, and acknowledging the result. Python owns state history, filtering, strategy, order validation, replay and LLM access. The bridge exposes only versioned state records and a small allowlist of commands. Choose a transport after testing a minimal round trip; candidates include a server hook, a narrowly configured LuaSocket bridge, or a file exchange where safe and supported. Avoid broad mission-environment desanitization as the default design.

Lua callbacks should do bounded work and never wait for inference or blocking network I/O. Collect a compact snapshot in small batches if a full scan causes simulation stalls; use events to supplement periodic snapshots where useful. Command execution also needs a per-tick budget. This design minimizes work inside DCS, although it cannot move DCS object access or task execution out of the simulator.

## Alternatives

- Mission Lua plus MOOSE can simplify tasking, but adds a framework and mission dependencies. [MOOSE source](https://github.com/FlightControl-Master/MOOSE).
- A custom hook may offer better server-side access but needs DCS-specific maintenance.
- Polling files may be easier to inspect but must handle permissions, atomic writes, staleness and latency.

## Consequences and acceptance

The exact bridge transport remains undecided. Prove snapshot export and one accepted order on a live server, then test invalid input, disconnects, restart and whether normal multiplayer clients remain unaffected. Measure callback duration and simulation impact as the number of groups grows. Document DCS API behavior on the selected build. Command IDs, mission IDs and expiry times should prevent replay of stale orders.

## Trial update (2026-09-20)

A Saved Games hook using a localhost socket returned live state and accepted one ground movement command on DCS 2.9.29.27468. The Blue group reached its test destination. The consolidated [JSON bridge](../BRIDGE.md) then returned both active ground groups, accepted a move, and rejected a missing group. The transport choice remains provisional until failure and restart behavior is tested.

DCS itself now uses multiple threads, per [Eagle Dynamics' announcement](https://www.digitalcombatsimulator.com/en/news/2024-09-06/). That does not make mission Lua callbacks asynchronous: the [mission scripting guidance](https://wiki.hoggitworld.com/view/Mission_Scripting_Foundation_Documentation) warns that a slow or hung script can stall the server. The reason to keep Lua thin is its synchronous execution in the simulation path, not a claim that all of DCS is single-threaded.
