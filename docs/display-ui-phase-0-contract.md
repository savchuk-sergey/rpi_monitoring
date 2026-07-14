# Display UI Phase 0 Contract

Status: **ACCEPTED BASELINE CONTRACT**  
Scope: Raspberry Pi 3B local 320×240 SPI display UI  
Contract version: **1.0**  
Baseline release: **0.02.00**  
Baseline commit: **080813a7b3b27fe46970ad59aee234d5d9a7e5ec**  
Prepared: **2026-07-14**

## 1. Purpose

This document freezes the implementation baseline and the non-negotiable UX, navigation, geometry, visual, and privilege-boundary decisions for the next display UI iterations.

It is the authority for Phase 1 and later UI phases. When code, tests, comments, or earlier plans conflict with this document, this document wins unless it is explicitly superseded by a later accepted contract revision.

Phase 0 changes documentation only. It must not change runtime behavior, telemetry behavior, deployment behavior, systemd behavior, rendering output, touch interpretation, or API surface.

## 2. Exact implementation baseline

All future work covered by this contract must start from the exact Git commit:

```text
080813a7b3b27fe46970ad59aee234d5d9a7e5ec
```

This commit is the accepted Release 0.02.00 implementation baseline. It contains telemetry v2, category navigation, short and long touch recognition, Values and Graph detail modes, and in-memory five-minute history.

The repository default branch must not be treated as the implementation baseline unless it resolves to the exact commit above or a documented descendant of it.

### 2.1 Baseline authority files

The following files define the current UI implementation and must be inspected before any implementation work:

```text
display/app.py
display/navigation.py
display/gestures.py
display/categories.py
display/history.py
display/renderer.py
display/drivers/ili9341.py
display/drivers/xpt2046.py
tests/test_display.py
deploy/raspberry-pi/install.sh
deploy/systemd/homelab-resource-monitor-display.service
hub/app.py
protocol/telemetry-v2.schema.json
```

### 2.2 Baseline runtime architecture

```text
Linux agent ----\
                 +-- authenticated HTTP telemetry --> Raspberry Pi hub
Windows agent --/                                      |
                                                        +-- localhost state API
                                                                |
                                                                v
                                                        display process
                                                        + touch input
                                                        + ILI9341 SPI output
```

Current network boundaries:

- Public Hub listener: telemetry ingestion and health only.
- Local Hub listener: current state only, bound to `127.0.0.1`.
- Display process: local consumer of current state.
- No remote command API exists.
- No remote power-control API exists.
- No monitored agent accepts inbound control requests.

These boundaries are preserved by this contract.

## 3. Confirmed baseline findings

### 3.1 Current screen model

Release 0.02.00 currently models UI state with:

```text
ViewMode.OVERVIEW
ViewMode.MENU
ViewMode.DETAIL
```

`ViewMode.DETAIL` contains a second state dimension:

```text
DetailView.VALUES
DetailView.GRAPH
```

### 3.2 Current category model

The current category registry contains exactly six categories:

```text
CPU
MEMORY
GRAPHICS
STORAGE
NETWORK
HEALTH
```

The current menu geometry is a fixed `3 × 2` grid. The hit-test calculation assumes exactly six menu entries.

### 3.3 Confirmed Values defect

The top metric selector is rendered in both Values and Graph detail views. Selecting a metric changes `UiState.metric_by_category`.

That selection affects Graph rendering only. Values rendering continues to show the same category-wide rows regardless of the selected metric.

Therefore, the metric selector is functionally irrelevant in Values and creates a false affordance.

The accepted correction is:

- Values must not render the chart-metric selector.
- Values must not expose a touch target that only affects Graph.
- Graph metric selection must be owned by the Graph screen.
- Values rows and chart metrics must become separate domain concepts in a later phase.

### 3.4 Confirmed Graph limitation

The current plot region is approximately:

```text
x = 28..310
y = 82..160
```

The graph itself is only 78 pixels high because the detail header, metric selector, Values/Graph tabs, summary values, and footer share the same screen.

