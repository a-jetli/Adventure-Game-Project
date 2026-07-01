# TODO — Port "The Game" from pygame (GUI) to Textual (TUI) + web demo

> Working checklist for the Textual port. Source of truth for the eventual
> in-repo guide (`docs/PORTING_TEXTUAL.md`). Check off stages as they land.

## Progress

- [x] **Stage 0** — Safety: verify functional, then back up to remote ✅ done!
- [x] **Stage 1** — Prototype the threading bridge in isolation ✅ done!
- [x] **Stage 2** — Refactor: separate UI-agnostic driver from pygame entry ✅ done!
      *(2a driver+protocol & 2b palette/highlight extraction complete + verified; one live-GUI visual gate left for the user — see Stage 2b notes)*
- [x] **Stage 3** — Build the Textual UI (`game/tui.py`) + entry (`game_tui.py`) ✅ COMPLETE!
      *(bridge + all protocol methods + flat-button menus + clean input + in-panel streaming + highlighting + status bar + modular borderless sidebar cards + live theme-switch + combat HUD + clean quit incl. typed /quit. Look-and-feel polish pass done: neutral-charcoal muted palette, in-`#story` streaming, box.SIMPLE inline panels. See Stage 3 wrap-up + the 2026-06-25 request map.)*
- [x] **Stage 4** — Combat interface for Textual ✅ COMPLETE!
      *(combat HUD reuses the shared `ChoiceScreen` modal; combat-intro now a flashing transient banner that paces the worker; `GUICombatInterface`/`run_combat` reused unchanged — no `TUICombatInterface` needed. Headless-verified incl. a full fight to victory.)*
- [x] **Stage 5** — Entity detail — ✅ A (inspect sidebar) + C (collapsible cards, quests, day/night) COMPLETE!
      *(B = word-hover tooltips moved to Stage 7 as rich-widget polish. Headless-verified.)*
- [x] **Stage 6** — Per-session isolation for the web demo ✅ COMPLETE!
      *(`GAME_DATA_DIR`-driven data root via `logs.set_data_dir()`; debug + stats files folded in; default stays `./logs`. Headless-verified two roots stay isolated.)*
- [ ] **Stage 7** — Rich widgets & extensibility (icons, animation, music — **open list, user adds more**)
- [ ] **Stage 8** — Web serving + protection (provider-agnostic) — **last; ships on a finished product**

> **Maintenance — 2026-06-26 sweep (post Stage 6).** Port-parity + code-quality pass over the
> new UI. Fixed: Textual `get_input` now honors `allow_empty` (blank Enter on a turn is
> ignored, not a wasted LLM call) and strips input ends, matching pygame. Retired the pygame
> front-end to a **gitignored `legacy/`** package (`legacy/ui.py`, `legacy/game_ui.py`; run
> `python3 -m legacy.game_ui`) — fully decoupled, recoverable from history / backup branch.
> Deleted the throwaway `prototype_textual.py` and the dead `main.py` stub. Note: most
> `game/ui.py` / `game_ui.py` mentions below are **historical** (provenance of extracted code)
> — the live pygame files now live under `legacy/`. Remaining QOL parity gaps (menu number-key
> select, combat letter/number hotkeys) parked for **Stage 7**.
>
> **Maintenance — 2026-06-26 second sweep + docs.** Bug fix: **Esc in the combat HUD** (the UI
> delivers `"__back__"`) now reads as **flee** in `choose_action` (and cancel in `choose_item`)
> — it previously fell through `run_combat` as an invalid action that silently handed the
> enemies a free round. Verified (`scratchpad/combat_esc_test.py`). Docs second pass: the
> technical sections of `README.md` + `implementation_details.md` are rewritten to **present
> tense** (port-history phrasing removed; the changelog stays past-tense by design). Added a
> labelled **Claude's wishlist** + **icons/music design notes** to Stage 7 below.

---

## Context

The game is currently a **pygame GUI**: `game/ui.py` (~1,800 lines) opens an OS window,
blits pixels at 60 FPS, does per-word mouse-hover tooltips, typewriter animation, and
combat flashes. We want to move to a **Textual TUI** (terminal UI, the style Claude Code
uses) and — as a bonus — serve that same TUI in a browser via `textual serve` so a
recruiter can play with **zero setup and no API key** (the key stays server-side).

This is feasible with low risk because the codebase is already cleanly layered:

- `pygame` appears in **only two files**: `game/ui.py` and `game_ui.py`. The entire
  `game/` package (`engine`, `game_logic`, `combat`, `logs`, `schema`, `stats`, `config`)
  is UI-agnostic.
- `game_thread(ui)` (in `game_ui.py`) drives the whole game by calling ~40 methods on an
  `ui` object. Reimplement those methods against Textual and the driver is unchanged.
- Combat already goes through an abstract `CombatInterface` (`game/combat.py:40`).

**Goal:** a playable Textual TUI at feature parity (minus the hover degraded to a sidebar),
the pygame version kept working as a fallback during the port, and a documented,
protected path to a web demo. A comprehensive guide doc ships in the repo
(`docs/PORTING_TEXTUAL.md`) — this plan is its source.

### Decisions (confirmed with user)
- **Threading:** thread-bridge — keep `game_thread` on a worker thread; marshal screen
  updates to Textual via `call_from_thread`; keep the existing `threading.Event` latches.
  ("Wrap, don't rewrite." Async rewrite is a possible later step, not now.)
- **Entity detail:** Milestone A = inspect **sidebar** (robust, works over SSH/web);
  Milestone B = optional word-**hover** polish on top.
- **Web hosting:** protection measures written provider-agnostically; pick PaaS / VPS /
  tunnel at deploy time.

---

## Stage 0 — Safety: verify functional, then back up to remote

**Do this before touching anything.**

1. **Smoke-test that the game is functional** (gate for the backup):
   - `python -c "import game_ui, game.ui, game.game_logic"` (imports clean).
   - `python -m pytest tests/ -q` (or whatever the suite runner is — see `tests/eval.py`,
     `tests/playthrough.py`). Record pass/fail honestly.
   - If it's broken, stop and report — don't back up a broken state as "the good one."

