# Display UI Phase 0 Contract v1.1 Addendum

Status: **ACCEPTED BASELINE CORRECTION**  
Scope: Raspberry Pi 3B local 320×240 SPI display UI  
Addendum version: **1.1**  
Supersedes conflicting parts of: `docs/display-ui-phase-0-contract.md` version 1.0  
Prepared: **2026-07-14**

## 1. Purpose

The original Phase 0 contract was prepared from Release 0.02.00 while the later release branch had not yet been incorporated into the selected baseline.

The actual release branch is:

```text
release/0.03.00
```

The package version produced by that branch is `0.3.0`.

This addendum corrects the implementation baseline and records the Release 0.03.00 behavior that all Phase 1 and later work must preserve.

The original contract remains authoritative for every requirement that is not explicitly replaced by this addendum.

When this addendum conflicts with `docs/display-ui-phase-0-contract.md`, this addendum wins.

## 2. Corrected exact identity

### 2.1 Release implementation head

The exact Release 0.03.00 implementation head is:

```text
a14ef5990a972b6064cf9f8141ba5694181ea582
```

Branch:

```text
release/0.03.00
```

Release title:

```text
Release/0.03.00
```

### 2.2 Integrated repository baseline

Release 0.03.00 and the original Phase 0 contract are both integrated in:

```text
main@7fc555b302b99e874f0872c6571ddb030dd782db
```

This is the exact integrated parent baseline for the v1.1 correction branch.

Future implementation work must not start from:

```text
080813a7b3b27fe46970ad59aee234d5d9a7e5ec
```

That commit remains historical Release 0.02.00 evidence only.

Future implementation work must not start from:

```text
e45f5838c8feb5c4582b548e3edc64b91053006b
```

That commit contains the original Phase 0 document but does not contain Release 0.03.00.

Future implementation work must start from an exact descendant of:

```text
7fc555b302b99e874f0872c6571ddb030dd782db
```

that contains this addendum and no unrelated runtime changes.

## 3. Corrected baseline release statement

The following statements in the original contract are replaced:

```text
Baseline release: 0.02.00
Baseline commit: 080813a7b3b27fe46970ad59aee234d5d9a7e5ec
```

Correct values:

```text
Baseline release branch: release/0.03.00
Release implementation commit: a14ef5990a972b6064cf9f8141ba5694181ea582
Integrated main commit: 7fc555b302b99e874f0872c6571ddb030dd782db
Package version: 0.3.0
```

## 4. Release 0.03.00 capabilities contract

Release 0.03.00 adds an optional telemetry `capabilities` map keyed by metric path.

Example key forms:

```text
cpu.usage_percent
cpu.temperature_c
cpu.power_w
cpu.clock_mhz
memory.usage_percent
memory.swap_usage_percent
memory.pressure_some_percent
gpu.usage_percent
gpu.temperature_c
gpu.memory_usage_percent
gpu.power_w
storage.usage_percent
storage.read_bytes_per_second
storage.write_bytes_per_second
storage.temperature_c
network.down_bytes_per_second
network.up_bytes_per_second
health.uptime_seconds
health.undervoltage
health.throttled
device.power_w
```

Each capability entry has the semantic shape:

```json
{
  "supported": true,
  "source": "source-name",
  "reason": null
}
```

or:

```json
{
  "supported": false,
  "source": null,
  "reason": "explicit_reason"
}
```

Phase 1 must preserve this data without modification.

Phase 1 must not:

- remove the capabilities map;
- alter telemetry schema v2;
- reinterpret capability reasons;
- infer a supported capability only from a non-null value when an explicit capability entry exists;
- change Linux or Windows capability collection;
- change category availability behavior.

## 5. Corrected category availability rule

Release 0.03.00 category availability is capability-aware.

The existing `Category.available(node)` implementation is authoritative.

Required behavior:

1. If `node.capabilities` is a dictionary and contains entries matching the category prefix, the category is available when at least one matching capability has:

```text
supported == true
```

2. If capabilities are missing or contain no matching prefix, the existing value-based fallback remains authoritative for backward compatibility.

3. Phase 1 reducer code must call the existing category availability function.

4. Phase 1 reducer code must not duplicate or reimplement capability interpretation.

5. Phase 1 rendering compatibility tests must cover both:
   - legacy samples without capabilities;
   - Release 0.03.00 samples with explicit supported and unsupported capabilities.

6. A category with placeholder data but explicit unsupported capabilities remains unavailable.

7. A category with temporarily null values but an explicit supported capability remains available.

## 6. Hub registry and persistence baseline

Release 0.03.00 changes the Hub from an in-memory map of only received samples to a registered-node view backed by configuration and optional last-state persistence.

The Hub node registry is the `token_sha256` configuration mapping.

The local state endpoint returns nodes in sorted `node_id` order across the registered node set.

The Hub may return three node origins:

```text
LIVE
RESTORED_LAST_KNOWN
WAITING_FOR_FIRST_SAMPLE
```

### 6.1 Live node

