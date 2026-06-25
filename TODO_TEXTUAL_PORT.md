# TODO — Port "The Game" from pygame (GUI) to Textual (TUI) + web demo

> Working checklist for the Textual port. Source of truth for the eventual
> in-repo guide (`docs/PORTING_TEXTUAL.md`). Check off stages as they land.

## Progress

- [ ] **Stage 0** — Safety: verify functional, then back up to remote
- [ ] **Stage 1** — Prototype the threading bridge in isolation
- [ ] **Stage 2** — Refactor: separate UI-agnostic driver from pygame entry
- [ ] **Stage 3** — Build the Textual UI (`game/tui.py`) + entry (`game_tui.py`)
- [ ] **Stage 4** — Combat interface for Textual
- [ ] **Stage 5** — Entity detail (sidebar now, hover later)
- [ ] **Stage 6** — Per-session isolation for the web demo
- [ ] **Stage 7** — Web serving + protection (provider-agnostic)

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

2. **Back up to remote.** Working tree is currently dirty (modified `combat.py`,
   `engine.py`, `game_logic.py`, `ui.py`, etc.); `main` is level with `origin/main`. Capture
   the dirty state as the port's base **and** an immutable marker:
   ```
   git switch -c textual-port                 # carries WIP onto the feature branch
   git add -A
   git commit -m "Snapshot: functional pygame game before Textual port"
   git push -u origin textual-port            # remote backup #1 (working branch)
   git branch backup/pre-textual-port         # immutable marker at the same commit
   git push -u origin backup/pre-textual-port # remote backup #2 (never touched)
   ```
   Restore path if anything goes wrong: `git reset --hard backup/pre-textual-port`.
   All further work happens on `textual-port`.

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

---

## Stage 3 — Build the Textual UI (`game/tui.py`) + entry (`game_tui.py`)

New `game/tui.py` exposes `TextualGameUI` implementing `GameUIProtocol`, plus a `GameApp`
(the `textual.App`). New `game_tui.py` is the thin entry: build the app, start
`game_thread` as a threaded worker, run the app. `main.py` / a `--tui` flag can select it.

### Layout (Textual widgets / CSS)
- **Status bar** (top): HP bar + location + time + equipped weapon/armor. Maps from
  `set_status` (`game/ui.py:331`). Use `ProgressBar` or a styled `Static` for HP.
- **Transcript** (center): a `RichLog` / scrollable `VerticalScroll` of narrative,
  player input, system lines, panels, and combat text — the analog of the `blocks` list.
- **Inspect sidebar** (right, Milestone A): list of known entities; details pane below.
- **Input** (bottom): a Textual `Input`.
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

---

## Stage 4 — Combat interface for Textual

Add `TUICombatInterface(CombatInterface)` (mirror `GUICombatInterface`, `game_ui.py:662`)
implementing `show_intro / log / on_player_action_complete / choose_action /
choose_target / choose_item` against `TextualGameUI` (combat HUD = a modal/region using
the same latch pattern). `run_combat` (`game/combat.py:62`) and `run_combat_ui` are
reused unchanged.

---

## Stage 5 — Entity detail

- **Milestone A — Inspect sidebar (now).** Feed the sidebar from the existing
  `_entity_info_for_ui(state)` (`game_ui.py:108`) and `set_context`'s known lists. Render
  people/places/items as selectable rows (`OptionList`); selecting one shows its detail
  text. Robust everywhere, including SSH and the browser demo.
- **Milestone B — Word hover (later polish).** Textual *does* support cell-level mouse
  hover (works in desktop terminals and in-browser via `textual serve`, **not** bare SSH).
  Make each highlighted word a hoverable element with a tooltip from the same
  `entity_info` map. Fiddlier/more brittle, so it's a stretch goal after the core is
  stable.

---

## Stage 6 — Per-session isolation for the web demo

All save/log paths derive from one constant: `LOGS_DIR = "logs"` (`game/logs.py:14`).
`textual serve` runs **one process per browser connection**, so per-session isolation is
simple at the process level:

- Make the data root configurable: read `GAME_DATA_DIR` (env) and derive `LOGS_DIR`,
  `SAVES_DIR`, `BOOKS_DIR`, etc. from it (small change in `game/logs.py`; add a
  `set_data_dir()` or compute at import from env). Also covers `DEBUG_LOG = "logs/..."`
  (`game_ui.py:39`) — move under the same root.
- For the web demo, launch each session with a unique `GAME_DATA_DIR` (e.g.
  `sessions/<uuid>/`) so two visitors never collide and one can't read another's saves.
- Default (local desktop play) stays `./logs` — no behavior change.

---

## Stage 7 — Web serving + protection (provider-agnostic)

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
- **Stage 7:** `textual serve "python game_tui.py"`, open in a browser, verify: playable
  with no client-side key; turn cap triggers; Settings/provider flow disabled in web mode;
  key never appears client-side (check page/network). Confirm the provider budget cap is set.
- Throughout: keep `tests/` green; the `game/` package behavior must not change.