2. **Back up to remote (single push — user's call: one remote backup, not two).**
   Captured the dirty pygame WIP as one untouched snapshot branch on the remote, then
   branched the port work off it locally so `main` and the remote stay simple:
   ```
   git switch -c backup/pygame-version          # carries WIP onto the snapshot branch
   git add -A
   git commit -m "Snapshot: functional pygame game before Textual port"
   git push -u origin backup/pygame-version      # the ONE push — preserved pygame state
   git switch -c textual-port                    # work branch, off the same commit (local)
   ```
   Snapshot commit: `992fa8b`. Restore path if the Textual port is abandoned:
   `git switch backup/pygame-version` (or `git reset --hard origin/backup/pygame-version`).
   All further work happens on `textual-port` (kept local until ready to push).

   **Gate results:** imports clean; engine suite `python3 -m tests.eval --engine-only`
   = 31/31 passed. (`python3`, not `python`, on this machine.)

---

## Stage 1 — Prototype the threading bridge in isolation (de-risk first)

The riskiest part is the thread/loop interaction, so prove it **before** refactoring the
real game. New throwaway file: **`prototype_textual.py`** (root, not imported by anything).

### The problem, in plain English (also goes verbatim in the guide)
Today the game runs two things at once: pygame redraws the window ~60×/s, and the game
logic (`game_thread`) runs on a **separate thread** that pauses whenever it needs input.
They coordinate with latches: the logic sets a flag, freezes on `event.wait()`, and the
draw side flips it (`event.set()`) on Enter. This works because pygame lets *any* thread
draw. **Textual is stricter: only its single event loop may touch the screen.** A
background thread that draws directly will corrupt/crash it.

**Fix (thread-bridge): "wrap, don't rewrite."** The game logic stays on its own thread,
still pausing on the same latches. The only change: when it wants to draw, it hands the
request to Textual's thread-safe postman, `App.call_from_thread(fn, *args)`, instead of
drawing directly. The waiting mechanism is unchanged.

### What the prototype must demonstrate
- A `textual.App` with a scrolling text log, an `Input`, and a button-menu modal.
- A worker thread started via Textual's `@work(thread=True)` (or `app.run_worker(...,
  thread=True)`) running a fake "game loop": print streamed text → block for input →
  show a menu → block for choice → loop.
- Blocking calls implemented exactly like today: `event.clear(); event.wait()`; the
  Textual-side handler (on `Input.Submitted` / button press) stores the value and calls
  `event.set()`.
- All screen mutations from the worker go through `self.app.call_from_thread(...)`.
- A clean shutdown that releases all waiters (mirror `_release_all_waiters`,
  `game/ui.py:567`) so the worker never hangs on a latch after the app exits.

If this runs smoothly, the whole port is low-risk. Keep the file in-repo until the real
UI lands, then delete.

### ✅ Done — what was built (Stage 1)
**File added:** `prototype_textual.py` (root, throwaway — not imported by anything; delete
when `game/tui.py` lands). **Dep:** `pip3 install textual` → **textual 8.2.7** (no
`requirements.txt` exists yet; record `textual` there when one is created in Stage 2/3).

Built a self-contained `GameApp(App)` that reproduces the real game's threading exactly:
- **Worker on its own thread.** `on_mount` starts `_game_loop` on a `threading.Thread`
  (daemon) — the direct analog of `threading.Thread(target=safe_game_thread)` in
  `game_ui.main()`. The loop streams an intro, then loops: prompt → block for input →
  (optionally) show a menu → block for choice → stream the result.
- **Same latch pattern as today.** `get_input` / `show_menu` do `event.clear();
  event.wait()` and return the value the UI thread stored — mirroring
  `GameUI.get_input` (`game/ui.py:482`) and `GameUI.show_menu` (`:499`). UI-thread
  handlers (`on_input_submitted`, `MenuScreen.on_button_pressed` → `deliver_menu_choice`)
  store the value and call `event.set()` to wake the worker.
- **The one real change vs pygame: drawing is marshalled.** Every screen mutation from
  the worker goes through a tolerant `_from_thread()` wrapper around
  `self.call_from_thread(...)` (no-ops if the app is tearing down, so the worker never
  crashes mid-draw). The worker never touches a widget directly.
- **Streaming** modeled as `begin/append/end` into a live `Static` line, then finalized
  into the `RichLog` — the analog of `begin/append/end_narrative_stream`.
- **Clean shutdown** via `action_quit` → `running=False` then `_release_all_waiters()`
  (sets every latch), mirroring `GameUI._release_all_waiters` (`game/ui.py:567`), so the
  worker unwinds instead of hanging on a `wait()` that would never be set.

**Verification:** added a headless `--selftest` mode (Textual `Pilot`) that drives the
whole flow — waits for the streamed intro + input latch, submits a line, waits for the
menu modal, clicks an option, then asserts the app shut down **and the worker thread
joined** (the decisive "no hung worker" check). `python3 prototype_textual.py --selftest`
→ `SELFTEST PASS`, green **5/5** consecutive runs (not flaky). Interactive run:
`python3 prototype_textual.py`.

**Takeaway:** the thread-bridge is proven — "wrap, don't rewrite" holds. The port is
low-risk; Stages 2–4 can reuse this latch+`call_from_thread` shape verbatim.

---

## Stage 2 — Refactor: separate the UI-agnostic driver from the pygame entry

`game_thread` and its helpers (`new_game`, `_handle_defeat`, `_handle_combat_aftermath`,
`pause_menu`, `opening_menu`, `settings_menu`, `journal_menu`, `run_setup`,
`show_tutorial`, the `_maybe_chronicle` / `_maybe_world_tick` machinery, etc.) live in
`game_ui.py` but **only use `pygame` in `main()`** — the driver itself is toolkit-agnostic.

1. **Create `game/driver.py`** and move every UI-agnostic function out of `game_ui.py`
   into it (mechanical: they already talk to `ui` abstractly). This lets the Textual entry
   reuse them verbatim instead of duplicating ~1,000 lines.
2. **Relocate `PAUSE_SENTINEL`** out of `game/ui.py` (which imports pygame) into
   `game/driver.py` (or a tiny `game/uikit.py`), so the Textual side never imports pygame.
   Re-export from `game/ui.py` for backward compatibility.
3. **Define the UI contract explicitly.** Add a `typing.Protocol` (e.g.
   `GameUIProtocol` in `game/uikit.py`) listing the ~40 methods the driver calls:
   `set_context, set_status, add_narrative, begin/append/end_narrative_stream,
   add_player_input, add_system, add_panel, add_combat_text, start_loading, stop_loading,
   clear, get_input, show_menu, begin_combat_intro, wait_for_combat_intro, show_combat_hud,
   wait_for_text_output, rehighlight_all, _release_all_waiters`, plus the `running`
   attribute. Both the pygame `GameUI` and the new Textual UI implement it. This is the
   port's checklist.
4. **Slim `game_ui.py`** to the pygame entry point (`apply_theme`, construct `GameUI`,
   the 60-FPS loop, `pygame.quit()`), importing the driver. Verify the pygame game still
   runs end-to-end after the refactor (regression gate before building anything new).

**Extract the shared, toolkit-free bits the new UI will reuse:**
- **Palette + highlight roles.** `game/ui.py` holds RGB tuples and semantic roles
  (`HIGHLIGHT_NPC`, `HIGHLIGHT_LOCATION`, …) and `THEMES` / `apply_theme` /
  `THEME_LABELS`. Lift the raw color data into a neutral structure (e.g.
  `game/palette.py`) both back-ends consume — pygame keeps using the tuples; Textual maps
  them to a Textual theme / CSS variables.
- **Highlight computation.** `_build_highlights` (`game/ui.py:683`) and
  `_extract_location_descriptors` (:343) compute role-tagged spans by regex over the
  narrative from `set_context` data — pure logic. Move to a shared helper that returns
  `(text, [(start, end, role)])`; pygame renders spans as colored blits, Textual builds a
  Rich `Text` with styles from the same spans.

### ✅ Done — Stage 2a (driver + protocol extraction)
**Files added:**
- `game/uikit.py` — toolkit-free `PAUSE_SENTINEL` + `GameUIProtocol` (`typing.Protocol`,
  `@runtime_checkable`) listing the full ~40-call UI surface the driver invokes, with
  signatures mirroring pygame `GameUI` exactly. This is the port's checklist; both
  back-ends implement it.
- `game/driver.py` — the entire UI-agnostic driver moved out of `game_ui.py`
  (`game_thread`, `new_game`, opening/pause/settings/journal menus, tutorial, setup,
  defeat/aftermath handlers, chronicle + world-tick machinery, `GUICombatInterface`,
  `run_combat_ui`, all the `_*_for_ui` helpers, `session_stats`, debug logging). Imports
  **no** UI toolkit; type hints use `GameUIProtocol`.

**Files changed:**
- `game_ui.py` — slimmed from ~1,166 lines to a ~50-line pygame entry point: `apply_theme`
  → build `GameUI` → worker thread runs `game_thread` → 60-FPS loop → `pygame.quit()`.
  Imports the driver.
- `game/ui.py` — now imports `PAUSE_SENTINEL` from `game/uikit.py` and re-exports it
  (backward compat for `from game.ui import PAUSE_SENTINEL`).

**Verification (all green):**
- `import game.driver` does **NOT** load pygame (`'pygame' in sys.modules` → `False`) —
  the decisive check that the Textual side can reuse the driver pygame-free.
- All modules import; `PAUSE_SENTINEL` re-export matches; `GameUI` structurally conforms
  to `GameUIProtocol` (every method present; `running` is an instance attr, set in
  `__init__`).
- **Engine suite 31/31** (`python3 -m tests.eval --engine-only`).
- **Headless pygame smoke** (`SDL_VIDEODRIVER=dummy`): `GameUI` constructs and survives
  `set_status` + `set_context` + `add_system`/`add_player_input`/`add_narrative` +
  begin/append/end stream + `render()` + `rehighlight_all()`. (Catches crashes/regressions
  at the API level — **not** visual correctness; that needs the real window, see below.)

### ✅ Done — Stage 2b (palette + highlight extraction)
**Files added:**
- `game/palette.py` — all RGB color constants + the three theme dicts (dark/light/earthy)
  + `THEME_LABELS` + `THEME_KEYS`, **moved verbatim** out of `game/ui.py`. Imports no UI
  toolkit. pygame does `from game.palette import *` (binds them as `ui` globals; the dark
  defaults); Textual will read `palette.THEMES[name]` and map role keys (`HIGHLIGHT_*`,
  `BG_COLOR`, …) to a Textual theme / CSS.
- `game/highlight.py` — the pure regex highlighter: `ROLE_*` constants, `KEYWORD_GROUPS`,
  `extract_location_descriptors()`, and `compute_highlight_spans()` → ordered
  `(start, end, role, key)` spans. Lifted from pygame `_build_highlights` /
  `_extract_location_descriptors`. Imports no UI toolkit.

**Files changed (`game/ui.py`):**
- Color/theme block replaced with `from game.palette import *`; `apply_theme` +
  `CURRENT_THEME` stay here (they mutate this module's globals, which render reads at
  call-time). `FONT_SIZE` stays too.
- `_build_highlights` is now a thin wrapper: calls `highlight.compute_highlight_spans`,
  then maps each span's role → the current-theme color global, filling the same
  `pos→color` / `pos→entity` dicts first-wins. **Output byte-identical** to before.
- `_extract_location_descriptors` delegates to `highlight.extract_location_descriptors`.

**Verification (all green, no GUI needed):**
- **Highlight extraction faithful:** new `_build_highlights` output compared against the
  **original from the backup branch** across 3 contexts × 5 texts = 15 checks → 0
  mismatches (both `highlights` and `entities` dicts identical); descriptor parity too.
- **Palette move faithful:** `palette.THEMES` / `THEME_LABELS` **equal** the backup's,
  value-for-value across all keys × all 3 themes; `apply_theme` swaps `game.ui` globals to
  exactly the backup's values for every theme (incl. `CURRENT_THEME`).
- `palette` and `highlight` import **pygame-free** (fresh interpreter); driver still
  pygame-free; `py_compile` clean; **engine 31/31**; headless render + live theme-switch +
  `rehighlight_all` OK; no leftover refs to moved names.

**Cleanup + completeness pass (pre-Stage-3):**
- **Protocol-coverage check:** cross-checked every `ui.*` and `self.ui.*` call the driver
  makes against `GameUIProtocol.__protocol_attrs__` → the driver's calls are a complete
  subset (21 methods + `running`); protocol also has `_release_all_waiters` (used by the
  entry's shutdown). So the protocol is the **complete checklist** for `TextualGameUI` —
  nothing the driver needs is missing.
- **Unused imports removed from `game/ui.py`:** dropped `import re` (regex moved to
  `highlight.py`) and trimmed the explicit palette import to just `THEMES` (the only star
  name used in-module; `THEME_LABELS` still reaches the driver via `import *`).
- Re-verified after cleanup: compile + imports + driver pygame-free + **engine 31/31** +
  headless render + Stage 1 prototype selftest all green.

**Port file inventory (on `textual-port`, uncommitted):** new — `game/uikit.py` (79),
`game/driver.py` (1142), `game/palette.py` (167), `game/highlight.py` (139),
`prototype_textual.py`, `docs/concept_ui.png`; changed — `game/ui.py`, `game_ui.py` (48),
`TODO_TEXTUAL_PORT.md`.

### ⏭ Remaining for Stage 2 (small)
- **Theme-picker abstraction (carry into Stage 3):** `driver._theme_picker` still
  lazy-imports `game.ui` (`from game import ui as ui_module`) to swap pygame theme globals.
  Lazy, so the driver stays pygame-free at import — but Textual needs its own theme path.
  Abstract via `palette` + a UI method when building `game/tui.py`.
- **Live-GUI visual gate (user runs):** `python3 game_ui.py` — new game, a few turns, a
  fight, save/load, a theme switch, pause (Esc), quit — eyeball parity with the pre-port
  build. Lower-stakes now (highlight/palette behavior proven byte-identical above), but
  still the one thing the headless checks can't see. Restore if needed:
  `git switch backup/pygame-version`.

---

## Stage 3 — Build the Textual UI (`game/tui.py`) + entry (`game_tui.py`)

New `game/tui.py` exposes `TextualGameUI` implementing `GameUIProtocol`, plus a `GameApp`
(the `textual.App`). New `game_tui.py` is the thin entry: build the app, start
`game_thread` as a threaded worker, run the app. `main.py` / a `--tui` flag can select it.

### 🎨 Design language / vision (from the user, 2026-06-25 — guides Stage 3+)
The concept image (`docs/concept_ui.png`) is **inspiration, not spec**. The actual vision:
- **Card/module feel:** content is grouped into blocks separated by **blank space**, as if
  each were a card. (In the transcript, space between entries; info shown as bordered
  cards/panels.)
- **Same overall layout as the pygame version:** the **terminal input at the bottom**, a
  **brief info bar up top** (status), and the **main narrative text in the large
  left/center area**.
- **Right side = the widget column.** ALL modules/tabs live on the **right only**. Start
  with the **commands** widget; planned additions (later, as scope grows): a
  **journal/quest tracker**, a **day/night cycle** animation, a **time-of-day / location**
  readout. Keep this region designed as a stack/tab host of swappable widgets.
- **Retro pixel animations** for those right-side widgets are a **later** stretch (Textual
  makes small animations easy) — don't build now, just don't preclude them.
- **More color themes** to be added later (the palette/theme system from Stage 2b already
  supports adding themes).
- Implication for Stage 3: build the right column as an extensible **sidebar host** (not a
  one-off commands list), and keep blocks visually card-separated.

### Layout (Textual widgets / CSS)

**Design-language reference (NOT a spec):** see `docs/concept_ui.png` (user's concept
mockup, saved 2026-06-25). It's **inspirational only** — for look-and-feel / visual
vocabulary (dark theme, monospace, rounded panels, inline accent-colored entities, a
status bar, a right sidebar, a bottom input with key hints). Do **not** treat any element
as required and do **not** implement imagined/illustrative features from it (e.g. the
exact glyphs, the `^t Method` control, the `v1.0.4` labels). The user will add more
direction manually as we go. ASCII of the mockup for quick recall without opening it:
```
┌───────────────────────────────────────────────────────────────┬──────────────────┐
│ RPG_TERMINAL v1.0.4 │ Tom  HP [███▒▒ 80%]  Brine Kettle Inn  Morning │ 👤 ♥ ◎ ⏱ │  ← status bar
├───────────────────────────────────────────────────────────────┼──────────────────┤
│ Previously...                                                  │ [ COMMANDS ]     │
│                                                                │ v1.0.4-alpha     │
│ You find yourself in the [back yard] of the [Brine Kettle]     │ ─────────────    │
│ Inn ... a peculiar [keyring] hanging on a brass hook ...       │ ◎ /explore       │
│                                                                │ ▤ /inventory     │
│ > I walk around                          (player input echo)   │ ♥ /hp            │
│                                                                │ ⏱ /time          │
│ You slip past the half-open [back door] and give the [yard]    │ ◎ /location      │
│ its proper going-over ...                                      │ ▦ /map           │
│   (highlighted entity words in accent colors; scrollable)      │ ? /help          │
│                                                                │                  │
│                                                                │ ── [ TUTORIAL ] ─│
├───────────────────────────────────────────────────────────────┴──────────────────┤
│ >> What do you do?                          ^j Send  ^t Method  ^s Save  ^q Quit  │  ← input + key hints
└───────────────────────────────────────────────────────────────────────────────────┘
```
Notes from the mockup: dark theme; monospace; rounded panel borders; a `RPG_TERMINAL`
app-title chip at top-left; HP as a colored mini-bar + `NN%`; entity words rendered in a
muted green/teal accent inline in the prose; `>` player-echo lines dimmed; the right
**sidebar lists the slash-commands** (with small glyphs) rather than the inspect-entity
list the plan originally specced — reconcile in Stage 5: sidebar can show **commands by
default, switch to entity-inspect** when relevant (or split into two stacked panes).
A `[ TUTORIAL ]` button pinned at the sidebar bottom. Bottom bar shows the `>>` prompt
plus footer **key hints** (`^j Send  ^t Method  ^s Save  ^q Quit`) — wire these as
Textual `BINDINGS` shown in a `Footer`.

- **Status bar** (top): HP bar + location + time + equipped weapon/armor. Maps from
  `set_status` (`game/ui.py:331`). Use `ProgressBar` or a styled `Static` for HP.
- **Transcript** (center): a `RichLog` / scrollable `VerticalScroll` of narrative,
  player input, system lines, panels, and combat text — the analog of the `blocks` list.
- **Sidebar** (right): commands list (per mockup) + inspect-entity detail (Milestone A);
  `[ TUTORIAL ]` button pinned at the bottom.
- **Input** (bottom): a Textual `Input` with a `>>` prompt; `Footer` with the key hints.
- **Theme/CSS** from the lifted palette; `rehighlight_all` becomes a refresh/recompose.

### Method-by-method mapping (the checklist)
| Driver call | Textual implementation |
|---|---|
| `get_input(allow_empty)` | latch on `threading.Event`; `Input.Submitted` stores text + `set()`. Esc returns `PAUSE_SENTINEL`. |
| `show_menu(...)` / `show_combat_hud(...)` | push a `ModalScreen` with buttons (or an `OptionList`); button press stores choice + `set()`. Same latch pattern. |
| `add_narrative` / `add_system` / `add_panel` / `add_player_input` / `add_combat_text` | `call_from_thread` → append a styled line/`Panel` to the transcript. |
| `begin/append/end_narrative_stream` | `call_from_thread` appending deltas to a live line; finalize with full highlight spans on `end`. |
| `start_loading` / `stop_loading` | toggle a `LoadingIndicator` / spinner widget. |
| `set_context` / `set_status` | `call_from_thread` updates sidebar data + status bar. |
| `begin_combat_intro` / `wait_for_combat_intro` | flash via Textual timer/CSS animation; latch as today. |
| `wait_for_text_output` | typewriter is optional in a TUI; either keep a reveal animation with the same poll, or render instantly and make this a no-op. |
| `clear` | empty the transcript. |
| `rehighlight_all` | recompute Rich `Text` styles from shared highlight helper. |
| `_release_all_waiters` | `set()` every latch on shutdown (input/menu/combat/intro). |
| `running` | bool flag flipped on app exit; checked by the worker. |

**Critical bridge rules (state in the guide):**
- Every method called from the worker thread that mutates widgets must go through
  `self.app.call_from_thread(...)`. Reads of plain data can stay direct (guard shared
  mutable state with the existing `self.lock` where the pygame code did).
- On app quit (`action_quit` / unmount), set `running = False` **then**
  `_release_all_waiters()` so the worker never blocks on a latch that will never be set.

### ✅ Done — Stage 3a (skeleton + bridge + all protocol methods)
**Files added:** `game/tui.py` (`GameApp(App)` — the app *is* the `ui` the driver drives,
like pygame's `GameUI`; plus `ChoiceScreen` modal) and `game_tui.py` (thin entry:
`GameApp(theme_name=config.UI_THEME).run()`). Both import **pygame-free**.

**Implemented (functional, not yet fully polished):**
- **Thread bridge** identical to the Stage 1 prototype / pygame: driver runs on a worker
  thread (started in `on_mount`, loops while it returns `"menu"`); blocking calls
  (`get_input`, `show_menu`, `show_combat_hud`, `wait_for_combat_intro`) use
  `threading.Event` latches; **every** screen mutation goes through `_from_thread`
  (tolerant `call_from_thread` wrapper). `_quit_app` sets `running=False` →
  `_release_all_waiters()` → `exit()`. *(NB: method renamed from `_shutdown` — that name
  collides with Textual `App._shutdown`.)*
- **All 21 `GameUIProtocol` methods** + `running`: context/status, narrative (with live
  highlighting), player/system/panel/combat lines, begin/append/end streaming, loading
  indicator, menus + combat HUD (via `ChoiceScreen`), clear, intro banner, no-op
  `wait_for_text_output`/`rehighlight_all` (stubbed for later).
- **Highlighting already wired:** `_render()` builds a Rich `Text`, coloring the shared
  `highlight.compute_highlight_spans` by role → `palette.THEMES[theme]` color (first-wins
  precedence). `area_intro` tints the base. Status bar built from `set_status`.
- **Layout** per the vision: status bar (top), transcript `RichLog` (left/center), right
  **sidebar** (`VerticalScroll` host — commands widget now, room for more), input docked
  bottom, `Footer`. Blank line after each block → card separation.
- **Esc:** mid-play → `PAUSE_SENTINEL` (driver opens pause menu); in a modal → `__back__`.

**Verification (headless Textual `Pilot`, no LLM — fake worker drives the bridge):**
- Full flow — context/status/stream/typed-input/menu-click/combat-HUD-click/panel →
  **clean shutdown, worker thread joins** (no hang). **5/5** non-flaky. `py_compile` clean.
- Esc paths asserted: `get_input`→`PAUSE_SENTINEL`, menu→`__back__`.
- `import game.tui` is pygame-free.

### ✅ Done — Stage 3a.1 (quit fix + polish pass, after first live run)
First live run (in VS Code's terminal) surfaced two issues; both addressed:
- **Quit bug FIXED:** Ctrl+Q did nothing while a modal was open — and the opening menu *is*
  a modal, so the first screen couldn't be quit. Root cause: app-level bindings don't fire
  when a `ModalScreen` has focus. Fix: `Binding("ctrl+q", "quit", priority=True)` (+ ctrl+c).
  Verified headlessly: ctrl+q over a menu modal now exits cleanly (worker joins). *(Method
  was already renamed `_shutdown`→`_quit_app` to avoid colliding with Textual internals.)*
- **Polish pass for proportions / "blocky" look** (toward the Toad/Posting aesthetic —
  refs saved in `docs/inspiration/`): titled **rounded-border panels** (transcript =
  "Story", sidebar = "Commands" via `border_title`), a real **header band** (bold
  `RPG_TERMINAL` title + a live status line with HP bar / ◎ location / ⏱ time / ⚔ gear),
  a dedicated **input row** (`>>` prompt + `Input`), `Footer`, and consistent padding /
  margins / proportions (sidebar width 36, transcript `1fr`). Removed dead `action_noop`.
- **Run it in a REAL terminal** (Terminal.app / iTerm2), **not** VS Code's integrated
  terminal — the latter degrades Textual's fonts/truecolor/mouse/sizing. ⌘-maximize for
  proportions. Quit = Ctrl+Q.
- Re-verified: `py_compile` clean; quit-over-modal + full bridge pilot pass; **4/4** non-flaky.

### ✅ Done — Stage 3a.2 (look overhaul, after 2nd live run + Textual research)
2nd live run (real terminal, 120×30 / 138×36) showed: highlighting *did* work but was
subtle; chunky default `Button`s + no cohesive theme = "MSDOS/clunky"; input outline
looked broken; `^q` caret; FPS felt low. **Textual research** ([themes guide](https://textual.textualize.io/guide/design/),
[binding API](https://textual.textualize.io/api/binding/)) → fixes applied:
- **Custom Textual theme generated from `game/palette`** (`_theme_from_palette`): registers
  `thegame-{dark,light,earthy}` mapping our colors → `primary/accent/foreground/background/
  surface/panel/...` + `variables` (footer-key, block-cursor, selection, scrollbar,
  border). Chrome now matches the narrative accents — **one cohesive look**, and live
  theme-switch is now possible via `self.theme = "thegame-<name>"`.
- **Flat `OptionList` menus** replace chunky `Button`s in `ChoiceScreen` (the main
  "MSDOS" culprit) — keyboard+mouse, accent highlight bar, same latch pattern.
- **One clean bordered input box** (`>>` prompt + borderless `Input` inside a single
  rounded `#inputrow`) — fixes the broken double-outline. Panels now have `$surface`
  backgrounds that lift off a darker `$background` (depth, like Posting).
