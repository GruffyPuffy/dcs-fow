# ADR 0004: Keep mission generation separate from live command

Date: 2026-09-19  
Status: Proposed

## Context

[pydcs](https://github.com/pydcs/dcs) is a Python framework for creating and editing DCS mission files. Its published example saves a `.miz` archive. It does not claim to issue live controller tasks to a running mission.

## Proposed decision

Use a small hand-built mission for the first live bridge test. Evaluate pydcs for reproducible scenario generation after the bridge and command model work. Treat mission generation, live runtime control and campaign persistence as distinct components.

## Alternatives

- Mission Editor only is sufficient for a tiny prototype but may become difficult to reproduce as scenarios grow.
- pydcs from day one could automate setup, but would add a second unknown during the first bridge experiment.

## Consequences and acceptance

pydcs is optional for the first milestone. If adopted, confirm generated missions load under the chosen DCS build and round-trip scenario essentials. Review dependency and content licenses before distributing generated assets or bundled frameworks.