The accepted correction is to make Graph a dedicated screen whose plot consumes the primary content area.

### 3.5 Confirmed multi-GPU limitation

`selected_gpu_index` exists, but Release 0.02.00 has no complete current interaction that advances it in the new navigation model.

History collection also resolves GPU metrics with index `0`, which means history is not correctly partitioned for multiple GPUs.

This is not part of Phase 1 implementation, but Phase 1 state design must not make the later correction harder.

### 3.6 Confirmed privilege boundary

The display service is intentionally unprivileged and hardened. It runs as `homelab-monitor-display` with `NoNewPrivileges=true` and a strict systemd sandbox.

The Hub service is also unprivileged and hardened.

The accepted power-control design must not:

- run the display service as root;
- run the Hub service as root;
- remove `NoNewPrivileges=true`;
- grant unrestricted sudo access to the display user;
- add a network power-control endpoint to the public Hub API;
- execute a shell command constructed from UI text;
- permit control of arbitrary monitored nodes.

## 4. Fixed hardware and display constraints

The target display is fixed for this work:

```text
Controller: ILI9341
Touch: XPT2046 resistive touch
Orientation: landscape
Logical size: 320 × 240 pixels
Color transport: RGB565 over SPI
```

The UI must be designed for imprecise resistive touch, low pixel density, limited SPI throughput, and operation without a keyboard or mouse.

The implementation must not assume multitouch, hover, wheel input, right click, pinch, swipe, or reliable drag gestures.

## 5. Preserved visual identity

The current visual identity is mandatory and must not be replaced.

### 5.1 Color palette

```text
BACKGROUND = #000400
GREEN      = #43ff6b
BRIGHT     = #c4ffcf
MUTED      = #438d50
RED        = #ff5c5c
AMBER      = #ffb84d
```

No new general-purpose theme color may be introduced without a contract revision.

Semantic use:

- `BACKGROUND`: screen background and inverse text on pressed controls.
- `GREEN`: normal active controls, healthy status, primary terminal-style accent.
- `BRIGHT`: selected item, current value, high-emphasis text.
- `MUTED`: secondary text, disabled control, grid line, unavailable optional data.
- `AMBER`: warning, degraded state, restart action.
- `RED`: critical state, offline state, shutdown action.

Color must never be the only status signal. A status word, symbol, or value must accompany warning, critical, degraded, and offline states.

### 5.2 Font

The primary and required UI font is:

```text
display/assets/ShareTechMono-Regular.ttf
```

The typeface must remain Share Tech Mono. Font fallback may remain for fault tolerance, but accepted screenshots and hardware validation must use the bundled font.

### 5.3 Text sizes

Normative size classes:

```text
TINY      = 11 px; non-interactive, optional supporting text only
SMALL     = 13 px; secondary labels and compact metadata
DETAIL    = 15 px; standard value rows and normal controls
LABEL     = 18 px; primary controls and large labels
TITLE     = 22 px; overview title or empty-state title
VALUE     = 38 px; overview primary values
```

Interactive text must not rely on the 11-pixel class.

## 6. Touch interaction contract

### 6.1 Minimum target size

Every independent actionable target must have a hitbox with:

```text
minimum width  = 48 px
minimum height = 48 px
```

Preferred target height is 53–80 pixels where layout permits it.

A visual label and its hitbox must represent the same action. Invisible full-height side navigation zones are forbidden.

### 6.2 Spacing

Independent neighboring actions must have at least 4 pixels of separation, or a clear non-action boundary that prevents one coordinate from mapping to two actions.

Hitboxes for different actions must never overlap.

### 6.3 Allowed gestures

Allowed:

- short press;
- deliberate long press;
- continuous hold for destructive confirmation.

Forbidden unless introduced by a later contract:

- swipe navigation;
- drag navigation;
- double tap;
- edge gesture;
- multi-finger gesture;
- hidden gesture without visible instruction.

### 6.4 Feedback

A valid press must produce visible feedback before the action completes.

A press that moves outside the configured movement tolerance must cancel the pending action.

A long press must emit at most one long-press action per physical press/release cycle.