- **Footer `Ctrl+Q`** via `key_display`; command palette disabled (`ENABLE_COMMAND_PALETTE
  = False`) so no stray `^p`.
- **Streaming throttle** (`append_narrative_stream` flushes ≤20×/s) to cut UI-thread churn
  (FPS). Remaining FPS feel is terminal-dependent — iTerm2 ≫ Terminal.app for Textual.
- **Block retention + working `rehighlight_all`:** every transcript block is recorded
  (`self._blocks`); `rehighlight_all` re-renders them, so a theme switch recolors
  on-screen text (foundation for live theming).
- **Sidebar = card host (3b started):** stacked cards — Commands + a live Location/time
  card (fed from `set_status`); room to add journal/quests/day-night next.

**Verification (headless Pilot):** themes build for all 3; OptionList menus return correct
values; streaming + `rehighlight_all` + clean quit; quit-over-modal **5/5**; `py_compile`
clean. Highlighting confirmed working (it always was — now reads clearly on the themed bg).

### ✅ Done — Stage 3a.3 (menu bug fix + theme-switch abstraction)
3rd live run: opening-menu options rendered as **blank bars** (OptionList text invisible
in-terminal) and a stray blue bar near the input. Fixes:
- **Menus → flat `Button`s** (replaced `OptionList`). Labels always render; styled flat
  (no chunky border, accent on focus/hover). Verified: buttons carry correct labels
  (`New game`/`Load game`/…) and selecting returns the right value.