A live node has a telemetry sample and a recent `received_at_utc`.

Its `online` field is calculated from the configured offline threshold.

### 6.2 Restored last-known node

The Hub may restore one last-known sample per registered node from SQLite.

A restored sample:

- retains its original telemetry payload;
- retains persisted receive time;
- is normally exposed as offline until fresh telemetry arrives;
- must remain selectable and renderable;
- must not be mistaken for a new live sample;
- must not be deleted by display-side logic.

The SQLite database is last-state persistence, not a time-series database.

The display history remains process-local in-memory history in the accepted baseline.

### 6.3 Waiting node

A registered node without any accepted or restored sample is returned with:

```text
online = false
waiting = true
```

It has a minimal placeholder shape including:

```text
node_id
display_name
cpu
memory
gpu
collector
online
waiting
```

It may not contain:

```text
timestamp_utc
received_at_utc
capabilities
storage
network
health
device
os
```

All future UI and reducer logic must tolerate those fields being absent.

## 7. Corrected status model

The original target status model is replaced with:

```text
LINK_LOST
WAITING
OFFLINE
CRITICAL
DEGRADED
ONLINE
```

Priority order:

```text
LINK_LOST > WAITING > OFFLINE > CRITICAL > DEGRADED > ONLINE
```

Definitions:

- `LINK_LOST`: the display cannot fetch current state from the local Hub.
- `WAITING`: Hub is reachable, node is registered, and `waiting` is true because no sample has ever been accepted or restored.
- `OFFLINE`: Hub is reachable, node is not waiting, and `online` is false.
- `CRITICAL`: node is online and reports active undervoltage or throttling.
- `DEGRADED`: node is online, not critical, and collector errors are non-empty.
- `ONLINE`: node is online with no critical health flag and no collector error.

Colors:

```text
LINK_LOST = AMBER
WAITING   = AMBER
OFFLINE   = RED
CRITICAL  = RED
DEGRADED  = AMBER
ONLINE    = GREEN
```

The existing Release 0.03.00 renderer currently implements:

```text
LINK_LOST
WAITING
OFFLINE
DEGRADED
ONLINE
```

The future `CRITICAL` extension remains planned for a later UI phase.

Phase 1 must preserve the current renderer output exactly and must not introduce `CRITICAL` rendering yet.

## 8. Corrected node-list requirements for later phases

The future Nodes screen must display the complete registered node list returned by the local Hub state endpoint.

It must include:

- live nodes;
- offline nodes;
- restored last-known nodes;
- waiting nodes.

The page size remains exactly three nodes.

Ordering remains stable by `node_id`.

Additional rules:

- A waiting node participates in pagination.
- A waiting node is selectable.
- Selecting a waiting node opens its Overview placeholder state; it must not crash category resolution or rendering.
- A restored offline node remains visible after Hub restart.
- When configuration reload removes a registered node, that node may disappear from the state endpoint and page clamping must occur.
- When configuration reload adds a registered node, it appears as waiting until first telemetry.
- The UI must not automatically jump to a newly registered waiting node.
- Hub link loss must retain and render the last successfully fetched list as stale.

## 9. Corrected architecture boundary

The accepted baseline architecture is:

```text
Linux agent ----\
                 +-- authenticated HTTP telemetry --> Raspberry Pi hub
Windows agent --/                                      |
                                                        +-- token registry reload
                                                        +-- one persisted last sample per node
                                                        +-- localhost state API
                                                                 |
                                                                 v
                                                        display process
                                                        + process-local history
                                                        + touch input
                                                        + ILI9341 SPI output
```

Network boundaries remain unchanged:

- public Hub listener provides telemetry ingestion and health only;
- local Hub listener provides current registered-node state only;
- local state remains bound to `127.0.0.1`;
- no remote command API exists;
- no power-control API exists;
- no monitored agent accepts inbound control requests.

The persistence database does not alter the power-control privilege boundary.

## 10. Corrected Phase 1 implementation baseline

Phase 1 remains a behavior-preserving state-management refactor.

It must preserve Release 0.03.00 behavior, not Release 0.02.00 behavior.

Phase 1 must preserve:

- capability-aware category availability;
- legacy fallback availability;
- `WAITING` renderer status;
- minimal waiting-node shapes;
- restored offline node shapes;
- current Values false affordance;
- current Graph geometry;
- current menu geometry;
- current footer labels;
- current touch thresholds;
- current inactivity behavior;
- current auto-rotation behavior;
- current local Hub API;
- current SQLite last-state persistence;
- current config reload behavior;
- current telemetry schemas;
- current systemd `StateDirectory` configuration;
- current deployment behavior.

Phase 1 must not modify:

```text
display/categories.py
display/history.py
display/gestures.py
display/drivers/*
hub/app.py
protocol/*
agents/*
deploy/*
scripts/*
README.md
pyproject.toml
```

unless a later accepted contract revision explicitly changes the Phase 1 file allowlist.

## 11. Corrected Phase 1 render-baseline rule