### 6.5 Destructive action confirmation

Restart and shutdown must not execute from one short press.

The confirmation screen must provide:

- an explicit target name;
- a description of the consequence;
- a large Cancel action;
- a distinct hold-to-confirm action;
- visible hold progress;
- cancellation when released early;
- cancellation when movement leaves the target;
- automatic timeout back to the previous safe screen.

## 7. Accepted target screen inventory

The final target UI uses a single explicit screen enum with the following values:

```text
OVERVIEW
MAIN_MENU
VALUES
GRAPH
NODES
SYSTEM
POWER_CONFIRM
POWER_PENDING
POWER_ERROR
```

No separate `DetailView` dimension is part of the target state model. Values and Graph are independent screens.

Phase 1 must introduce the target enum and reducer foundation while preserving Release 0.02.00 user-visible behavior. Later phases will activate the new screens.

## 8. Accepted target navigation map

```text
OVERVIEW
  short center                -> VALUES
  long center                 -> MAIN_MENU
  previous                    -> previous node
  next                        -> next node

MAIN_MENU
  category tile               -> VALUES for that category
  NODES tile                  -> NODES
  SYSTEM tile                 -> SYSTEM
  center/back                 -> OVERVIEW
  previous/next               -> menu page navigation
  inactivity timeout          -> OVERVIEW

VALUES
  open graph                  -> GRAPH
  center/overview             -> OVERVIEW
  long center                 -> MAIN_MENU
  GPU selector, when present  -> next GPU
  inactivity timeout          -> OVERVIEW

GRAPH
  previous metric             -> previous available chart metric
  next metric                 -> next available chart metric
  center/values               -> VALUES
  long center                 -> MAIN_MENU
  inactivity timeout          -> OVERVIEW

NODES
  node row                    -> OVERVIEW with selected node
  previous                    -> previous node-list page
  next                        -> next node-list page
  center/back                 -> MAIN_MENU
  inactivity timeout          -> OVERVIEW

SYSTEM
  restart                     -> POWER_CONFIRM(REBOOT)
  shutdown                    -> POWER_CONFIRM(POWEROFF)
  back                        -> MAIN_MENU
  inactivity timeout          -> OVERVIEW

POWER_CONFIRM
  cancel                      -> SYSTEM
  completed hold              -> POWER_PENDING
  early release               -> remain on POWER_CONFIRM
  movement outside target     -> reset hold progress
  inactivity timeout          -> SYSTEM

POWER_PENDING
  accepted                    -> wait for local process termination
  failed                      -> POWER_ERROR

POWER_ERROR
  back                        -> SYSTEM
```

## 9. Pixel geometry contract

All coordinates use half-open rectangles:

```text
(left, top, right, bottom)
left <= x < right
top <= y < bottom
```

The full display is:

```text
(0, 0, 320, 240)
```

### 9.1 Standard shell

The standard non-graph screen shell is:

```text
Header:  y = 0..31
Content: y = 32..191
Footer:  y = 192..239
```

Constants:

```text
SCREEN_WIDTH  = 320
SCREEN_HEIGHT = 240
HEADER_TOP    = 0
HEADER_BOTTOM = 32
CONTENT_TOP   = 32
CONTENT_BOTTOM= 192
FOOTER_TOP    = 192
FOOTER_BOTTOM = 240
```

### 9.2 Standard footer

The standard three-part footer uses:

```text
LEFT:   (0,   192, 64,  240)
CENTER: (64,  192, 256, 240)
RIGHT:  (256, 192, 320, 240)
```

No dead strips are required between these three footer targets. Boundary coordinates must map deterministically to exactly one target.

### 9.3 Main menu layout

The accepted menu uses two pages and a `2 × 2` grid.

Tile rectangles:

```text
TOP_LEFT:     (0,   32, 160, 112)
TOP_RIGHT:    (160, 32, 320, 112)
BOTTOM_LEFT:  (0,  112, 160, 192)
BOTTOM_RIGHT: (160,112, 320, 192)
```

Page 1 order:

```text
CPU       | MEMORY
GRAPHICS  | NODES
```

Page 2 order:

```text
STORAGE   | NETWORK
HEALTH    | SYSTEM
```

Menu footer labels:

```text
LEFT:   <
CENTER: BACK <page>/<page_count>
RIGHT:  >
```

Unavailable metric categories remain visible in their fixed positions and render as `MUTED` with `NO DATA`.

### 9.4 Values layout

Values must not contain a chart metric selector or Values/Graph tabs.

Standard Values layout:

```text
Header: category and node identity, y = 0..31
Rows:   y = 32..143 or y = 32..175 depending on row count
Graph action area: at least 48 px high when graph metrics exist
Footer: y = 192..239
```

The Open Graph action must occupy a visible rectangle at least 48 pixels high. Exact vertical placement may be chosen in the implementation phase as long as no row or footer overlaps and all geometry tests pass.

Health may have no Open Graph action when no chartable metric exists.

### 9.5 Full-screen Graph layout

Graph is a dedicated screen.

Normative regions:

```text
Compact overlay header: y = 0..27
Primary plot region:    x = 20..312, y = 28..184
Summary overlay:        y = 164..191, where required
Footer:                 y = 192..239
```

The plot must remain the dominant area. The graph screen must not render:

- the Values row list;
- Values/Graph tabs;
- the category-wide chart metric tab strip;
- the standard large Overview header.

Graph footer semantics:

```text
LEFT:   previous available metric
CENTER: VALUES
RIGHT:  next available metric
```

The left and right labels should include the neighboring metric title when it fits.

### 9.6 Nodes layout

The accepted page size is exactly three node rows.

```text
Header:    (0, 0, 320, 32)
Row 1:     (0, 32, 320, 85)
Row 2:     (0, 85, 320, 138)
Row 3:     (0, 138, 320, 192)
Footer:    (0, 192, 320, 240)
```

Each complete row is one touch target.

Each row contains:

- status indicator and status text or abbreviation;
- fitted display name;
- data age;
- CPU usage;
- RAM usage;
- CPU temperature, otherwise GPU usage, otherwise storage usage, otherwise `N/A`.

Node order is stable by `node_id` unless a future contract defines another stable key.

Selecting a row sets `selected_node_id` and returns to Overview.

### 9.7 System layout

The System screen target is always the local display Raspberry Pi, never the currently selected monitored node.

The target name must be visible.

Accepted action semantics:

```text
Restart action: amber
Shutdown action: red
Back action: safe navigation action
```

Restart and Shutdown must each have a target height of at least 64 pixels.

### 9.8 Power confirmation layout

The confirmation screen must include two independent targets:

```text
CANCEL
HOLD TO CONFIRM
```

Both targets must be at least 48 pixels high. The hold target should be wider than Cancel.

The hold progress bar must be inside the hold target or immediately adjacent to it and visually associated with the action.

## 10. Status model

The target common status classifier is:

```text
LINK_LOST
OFFLINE
CRITICAL
DEGRADED
ONLINE
```

Priority order:

```text
LINK_LOST > OFFLINE > CRITICAL > DEGRADED > ONLINE
```

Definitions:

- `LINK_LOST`: display cannot fetch current state from the local Hub.
- `OFFLINE`: Hub is reachable and node `online` is false.
- `CRITICAL`: node is online and reports active undervoltage or throttling.
- `DEGRADED`: node is online, not critical, and collector errors are non-empty.
- `ONLINE`: node is online with no critical health flag and no collector error.

Colors:

```text
LINK_LOST = AMBER
OFFLINE   = RED
CRITICAL  = RED
DEGRADED  = AMBER
ONLINE    = GREEN
```

Status classification must eventually move out of screen-specific rendering code into a reusable view-model function.

## 11. Node pagination rules

Page size is fixed at three.

Given `node_count`:

```text
page_count = max(1, ceil(node_count / 3))
```

The current page index is zero-based internally and one-based in the UI.

Rules:

- Clamp `nodes_page` after every node-list refresh.
- Do not automatically change page when a node status changes.
- Do not automatically jump to a newly added node.
- Preserve selected node by `node_id`, not by list index.
- If the selected node disappears, select the first remaining node.
- If no nodes remain, set `selected_node_id` to `None`.
- When the Hub link is lost, keep and render the last known node list as stale; do not replace it with an empty list solely because the request failed.

## 12. History and graph decisions

The renderer must eventually use `HistoryStore.window_seconds`; a hard-coded five-minute renderer window is not allowed in the target design.

GPU history must be partitioned by stable GPU identity, not only by category and metric.

Target history key shape:

```text
<node_id>/<category_id>/<resource_id>/<metric_id>
```

For non-multi-resource categories, `resource_id` may be a fixed sentinel such as `default`.

Missing and offline samples remain `None` gaps. They must not be converted to zero and must not be bridged by a continuous graph line.

Graph scale modes reserved by the contract:

```text
FIXED
DYNAMIC_ZERO_BASED
DYNAMIC_RANGE
```

Exact scale implementation is not Phase 1 scope.

## 13. Power-control security contract

Power controls affect only the local Raspberry Pi that hosts the physical display.

They must not affect:

- the selected monitored node;
- a remote Windows agent;
- a remote Linux agent;
- the Homelab Control Plane;
- any host addressed by user-provided text.

### 13.1 Required local configuration

The later power phase must use explicit local configuration equivalent to:

```json
{
  "local_node_id": "display-rpi",
  "power_actions_enabled": true,
  "power_socket": "/run/homelab-resource-monitor/power.sock",
  "power_confirm_hold_seconds": 1.5
}
```

The actual local node ID remains deployment configuration and must not be hard-coded in renderer logic.

### 13.2 Required privilege separation

The accepted architecture is a root-owned systemd-activated Unix domain socket helper.

Required properties:

- no TCP listener;
- no public Hub route;
- no local Hub power route;
- socket path under `/run/homelab-resource-monitor`;
- access restricted to root and the display service group;
- helper receives one fixed action per connection;
- accepted actions are exactly `reboot` and `poweroff`;
- any other payload is rejected;
- request size is bounded;
- read time is bounded;
- peer credentials are checked;
- commands use fixed argv without a shell;
- action and result are logged to journald;
- the display renders the pending frame before sending the request.

Required command shape:

```text
/usr/bin/systemctl --no-block reboot
/usr/bin/systemctl --no-block poweroff
```

No part of the command is constructed from UI labels or external telemetry.

### 13.3 Required service hardening preservation

The display service must remain unprivileged.

The Hub service must remain unprivileged.

Existing hardening must not be weakened to implement power control.

## 14. Phase 1 implementation boundary

Phase 1 is a structural state-management refactor only.

Phase 1 must:

- introduce a single explicit `Screen` enum;
- replace the `ViewMode` plus `DetailView` state combination;
- introduce typed UI events;
- introduce a pure UI reducer;
- introduce an effect description type without executing new effects;
- route existing Release 0.02.00 behavior through the reducer;
- preserve existing visual output and existing user-visible interaction behavior;
- preserve current API, telemetry, history, rendering, deployment, and privilege behavior;
- add exhaustive reducer tests.

Phase 1 must not:

- redesign Values;
- enlarge Graph;
- add Nodes UI;
- add System UI;
- add reboot or shutdown behavior;
- add a power helper;
- change menu geometry;
- change footer labels;
- change touch thresholds;
- change timeouts;
- change colors;
- change fonts;
- change telemetry schemas;
- change agent collectors;
- change Hub routes;
- change systemd units;
- change installer configuration;
- change screenshots or hardware behavior intentionally.

## 15. Phase 1 compatibility mapping

To preserve Release 0.02.00 behavior during the structural refactor, Phase 1 uses this temporary mapping:

```text
Old ViewMode.OVERVIEW                         -> Screen.OVERVIEW
Old ViewMode.MENU                             -> Screen.MAIN_MENU
Old ViewMode.DETAIL + DetailView.VALUES       -> Screen.VALUES
Old ViewMode.DETAIL + DetailView.GRAPH        -> Screen.GRAPH
```

