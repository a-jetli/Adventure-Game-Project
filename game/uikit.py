"""Toolkit-agnostic UI contract shared by every front-end.

This module deliberately imports **no** UI toolkit (no pygame, no textual) so the
game driver (`game/driver.py`) and the Textual UI can both depend on it without
dragging pygame in. The pygame `GameUI` (`game/ui.py`) and the future
`TextualGameUI` (`game/tui.py`) each implement `GameUIProtocol`.

`PAUSE_SENTINEL` lives here (rather than in the pygame `game/ui.py`) for the same
reason — the driver compares against it every turn, and the Textual side must be
able to import it without importing pygame. `game/ui.py` re-exports it for
backward compatibility.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


# get_input() returns this when the player presses Esc mid-play; the driver opens
# the pause menu instead of quitting.
PAUSE_SENTINEL = "\x00pause"


@runtime_checkable
class GameUIProtocol(Protocol):
    """The ~40-call surface `game_thread` (the driver) invokes on its `ui` object.

    Both back-ends implement this; it is the port's checklist. Signatures mirror the
    pygame `GameUI` exactly so the driver is unchanged across front-ends. Methods
    that mutate the screen are expected to be safe to call from the worker thread
    (the Textual impl marshals them via `call_from_thread`; pygame draws directly).
    """

    # Lifecycle flag the worker polls; flipped False on app exit.
    running: bool

    # ── context / status ───────────────────────────────────────────────────────
    def set_context(self, player_name: str, locations: list[str], items: list[str],
                    npcs: list[str] | None = None,
                    info: dict[str, str] | None = None) -> None: ...

    def set_status(self, hp: int, max_hp: int, location: str, time_label: str,
                   weapon: str, armor: str) -> None: ...

    # Active objectives for the sidebar journal card: list of (title, detail).
    def set_quests(self, quests: list[tuple[str, str]]) -> None: ...

    # ── transcript output ──────────────────────────────────────────────────────
    def add_narrative(self, text: str, area_intro: bool = False, instant: bool = False) -> None: ...
    def add_player_input(self, text: str) -> None: ...
    def add_system(self, text: str, instant: bool = False) -> None: ...
    def add_panel(self, title: str, body: str) -> None: ...
    def add_combat_text(self, text: str, animate: bool = True) -> None: ...

    # ── streaming narrative ────────────────────────────────────────────────────
    def begin_narrative_stream(self) -> None: ...
    def append_narrative_stream(self, delta: str) -> None: ...
    def end_narrative_stream(self, final_text: str, area_intro: bool = False) -> None: ...

    # ── loading indicator ──────────────────────────────────────────────────────
    def start_loading(self) -> None: ...
    def stop_loading(self) -> None: ...

    # ── blocking input (latch pattern) ─────────────────────────────────────────
    def get_input(self, prompt: str = "", allow_empty: bool = False) -> str: ...
    def show_menu(self, title: str, options: list[tuple[str, str]], subtitle: str = "",
                  layout: str = "vertical", body: str = "") -> str: ...

    # ── combat ─────────────────────────────────────────────────────────────────
    def begin_combat_intro(self, title: str, flashes: int = 3,
                           interval: float = 0.12) -> None: ...
    def wait_for_combat_intro(self) -> None: ...
    def show_combat_hud(self, title: str,
                        status_lines: list[tuple[str, int | None]],
                        options: list[tuple[str, str]],
                        layout: str = "horizontal") -> str: ...
    def wait_for_text_output(self) -> None: ...

    # ── misc ───────────────────────────────────────────────────────────────────
    def clear(self) -> None: ...
    def rehighlight_all(self) -> None: ...
    def _release_all_waiters(self) -> None: ...

    # ── theming (each back-end applies a palette theme its own way) ────────────
    def set_theme(self, name: str) -> None: ...
    def get_theme_name(self) -> str: ...
    # Day/night lighting toggle (Textual tints the palette by in-game time; pygame no-ops).
    def set_daynight(self, enabled: bool) -> None: ...
    def get_daynight(self) -> bool: ...