All pre-refactor render hashes must be generated from the exact corrected integrated baseline that contains Release 0.03.00.

Do not reuse hashes produced from:

```text
080813a7b3b27fe46970ad59aee234d5d9a7e5ec
```

or from:

```text
e45f5838c8feb5c4582b548e3edc64b91053006b
```

The deterministic baseline fixture set must include at least:

```text
Overview live legacy node
Overview waiting node
Menu legacy node without capabilities
Menu capability-aware node
Values
Graph
```

Required compatibility checks:

1. All corresponding pre/post frame hashes are identical.
2. `WAITING` remains visible and amber.
3. A supported capability keeps a category available even if its current value is null.
4. An explicitly unsupported capability hides the category even if placeholder value objects exist.
5. Legacy samples without capabilities retain value-based fallback behavior.

## 12. Corrected Phase 1 reducer data rules

The Phase 1 reducer must treat nodes as opaque telemetry/state dictionaries except when it must:

- preserve selection by `node_id`;
- call the existing category resolver;
- call the existing category availability predicate;
- call the existing metric resolver;
- navigate the node list.

It must not normalize waiting nodes into a telemetry v2 shape.

It must not inject missing fields into waiting nodes.

It must not mutate Hub-returned node dictionaries.

It must not filter waiting or offline nodes from `DataRefreshed`.

It must not sort nodes again when the Hub has already supplied stable order; selection logic must nevertheless remain correct if test input is reordered.

When the selected node is waiting and the current detail category is unavailable, existing Release 0.03.00 behavior must be preserved: return to Overview on refresh.

## 13. Corrected Phase 1 test additions

In addition to the original Phase 1 test plan, reducer and renderer tests must cover:

1. `DataRefreshed` with a waiting node only.
2. Selection preservation when a waiting node receives its first sample.
3. Selection preservation when a live node becomes restored/offline after restart.
4. Removal of a selected node after config reload.
5. Addition of a new waiting node without automatic selection.
6. Category validation using explicit supported capabilities.
7. Category validation using explicit unsupported capabilities.
8. Legacy category fallback without capabilities.
9. Waiting node missing timestamps.
10. Waiting node missing storage, network, health, device, OS, and capabilities.
11. `WAITING` status precedence over `OFFLINE`.
12. Frame-hash equivalence for Release 0.03.00 waiting and capability-aware fixtures.

No Phase 1 test may require modifying Hub persistence or telemetry code.

## 14. Corrected Phase 1 branch rule

The old proposed Phase 1 branch base is invalid:

```text
docs/display-ui-phase-0-contract@e45f5838c8feb5c4582b548e3edc64b91053006b
```

Phase 1 must instead start from the exact HEAD of:

```text
docs/display-ui-phase-0-contract-v1.1
```

The exact HEAD must be supplied in the implementation prompt and verified before edits.

The Phase 1 implementation branch name remains:

```text
refactor/display-ui-phase-1-state-reducer
```

If that implementation branch was already created from the obsolete baseline, it must not be continued or rebased silently.

The implementation must stop and report the obsolete branch identity. A new clean Phase 1 branch must be created from the corrected contract HEAD after the obsolete branch is explicitly removed or renamed by the operator.

## 15. Corrected Phase 0 acceptance

Phase 0 correction is complete when:

- Release 0.03.00 head is recorded;
- current integrated `main` is recorded;
- the original Release 0.02.00 baseline is explicitly superseded;
- capabilities-aware availability is documented;
- waiting nodes are documented;
- restored last-known samples are documented;
- the status model includes `WAITING`;
- future node pagination includes registered waiting nodes;
- Phase 1 render hashes are required from Release 0.03.00;
- the Phase 1 start branch is corrected;
- no runtime file is changed by the correction.

## 16. Decisions unchanged from contract v1.0

The following accepted decisions remain unchanged:

1. Values and Graph become separate target screens in later phases.
2. The chart metric selector is removed from Values in a later phase.
3. Graph becomes a dedicated full-screen visualization in a later phase.
4. The main menu becomes two `2 × 2` pages in a later phase.
5. Nodes uses exactly three rows per page.
6. All independent touch targets are at least `48 × 48` pixels.
7. The current palette is preserved.
8. Share Tech Mono is preserved.
9. Restart and shutdown affect only the local display Raspberry Pi.
10. Restart and shutdown require explicit hold confirmation.
11. Power control uses a root-owned local Unix socket helper in a later phase.
12. Public and local Hub APIs remain free of power-control actions.
13. Phase 1 remains a behavior-preserving state-management refactor only.

## 17. Change-control rule

Implementation may not silently reinterpret this addendum.

If this addendum conflicts with an observed exact-head behavior, implementation must stop before changing behavior and report:

```text
CONTRACT BLOCKER
- exact corrected requirement
- exact observed Release 0.03.00 behavior
- exact commit and file evidence
- smallest proposed contract amendment
- affected acceptance criteria
```

No contract correction is implicit in a code change.