The following target enum members must exist but remain unreachable in normal Phase 1 interaction:

```text
Screen.NODES
Screen.SYSTEM
Screen.POWER_CONFIRM
Screen.POWER_PENDING
Screen.POWER_ERROR
```

No placeholder screen may be rendered to the user in Phase 1.

## 16. Phase 1 reducer contract

The reducer must be pure:

```python
def reduce_ui(state: UiState, event: UiEvent, context: UiContext) -> UiTransition:
    ...
```

A pure reducer:

- does not read the clock directly;
- does not read touch hardware;
- does not call the Hub;
- does not render images;
- does not write logs;
- does not mutate the input event;
- does not execute system commands;
- does not perform network or filesystem I/O.

All data needed for a transition must be supplied through `event` and `context`.

The reducer may mutate the provided `UiState` only if that is explicitly chosen and consistently tested. The preferred design is to return a new or copied state so tests can compare before and after values without aliasing. The implementation must choose one model and use it consistently.

### 16.1 Required event types

Phase 1 must define typed events equivalent to:

```text
ShortPress(x, y, now)
LongPress(x, y, now)
DataRefreshed(nodes, hub_online, now)
InactivityTick(now, touch_pressed)
AutoRotateTick(now)
```

Names may differ only when the mapping remains one-to-one and explicit.

Raw press-progress events are not required in Phase 1 because the existing `TouchRecognizer` remains authoritative for short and long gesture recognition.

### 16.2 Required context

`UiContext` must contain all transition dependencies that are currently read from outer variables, including:

```text
nodes
current_index
auto_rotate_seconds
pause_until
last_rotation
detail_timeout_seconds
menu_timeout_seconds
```

The implementation may split mutable runtime navigation data between `UiState` and context, but the owner of each field must be explicit and covered by tests.

### 16.3 Required transition result

`UiTransition` must provide at least:

```text
state
full_refresh
completed_action
```

It may additionally return:

```text
selected_index
pause_until
last_rotation
effect
```

No new runtime side effect may be executed in Phase 1.

## 17. Phase 0 acceptance criteria

Phase 0 is complete only when:

- the exact Release 0.02.00 baseline commit is recorded;
- current screen behavior is documented;
- the Values false-affordance defect is documented;
- the Graph space limitation is documented;
- target screens are enumerated;
- target navigation is specified;
- pixel geometry is specified;
- the palette is fixed;
- the font is fixed;
- touch target requirements are fixed;
- node pagination rules are fixed;
- power-control scope is fixed to the local Raspberry Pi;
- the privilege-separation contract is fixed;
- Phase 1 scope and exclusions are explicit;
- no runtime source file is changed by Phase 0.

## 18. Decision record

Accepted decisions:

1. Release 0.02.00 commit `080813a7b3b27fe46970ad59aee234d5d9a7e5ec` is the implementation baseline.
2. Values and Graph are separate target screens.
3. The chart metric selector is removed from Values in a later phase.
4. Graph becomes a dedicated full-screen visualization in a later phase.
5. The main menu becomes two `2 × 2` pages in a later phase.
6. Nodes uses exactly three rows per page.
7. Node order is stable by `node_id`.
8. All independent touch targets are at least `48 × 48` pixels.
9. The current palette and Share Tech Mono font are preserved.
10. Restart and shutdown affect only the local display Raspberry Pi.
11. Restart and shutdown require explicit hold confirmation.
12. Power control uses a root-owned local Unix socket helper in a later phase.
13. Public and local Hub APIs remain free of power-control actions.
14. Phase 1 is a behavior-preserving state-management refactor only.

## 19. Change-control rule

Implementation may not silently reinterpret this contract.

If a requirement proves technically impossible on the accepted hardware or conflicts with an already accepted invariant, implementation must stop before changing behavior and report:

```text
CONTRACT BLOCKER
- exact requirement
- exact technical conflict
- evidence
- smallest proposed contract amendment
- affected acceptance criteria
```

No contract amendment is implicit in a code change.