- **Single clean bordered `Input`** (dropped the prompt+row wrapper that caused the broken
  double-outline / stray bar); `>>` lives in the input's `border_title`.
- **In-game theme switching now works (Stage 2 carryover DONE):** added `set_theme(name)` +
  `get_theme_name()` to `GameUIProtocol`; pygame `GameUI` applies via module `apply_theme`,
  TUI sets `self.theme = "thegame-<name>"` + re-renders. `driver._theme_picker` rewritten
  to use **`game.palette`** (toolkit-free) + `ui.set_theme/get_theme_name` — the driver no
  longer imports `game.ui` at all. Verified: real `_theme_picker` → menu → pick Earthy →
  `app.theme` switches live + transcript recolours; pygame `set_theme` works headless.
- Verified: `py_compile` clean; driver pygame-free; both UIs conform to the protocol;
  engine **31/31**; quit-over-modal **5/5**.

**➡️ Stage 3 is functionally COMPLETE** (all protocol methods, working menus, input,
streaming, highlighting, status bar, sidebar cards, live theming, combat HUD, clean quit).
What's left is **look-and-feel polish**, intentionally deferred to a dedicated Textual
research+design pass (user's call):

### 🎨 Stage 3 look-polish pass (✅ complete)

**Terminal capability (researched):** user is on **macOS Tahoe 26.2, Terminal.app,
`COLORTERM=truecolor`** — full 24-bit colour (Terminal.app gained truecolor in macOS 26).
So no 256-colour downsampling; the muted palette renders faithfully. ([Terminal truecolor](https://www.macrumors.com/2025/06/16/apples-terminal-app-macos-tahoe/))

**✅ Done — muted editorial palette retune (per user's design brief).** Brief + concrete
role→colour mapping saved to **`docs/DESIGN_PALETTE.md`**. Philosophy: quiet/editorial,
colour is rare semantic punctuation, **cool sage = world, warm brass = player/interaction,
dusty salmon = danger** — which maps 1:1 onto our existing `highlight.py` roles, so it was
a palette **retune, not a restructure**.
- `game/palette.py` **`"dark"` theme retuned** to the muted system (bg `#0B0F14`/`#131A22`,
  text `#D7D8DA`, sage world `#7FAE9E`/`#87B8A8`, brass player/interaction `#D39B57`/
  `#E0AA67`, salmon danger `#DB7E77`). `light`/`earthy` **untouched** (they fully override).
  Both UIs + all themes share this; default `UI_THEME=dark` so it shows immediately.
- `game/tui.py` CSS: borders now **subtle neutral** (`$surface-lighten-2`) to blend per the
  brief ("avoid obvious panel separation"); warm `$accent` reserved for titles/focus/modal
  edge; panels lift via bg value steps (`$background`→`$surface`).

**✅ Done — sidebar de-boxed into borderless cards (Gemini feedback reconciled).** The
sidebar host lost its single outer round border; the right column is now a **stack of
borderless `.card`s** that lift via a background value step (`$surface`) and are separated
by blank space — the user's "editorial cards" aesthetic, and it kills the box-in-box
nesting. Three cards mount: **World** (live location/time from `set_status`), **Commands**
(slash-command crib), **Journal** (`#side-journal` stub for quests). Headless-verified:
3 cards, borderless host, `#side-location`/`#side-journal` present.

**Gemini screenshot-feedback pass (weighed vs the user's vision, 2026-06-25):**
- *Already done (it couldn't see the code):* inventory is an inline `rich.Panel` (not a
  bordered widget in the log); `padding: 1 2` on reading panels; native `Footer`; muted
  input-focus border (no neon).
- *Adopted:* de-box the sidebar (above). Focus hierarchy = the **input** warms to brass on
  focus while panels stay quiet (right form for our single-input flow, vs Posting's
  tab-between-panels model).
- *Declined (conflicts with the user's vision):* Posting-style flush dock-to-edge / zero
  margin / directional dividers / continuous surface — the user wants editorial **cards
  separated by blank space**, the opposite language. Also keeping the **custom header band**
  (native `Header` can't host the live HP/loc/time/weapon status bar).

**✅ Done — neutral-charcoal retune (user: "too close to nautilus/vscode blue").** The
structural neutrals in `palette.py` `"dark"` were de-blued toward traditional charcoal
(faint cool, not navy): panel `#17181B` (was `#131A22`), deepest bg `#0E0F11`, borders
`#3C3E44`, selection/menu/status/hp-empty greys all neutralised. **Accents untouched**
(brass name/sage world/salmon danger keep the brief). `light`/`earthy` untouched.

**✅ Done — narrative now streams *inside* the story panel (fixes "glitch block below
the UI" + "no streaming").** Root cause: `append_narrative_stream` was dumping live text
into a `#thinking` Static positioned *below* the story panel, then `end_narrative_stream`
hid it and wrote the final block into the transcript — the bottom flash + the "jump".
Fix in `tui.py`: the left column is now a `#story` card wrapping the scrolling
`#transcript` **plus** a `#live` region; streamed deltas render (highlighted) in `#live`
inside the panel, auto-scroll-pinned, then fold into the transcript on completion. Spinner
also lives in `#live`. Headless-verified: live-on mid-stream, hidden after, final block
committed.

**✅ Done — typed `/quit` & `/exit` now actually exit (only Ctrl+Q did before).**
`driver._save_and_quit` was blocking on a *second* "press any key to close" `get_input`
before setting `running=False`, so typed quit looked dead. Removed that gate (+ the 0.5s
sleep): it saves, shows the summary, sets `running=False` → worker loop ends → app exits
in one step. (Shared by typed quit and the pause-menu "Save & quit".)

**✅ Done — inline-panel border gaps softened (user: "inventory yellow lines have gaps").**
Inline `Panel`s (inventory/read-outs) switched to `box.SIMPLE` (horizontal rules only — no
vertical/corner glyphs), which removes Terminal.app's font-line-height gap artifacts on
long lines and reads more editorial.

**✅ Done — typed `/quit` & `/exit` REALLY exit now (2nd report).** First fix removed the
"press any key" gate but the app still didn't close — root cause was a **bound-method
identity bug** in `tui.py:_from_thread`: the teardown guard `fn is not self._quit_app` is
*always* true because `self._quit_app` builds a new bound-method object on every access, so
once the worker set `running=False` the final `_quit_app` marshal was swallowed and
`self.exit()` never fired (Ctrl+Q worked only because `action_quit` calls `_quit_app()`
directly). Fixed by comparing the underlying function: `getattr(fn, "__func__", None) is
GameApp._quit_app`. Headless-reproduced (was `_exiting=False`) → now `_exiting=True`.

**✅ Done — streaming (3rd report: "comes out in one big chunk instantly"). REAL root
cause found via a live diagnostic.** Instrumented one real `gpt-5.4-nano` call
(`scratchpad/stream_diag.py`): the model emits 124 `content.delta` events **but** the
SDK's partial parser only exposes `event.parsed.narrative` **once the string field is
complete** (all narrative-bearing deltas already showed the full 498 chars), and every
delta lands in a **~40 ms burst after a ~1.25 s reasoning pause**. So `_stream_completion`
calls `on_delta` effectively **once, with the whole narrative** → nothing to stream, no
matter the UI. Network token-streaming is simply **invisible** for this fast reasoning
model. Two fixes:
  1. **Transcript refactored `RichLog` → `VerticalScroll` of per-block `Static` widgets**
     (needed regardless): the narrative block is one widget that grows in place and stays —
     no separate region, no reflow, no jump. Bonus: blocks are now individually
     addressable → foundation for clickable/animatable modules (Stage 7).
  2. **Client-side typewriter** (the pygame build had this; the TUI had stubbed it
     "instant"). A UI-thread `set_interval` reveals the narrative at reading pace
     (~constant ~1.6 s, any length), trailing behind whatever the deltas deliver — so an
     all-at-once burst **still reads as smooth streaming**. `wait_for_text_output` now
     blocks (bounded 15 s) until the reveal completes, for combat/following beats.
  Headless-verified: a full text delivered in ONE `append` still reveals through 37
  distinct partial lengths before committing (with area tint); quit/menus/sidebar/theme
  regression green.

**✅ Done — typewriter made UNIVERSAL + constant CPS (user: "all new text through
streaming… consistent characters-per-second… a bit slower").** Replaced the
narrative-only timer with a single **reveal queue**: every prose block
(`narrative` / `system` / animated `combat`) types out at a **constant
`GameApp.TYPEWRITER_CPS` (80 c/s)**, one block at a time (earliest first) — so streamed
and non-streamed text (e.g. the resume recap via `add_narrative`) look identical, and
short messages no longer crawl while long ones race (the old constant-*duration* model's
flaw). **Instant** (matching pygame): player echo, info `panel`s (bordered cards never
stream well), the spinner, and `add_system(instant=True)`. The streamed narrative is just
a *dynamic* queue item whose target grows as deltas arrive. `wait_for_text_output` waits
on the queue-drained event (`_reveal_idle`, bounded 20 s). Speed is **one knob**
(`TYPEWRITER_CPS`). Headless-verified: blocks reveal in order
(player·system·narrative·panel·combat), observed ≈80 c/s, `wait_for_text_output` blocked
until drained, quit/bridge regression green. Ref: pygame `game/ui.py` `typewriter_speed`.

**✅ Done — skip / reveal-all = "press any key" (REVISED; the Ctrl+K version was a bug).**
The first cut bound `Ctrl+K` (`priority=True`) for skip — but Textual's `Input` already
uses Ctrl+K for *delete-to-end-of-line*, so the override **reset/garbled the UI**. Removed
that binding entirely. Skip is now: **typing any character** (`on_input_changed`) or
**Enter** (`on_input_submitted`) while text is revealing calls `_reveal_all()`; the app-level
`on_key` catches the rest (Esc etc.) while revealing. A grey italic indicator
**`#skip-hint` "press any key to skip…"** sits just below the story area (shown only while
revealing, cleared when idle). Headless-verified: typing 'l' or Enter drains in ~0.2 s vs
~1.3 s natural; empty-Enter skips *without* submitting; hint toggles.

**✅ Done — clipboard / line-editing keys now work in the input (user request).** Removed
our `Ctrl+C`=quit binding (it was stealing copy). Textual's `Input` already provides
**Ctrl+C copy · Ctrl+X cut · Ctrl+V paste · Ctrl+Backspace delete-word · Ctrl+W/U · Ctrl+K
delete-to-end · Ctrl+A/E home/end**. Quit is now **Ctrl+Q only** (still `priority=True`,
fires over modals). (macOS Terminal.app's ⌘C/⌘V also work natively.)

**✅ Done — menu arrow-key navigation (user request).** `ChoiceScreen.on_key` moves the
highlight with **↑/← (prev), ↓/→ (next), wrapping**; **Enter/Space/click select** (Textual
`Button`), **Esc = back/cancel**. Headless-verified: down·down·up focus walk + Enter selects
the right option.

**✅ Done — resume recap no longer half-streams (user: "streams grey stuff… not the
inventory… then streams the bottom").** Added an `instant` flag to `add_narrative`
(protocol + both UIs); the driver's load path now renders the whole catching-up block
(welcome lines, inventory panel, recap) **instantly** so it appears at once instead of
animating around the instant inventory panel. Live turns still type out.

**✅ Done — typewriter speed 1.5× → `TYPEWRITER_CPS = 120`** (was 80; user: "1.5x the
streaming speed").

**✅ Done — animated, bigger loading indicator (user request).** The "thinking" line is
now an **animated rotating orb** (`◐◓◑◒`, `set_interval` 0.12 s) in bold brass with pulsing
dots, given extra presence via `.blk-loading { padding: 1 0; text-style: bold }`. Cleared
(timer stopped + removed) on first delta / `stop_loading`. Headless-verified: frames
advance and it clears.

**🟡 Remaining known-minor (cosmetic, not blockers):**
- **Font size (user: "font up 1–2 sizes across the board"):** a TUI renders into the
  terminal's fixed character cells — the **app cannot set font size**. It's a Terminal.app
  setting: ⌘‑+ (or Settings → Profiles → Text → Font). If "things feel cramped" is the real
  ask, the in-app lever is more padding/spacing (not done — would change the approved look;
  ask before applying).
- **High contrast / "blocky" feel:** the user flagged this for later (contrast fix
  deferred; "blocky" = the cell-grid nature of TUIs, hard to soften). Revisit after Stage 4.
- **Round-border glyph gaps** on the two big panels (`#story`, `#cmd`): font line-height;
  looked clean in the latest screenshot, so leaving the round borders. Sidebar is borderless
  and inline panels are `box.SIMPLE`.
- **Many block widgets over a very long session:** the widget-per-block transcript is heavier
  than `RichLog` for hundreds of blocks. Fine for demo length; revisit (cap/virtualize) only
  if a long playthrough lags.
- **Live gate (user):** re-run `python3 game_tui.py` — confirm the animated spinner, skip
  (Ctrl+K / Enter), and the typewriter pace feel right.

### ✅ Stage 3 — COMPLETE (wrap-up)
All protocol methods, flat-button menus, single clean input, semantic highlighting, live
status bar, **modular borderless sidebar cards**, live theme-switch, combat HUD,
neutral-charcoal muted palette. Text rendering settled on a **`VerticalScroll` of per-block
`Static` widgets** (each block individually addressable → foundation for Stage 7) driven by
a **universal typewriter**: all prose (`narrative`/`system`/animated `combat`) reveals at a
constant `GameApp.TYPEWRITER_CPS` (120 c/s), one block at a time; player echo / panels /
spinner / the resume recap are instant. **Animated rotating-orb spinner**, **skip = press
any key** (grey `#skip-hint` below the story), **menu arrow-keys** (↑↓←→ + Enter/Esc),
**Input clipboard/edit keys** (Ctrl+C/X/V/Backspace, via Textual), and **clean quit**
(Ctrl+Q + typed `/quit`,`/exit`). Headless bridge + typewriter + spinner + skip + menu +
quit checks pass; engine import clean.

**Key knobs / entry points (for fresh context):** speed = `GameApp.TYPEWRITER_CPS`
(`game/tui.py`); palette = `game/palette.py` `_THEME_DARK` (light/earthy override it);
the driver↔UI contract is `GameUIProtocol` in `game/uikit.py`; the UI-agnostic driver is
`game/driver.py`; run with `python3 game_tui.py`. Scratch tests used during Stage 3 live in
the session scratchpad (not committed).

### 🗺️ Where the user's 2026-06-25 requests land in the roadmap
| # | Request | Stage | Status |
|---|---|---|---|
| 1 | Right modules **minimizable** | **Stage 5** (interactive sidebar) | ✅ done — each card is a Textual `Collapsible` (clickable ▶/▼) |
| 2 | Less-blue **charcoal** bg + inventory line gaps | **Stage 3** | ✅ done this pass |
| 3 | `/quit` `/exit` actually kill the app | **Stage 3** | ✅ done this pass |
| 4 | **Modular/future-proof** for custom icons, icon animations, background music + music-player widget; right-side widgets **clickable** | **Stage 7** (extensibility) + clickable/minimizable bits in **Stage 5** | planned — see Stage 7 notes |
| 5 | "Glitch text block below the UI" on first LLM return | **Stage 3** | ✅ done (widget transcript; no separate region) |
| 6 | "No streaming?" / "one big chunk" | **Stage 3** | ✅ done (universal typewriter — model returns whole field at once) |
| 7 | Animated + bigger loading icon | **Stage 3** | ✅ done (rotating-orb spinner) |
| 8 | Press-to-skip / reveal-all + hint | **Stage 3** | ✅ done — **press any key** + grey `#skip-hint` (Ctrl+K version was a bug, removed) |
| 9 | Font up 1–2 sizes everywhere | n/a | ⚠️ terminal setting (⌘‑+), not app-controllable — see known-minor |
| 10 | 1.5× typewriter speed | **Stage 3** | ✅ done (`TYPEWRITER_CPS` 80→120) |
| 11 | Resume recap streams inconsistently | **Stage 3** | ✅ done (resume block now instant) |
| 12 | Menu arrow keys + Enter/Esc | **Stage 3** | ✅ done (↑↓←→ wrap, Enter select, Esc back) |
| 13 | Ctrl+C/V/X/Backspace in input | **Stage 3** | ✅ already in Textual `Input`; unblocked by dropping our Ctrl+C binding |

**Moved out of Stage 3:** the **combat-intro flash** belongs with the combat UI → **Stage 4**.
Wiring the **Journal card to real quests** + a **day/night clock** share the sidebar-data
plumbing → **Stage 5** (the World card is already live from `set_status`).

---

## Stage 4 — Combat interface for Textual ✅ COMPLETE

**Key finding:** no `TUICombatInterface` was needed. `GUICombatInterface` (`game/driver.py:674`)
and `run_combat` / `run_combat_ui` are already **UI-agnostic** — they only call protocol
methods (`begin_combat_intro` / `wait_for_combat_intro` / `add_combat_text` /
`wait_for_text_output` / `show_combat_hud`) and read `ui.running`. The same interface drives
both front-ends; Stage 4 was just finishing the Textual side of those methods.

### ✅ Done
- **Combat HUD** already routes through `ChoiceScreen` (the shared modal): `show_combat_hud`
  pushes it with the `status_lines` rendered as coloured `.modal-status` rows above the
  flat `Button` options, same latch (`combat_ready`) + Esc/arrow/Enter handling as menus.
  `choose_item` reuses it with a vertical item list. No combat-specific widget required.
- **Combat-intro flash** (was: emit title + release latch instantly): `begin_combat_intro`
  now mounts a transient centered banner (`.blk-combat-intro`) and **flips it bright/dim
  `flashes×2` times** via `set_interval` (`_tick_combat_intro`); `_finish_combat_intro`
  stops the timer, **removes the banner** (the `═══ COMBAT — X ═══` log line from
  `run_combat_ui` is the persistent header — same as the old pygame overlay vanishing), and
  sets `combat_intro_ready`. `wait_for_combat_intro` blocks on it (bounded `timeout=10`).
- **Latch always fires:** every path in `_start/_tick/_finish_combat_intro` is wrapped so a
  render bug calls `_finish_combat_intro` (which sets the latch); `not self.running` short-
  circuits to `.set()`; `_release_all_waiters` still sets it on quit; `_clear_transcript`
  stops a mid-flash timer. The worker can never hang on the intro.

### Verified (headless, `scratchpad/combat_test.py` — all PASS)
- `intro_flash`: banner mounts mid-flash, worker is **paced** (~0.30s for 3 flashes), banner
  removed + latch set after.
- `hud`: 3 status rows render; ↓ + Enter selects the right option through the HUD.
- `full_combat`: a real `run_combat_ui` (fists vs 3 hp goblin) driven to **victory**
  end-to-end through the Textual modal.
- Stage-3 regression suite (`scratchpad/v2.py`) still green.

---

## Stage 5 — Entity detail ✅ A + C COMPLETE (B → Stage 7)

- **✅ Milestone A — Inspect sidebar.** New **Inspect** card holds an `OptionList`
  (`#inspect-list`) rebuilt from `set_context`'s known lists + the `entity_info` map (the
  same detail text the hover tooltips would use). `_refresh_inspect` lists **People / Places /
  Items** under disabled section headers (player included as a person); selecting a row fires
  `on_option_list_option_selected`, which shows that entity's detail in `#inspect-detail`.
  `set_context` marshals `_refresh_inspect`, so it tracks state every turn. Robust everywhere
  (plain selectable list — works over SSH and in-browser).
- **✅ Milestone C — Interactive sidebar (user request #1: minimizable + clickable).** Every
  sidebar module is now a Textual **`Collapsible`** (clickable ▶/▼ header) — World / Inspect /
  Journal open, Commands collapsed by default; styled to keep the editorial look. **Journal
  wired to real quests:** new `set_quests(list[(title, detail)])` protocol method; the driver
  pushes active quests from `_refresh_ui` (pygame no-ops it), Textual renders them in
  `#side-journal` via `_render_journal`. **Day/night clock:** the World card shows a
  ☀/◐/◑/☾ glyph + time label off `set_status`'s `time_label` (`_DAYNIGHT` map). Cards stay
  discrete widgets (not log text), so they remain individually addressable/clickable — the
  foundation for Stage 7.
- **⏭ Milestone B — Word hover → moved to Stage 7.** Per-word hover tooltips are a
  rich-widget polish (desktop/browser only, not bare SSH); parked in the extensibility stage
  rather than blocking the core sidebar. See Stage 7.

### Verified (headless, `scratchpad/stage5_test.py` — all PASS)
- `inspect_populated` (7 options = 4 entities + 3 headers, detail map of 4), `inspect_detail`
  (selecting a row shows its info), `journal` (both active quests render), `daynight`
  (night → ☾), `collapsible` (Commands starts collapsed; toggling World minimizes it).
  Stage-3/4 suites still green.

---

## Stage 6 — Per-session isolation for the web demo ✅ COMPLETE

`textual serve` runs **one process per browser connection**, so isolation is handled at the
process level by giving each session its own data root.

### ✅ Done
- **Single configurable data root in `game/logs.py`.** Added `set_data_dir(root)` which
  reassigns every derived path (`LOGS_DIR`, `REGIONS_DIR`, `NPCS_DIR`, `EVENTS_DIR`,
  `WORLD_FILE`, `SESSION_FILE`, `SAVE_FILE`, `SAVES_DIR`, `BOOKS_DIR`, plus `DEBUG_FILE` and
  `STATS_FILE`). It's called once at import with `os.environ.get("GAME_DATA_DIR", "logs")`,
  so the env var picks the root; functions read the globals live, so it's total.
- **Folded in the two stray hardcodes:** the driver's debug log (was `DEBUG_LOG =
  "logs/debug_narrative.txt"`) now uses `logs.DEBUG_FILE`; `game/stats.py`'s
  `session_stats.json` now uses `logs.STATS_FILE` (lazy import — no cycle). Both honor the
  per-session root.
- **Default unchanged:** with no env var the root is `./logs` — local desktop play is
  byte-for-byte the same. `tests/eval.py`'s existing `logs.SAVES_DIR` monkeypatching still
  works (same module-global it always patched).
- **For the web demo (Stage 8):** launch each session with a unique `GAME_DATA_DIR` (e.g.
  `sessions/<uuid>/`) + periodic cleanup. No app code change needed there — just the env.

### Verified (headless, `scratchpad/stage6_test.py` — all PASS)
- `default_root` (no env → `./logs` tree), `env_root` (a save lands under the temp root),
  `two_sessions_isolated` (two roots each see only their own slot), `set_data_dir_repoints`
  (every derived path moves, incl. stats + debug). Stage 3/4/5 suites still green.

---

## Stage 7 — Rich widgets & extensibility (user request #4)

> **Swapped ahead of web serving (2026-06-26):** the user wants the demo to go online only
> on a *finished product*, so all the polish/extensibility lands first and web serving is now
> the final stage (8). **This list is intentionally open — the user will add more items.**

Goal: keep the architecture open so we can later add **custom icons, animated icons,
background music + a music-player widget**, and make the right-side modules **clickable**,
**without** reworking the core. Design principles to hold to *now* so this stays cheap later:

- **Keep UI state behind the `GameUIProtocol`.** The driver never imports Textual; new
  chrome (music player, animated status) is added in `tui.py` only, behind existing/added
  protocol methods. Don't leak widget concerns into `game/driver.py` or the engine.
- **Sidebar modules are discrete widgets, not log text.** Already true (each `.card` is its
  own widget). That's what makes them individually **minimizable/clickable** (Stage 5
  Milestone C) and animatable here. Avoid ever moving them into the `RichLog`.
- **Icons:** today the sidebar uses Unicode glyphs in `_COMMANDS` / status bar. A future
  icon set = a small `name → glyph/style` registry in `palette.py` (theme-swappable), so
  icons follow the active theme. Animated icons = a `set_interval` cycling glyphs/styles on
  a `Static` (same mechanism as the planned combat-intro flash).
- **Background music + player widget:** audio is out-of-band (a separate thread/process —
  e.g. a small `pygame.mixer` or system player — *not* the TUI). Add a thin `audio` module
  with `play/pause/stop/volume`; the **music-player card** is just a Textual widget bound to
  it (clickable transport buttons). Terminals can't emit audio themselves, so this only runs
  in local/desktop play, **not** the `textual serve` web demo (note for Stage 8).
- **Clickable widgets:** Textual already delivers mouse events; wiring `Button`/`Click`
  handlers on sidebar cards is incremental once they're `Collapsible` (Stage 5 C).
- **Word-hover tooltips (was Stage 5 Milestone B).** Make each highlighted word in the
  narrative a hoverable element with a tooltip from the same `entity_info` map that already
  feeds the Inspect card. Textual supports cell-level mouse hover in desktop terminals and
  in-browser via `textual serve` (**not** bare SSH), so it's polish on top of the
  always-available Inspect list — fiddlier/more brittle, hence parked here.

**Open list — USER's items (the user will add more here):**
- _(reserved for new extensibility / widget ideas the user wants — append as they come up)_

---

### ✅ Built so far in Stage 7

- **HP-bar drain animation.** On any HP *drop* (combat hit or narrative wound) the top
  status bar's HP bar blinks once — brightens over 3 frames, dims back over 2 — then eases
  down to the new value instead of snapping. Heals and the first paint still snap. One
  UI-thread state machine (`_start_hp_drain`/`_hp_tick`/`_stop_hp_anim`); idle = show real HP.
- **Smoother combat telegraph.** The combat-intro banner glows along an eased (sine)
  brightness ramp (`_build_intro_pulse`) instead of a hard bold↔dim strobe. Still always
  releases `combat_intro_ready`, so the worker can't hang.
- **Click an entity name → Inspect.** Entities we have an Inspect entry for render
  **underlined** in the narrative and carry a `@click` meta routing to `action_inspect`,
  which expands the Inspect card and highlights/shows that row. Flavor keywords (e.g. "blade")
  stay plain. `_blend()` helper backs both the HP blink and the telegraph easing.
- **Day/night lighting phase.** A photographic *white-balance* over the active theme: the
  palette warms a touch by in-game day, cools/dims by night — lighting changes, theme identity
  doesn't. Pure shared engine in `game/palette.tint_theme()` + `phase_for(time_label)`
  (multiplicative per-channel gain, so contrast/legibility hold). `_pal()` tints by phase;
  `_sync_phase()` recolours on time-bucket change. On by default (`UI_DAYNIGHT`); **F9** toggles.
- **`cyber` theme (neon-noir).** Fourth theme for sci-fi/cyberpunk: near-black indigo base,
  hot-magenta player + electric-blue interaction (warm), cyan/teal world (cool), neon-violet
  magic, hot-red alarm. Selectable in the Theme menu and as a boot theme.
- **Windows glyph hardening.** Emoji-capable icons (♥ ⏱ ⚔ ☀) carry **U+FE0E (VS15)** so
  terminals like Windows Terminal render them single-cell mono (themeable) instead of wide
  colour emoji that break alignment. Box/geometric glyphs need no selector.
- **High-refresh hook.** `UI_MAX_FPS` (config/.env, default 120) sets `TEXTUAL_FPS` *before*
  Textual imports (it bakes `screen.UPDATE_PERIOD = 1/MAX_FPS` at import). The smooth
  animations are now duration-based, sampled at `_ANIM_DT = 1/120`, so the look is stable at
  60 or 120. Drop `UI_MAX_FPS=60` for slow terminals / SSH.
- **Day/night on/off in Settings** (`driver._daynight_toggle`, persisted to `.env` as
  `UI_DAYNIGHT`; live via `ui.set_daynight`/`get_daynight`). F9 still toggles in-session.
- **Named time-of-day skips** (engine). `StateChanges.set_time_of_day` lets the narrator jump
  the clock forward to a named band ("wait until morning", "camp for the night") instead of
  being stuck with the fixed none/short/medium/long increments. `EngineState.set_time_to_label`.

*Fixed:* a day/night phase change that landed **mid-stream** used to rebuild the transcript
(`_rerender_all`) before the streaming block was retained in `_blocks`, erasing the response
and ending the turn early. Phase recolours now defer past an in-flight reveal (`_recolor_surface`
+ `_phase_dirty`). Clickable entities also got a hover highlight, **and** a real hand cursor:
on kitty/ghostty we drive the OS pointer shape per-span via kitty's OSC-22 protocol
(Textual's built-in `_set_pointer_shape`; its native pointer system is per-widget so it can't
tell an entity from prose — we flip it off the `@click` style under the cursor). Other
terminals keep their default pointer.

*Deferred per user: audio/music (only if it never pops a separate window); the visual map →
directional graph. Open: genuinely "bigger" glyphs need pixel-art (graphics protocol / image
renderable), not plain text — looking into `rich-pixels` as the lightweight route.*

---

### 🤖 Claude's wishlist (Stage 7 candidates — *my* picks, kept separate from the user's list)

*Small fixes / polish (low effort, found during the 2026-06 sweeps):*
- **Preserve Inspect selection across turns.** `set_context` rebuilds `#inspect-list` every
  turn (clear + repopulate), which resets the highlight/scroll. Diff instead, or only rebuild
  when the known-entity set actually changes.
- **Anchor asset paths to the repo root.** `prompts/`, `templates/`, `logs/` are resolved
  relative to the CWD, so the game only runs from the project root. Resolve them from
  `__file__` so `python3 /abs/path/game_tui.py` works from anywhere. (Pre-existing, not a
  regression.)
- **Clamp the status HP bar.** If `hp > max_hp` (a maxhp buff) `filled` exceeds 10 and the
  empty segment goes negative — guard it.
- **Honor the combat-HUD `layout` hint.** `show_combat_hud(..., layout="horizontal")` is
  ignored (always a vertical button stack); lay the action row out horizontally like pygame.
- **Menu/combat hotkeys.** Number keys (1–9) for menu items and `a`/`i`/`f` + `1`/`2`/`3` in
  the combat HUD, matching pygame muscle memory (parity gap noted in the port audit).

*UX / immersion:*
- **Theme-matched icon set** for sidebar/status/commands (see design note below); an animated
  day/night glyph that eases sun→moon as time passes.
- **A real map card** rendering the `location_graph` as box-drawing instead of the `/map`
  text dump; "you are here" highlighted.
- **Combat juice:** animate HP bars draining ✅ (built), flash the struck
  combatant's line, a compact damage ticker — all via `set_interval`, the same mechanism as
  the combat-intro flash. *(Smoother combat telegraph also built; screen-shake declined by user.)*
- **Settings:** a typewriter-speed slider + a "reduce motion / instant text" accessibility
  toggle (instant reveal, no flash).
- **Click an entity name** in the narrative to open it in the Inspect card — a mouse bridge
  that doesn't need true hover (cheaper than Milestone B, works in more terminals). ✅ built
  (underline marks inspectable spans).
- **Time-of-day ambient tint:** nudge the palette warmer at dawn / cooler at night (subtle,
  per-turn), reusing the theme system.

*Extensibility / architecture:*
- **Icon registry** in `palette.py` (`name → (glyph, role-key)`) — design note below.
- **Thin `game/audio.py`** + a music-player card — design note below; SFX hooks (combat hit,
  quest chime, page-turn) ride the same module.
- **Sidebar plugin seam:** register cards by name so new modules (music, map, clock) drop in
  without rewriting `compose()`.

*Go-crazy / stretch (no wrong answers):*
- Journal as **turnable pages**; an in-app preview of the `/export` book.
- A **codex / achievements** card; a "scars & defeats" ledger that survives across saves.
- Optional **CRT / scanline** visual mode (pure Textual CSS).
- Localizable command words.

---

### Design note — theme-matched icons (researched 2026-06)

Three tiers, ship the baseline and treat the rest as opt-in:

1. **Baseline (recommended) — a glyph registry, theme-matched for free.** We already use
   Unicode glyphs (`◎ ⏱ ☀ ☾ ❖ ⚔ ▤ ♥ ▦ ✎`). Put them in an `ICONS` table in `palette.py`
   (`name → (glyph, role-key)`); the renderer styles each glyph with `_hex(theme[role])`, so
   **icons recolour with the active theme automatically** — "theme-matching" falls out of
   styling the glyph, not the glyph itself. Animated icons = a `set_interval` cycling
   glyph/style on a `Static` (same as the spinner / intro flash). Works **everywhere**,
   including bare SSH and the `textual serve` browser.
2. **Richer pictographs — Nerd Fonts (opt-in, config flag).** ~3,600 extra single-codepoint
   glyphs (weather/sun/moon/scroll/map/note); still "text", so the same registry colours them.
   Cost: the player's terminal must use a Nerd Font — document it and keep the Unicode table as
   fallback.
3. **True raster/SVG art (fancy terminals only).** Terminal **image** protocols — Kitty
   Graphics Protocol (best; Kitty/Ghostty/WezTerm), iTerm2 inline images, Sixel (xterm et al.).
   Libraries: **`textual-image`** (Rich renderables + Textual widgets; auto-detects TGP/Sixel
   with a Unicode fallback) and **`rich-pixels`** (half-block pixel-art, no protocol needed —
   works anywhere but low-res). Caveats: Sixel in Textual is hacky and flickers on scroll, and
   protocol support is terminal-dependent and inconsistent under `textual serve`. So raster is
   a per-terminal enhancement, **never the only path**.

### Design note — shipping music / does it need a separate player? (researched 2026-06)

- **Terminals can't emit audio and Textual has no audio API**, so music is **out-of-band**: a
  background audio thread inside the app, controlled by a Textual widget.
- **Library:** a thin `game/audio.py` wrapper (`play/pause/stop/next/volume/loop`) over
  **`pygame.mixer`** (already a dependency for the legacy client; does mixing, looping, volume,
  mp3/ogg) — make it an *optional* import that degrades to silence if pygame isn't installed.
  Alternatives: `just_playback` (miniaudio, simple seek/volume) is the lightest real option;
  `playsound`/`simpleaudio` are too minimal (no pause/volume/loop). Ship a few CC0 loops under
  `assets/music/` (document licensing).
- **Separate player?** Not a separate *process* — `pygame.mixer` runs on a background thread in
  the same process. Yes a separate *UI*: a small **music-player card** (track + ▶/⏸/⏭ +
  volume) bound to `game/audio.py`; it's just another `Collapsible`, clickable once it's a
  widget. SFX (combat hit, quest chime) reuse the module via `play_sfx(name)` on a second mixer
  channel. So: **one thin audio module + one widget, no external app.**
- **Web caveat (Stage 8):** `textual serve` runs the app **server-side** and streams the
  *terminal* to the browser — audio from `pygame.mixer` plays on the **server's** speakers, not
  the visitor's. So packaged music is **local/desktop only**; gate `game/audio.py` off in web
  mode (the same env flag that locks Settings). Web audio would need a browser-side channel
  (e.g. a companion HTML5 `<audio>`), out of scope for the demo.

*Sources:* [textual-image](https://pypi.org/project/textual-image/) ·
[rich-pixels](https://github.com/Textualize/rich-pixels) ·
[Textual image-display discussion](https://github.com/Textualize/textual/discussions/1191) ·
[textual-musicplayer (pygame.mixer example)](https://github.com/bluematt/textual-musicplayer) ·
[Textual (serve / browser)](https://github.com/Textualize/textual)

---

Not scheduled — captured so the Stage 3–8 work doesn't paint us into a corner.

---

## Stage 8 — Web serving + protection (provider-agnostic) — FINAL, ships on finished product

Once it's a Textual app, the browser demo is essentially free:
```
textual serve "python game_tui.py"
```
The OpenAI key lives in the **server's** environment and never reaches the client.
Document these protections as portable building blocks (apply the subset the chosen host
needs):

1. **Hard budget cap** on the API key at the provider dashboard (the real backstop — a
   ceiling no bug or abuse can exceed). Use a dedicated low-limit key for the demo.
2. **Per-session turn cap.** Reuse `state.session_turn`; when it exceeds a limit, show a
   "demo limit reached" message and stop making model calls. Prevents one visitor from
   running up cost.
3. **Rate limiting / concurrency cap.** Limit simultaneous sessions and requests/min
   (reverse proxy like Caddy/nginx, the PaaS's limits, or a small middleware). Caps total
   burn and basic abuse.
4. **Access gate (optional).** A passphrase in the URL / simple basic-auth so only people
   you share the link with can play — keeps it off the open internet.
5. **Session isolation** from Stage 6 (`GAME_DATA_DIR` per connection) + periodic cleanup
   of old `sessions/<uuid>/` dirs.
6. **Lock the model/provider** server-side for the demo: disable the in-game
   provider/key Settings flow (`run_setup`, `settings_menu`) in web mode (env flag) so a
   visitor can't repoint the backend or see/change the key.
7. **TLS** in front (PaaS gives it; for VPS use Caddy/nginx; for tunnels cloudflared/ngrok
   provide HTTPS).

**Host options (decide at deploy):** PaaS (Railway/Render/Fly — easiest always-on URL) ·
self-host VPS behind Caddy/nginx · on-demand tunnel (run locally, expose via cloudflared
only while demoing — cheapest, no standing exposure). All use the same caps above.

---

## Critical files

- **New:** `prototype_textual.py` (Stage 1, throwaway) · `game/driver.py` (extracted
  driver) · `game/uikit.py` (`PAUSE_SENTINEL` + `GameUIProtocol`) · `game/palette.py`
  (shared colors/roles) · `game/tui.py` (`TextualGameUI` + `GameApp`) · `game_tui.py`
  (Textual entry) · `docs/PORTING_TEXTUAL.md` (the guide).
- **Modified:** `game_ui.py` (slim to pygame entry; driver moves out) · `game/ui.py`
  (consume shared palette/highlight helpers; re-export `PAUSE_SENTINEL`) · `game/logs.py`
  (`GAME_DATA_DIR`-rooted paths) · `main.py` (`--tui` selector) · `requirements`/`.env.example`
  (add `textual`; document `GAME_DATA_DIR`, demo caps).
- **Untouched:** `game/engine.py`, `game/game_logic.py`, `game/combat.py` (interface
  reused), `game/schema.py`, `game/stats.py`, `game/config.py`.

---

## Verification

- **Stage 1:** run `python prototype_textual.py`; confirm streamed text, blocking input,
  a menu choice, and clean quit (no hung worker). This validates the whole approach.
- **Stage 2:** after the refactor, run the **pygame** game end-to-end (new game, a few
  turns, a fight, save/load, quit) — must still work. Run `pytest tests/`.
- **Stages 3–5:** run `python game_tui.py` locally: new game, several turns with streaming
  + highlights, open a menu, trigger combat, inspect an entity in the sidebar, save/load,
  pause (Esc), quit. Compare against the pygame build for parity.
- **Stage 6:** launch two sessions with different `GAME_DATA_DIR`; confirm saves don't
  collide and neither sees the other's slots.
- **Stage 8:** `textual serve "python game_tui.py"`, open in a browser, verify: playable
  with no client-side key; turn cap triggers; Settings/provider flow disabled in web mode;
  key never appears client-side (check page/network). Confirm the provider budget cap is set.
- Throughout: keep `tests/` green; the `game/` package behavior must not change.
