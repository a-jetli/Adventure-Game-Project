"""Textual front-end for The Game.

`GameApp` is a `textual.App` that also implements `GameUIProtocol` (`game/uikit.py`),
so the toolkit-agnostic driver (`game/driver.py`) drives it exactly like the pygame
`GameUI` — the app IS the `ui` the driver talks to (the pygame `GameUI` does the same
double duty).

Threading model: the driver runs on its own worker thread and blocks on
`threading.Event` latches for input/menus/combat, the
same pattern as pygame. The ONE difference from pygame: Textual lets only its event
loop touch the screen, so every screen mutation from the worker is marshalled via
`call_from_thread` (wrapped in `_from_thread`). "Wrap, don't rewrite."

Look & feel: a custom Textual theme is generated from the shared `game/palette` so the
chrome (borders, panels, footer, selection) matches the narrative's accent colors.
Layout: a header band (title + live status), the narrative transcript in a titled
rounded panel on the left, an extensible widget column (sidebar host) on the right, and
one clean input box at the bottom. Menus/combat use a flat column of `Button`s in a
modal; the sidebar's Inspect card uses an `OptionList`.
"""

from __future__ import annotations

import math
import os
import threading
import traceback

from rich import box
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Collapsible, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from game import config, palette
from game import highlight
from game.uikit import PAUSE_SENTINEL


# Role → palette color-key, so a span's role resolves to the current theme's color.
_ROLE_KEY = {
    highlight.ROLE_NAME: "HIGHLIGHT_NAME",
    highlight.ROLE_LOCATION: "HIGHLIGHT_LOCATION",
    highlight.ROLE_ITEM: "HIGHLIGHT_ITEM",
    highlight.ROLE_DESCRIPTOR: "HIGHLIGHT_DESCRIPTOR",
    highlight.ROLE_NPC: "HIGHLIGHT_NPC",
    highlight.ROLE_DANGER: "HIGHLIGHT_DANGER",
    highlight.ROLE_MAGIC: "HIGHLIGHT_MAGIC",
    highlight.ROLE_TIME: "HIGHLIGHT_TIME",
    highlight.ROLE_INTERACT: "HIGHLIGHT_INTERACT",
    highlight.ROLE_DIRECTION: "HIGHLIGHT_DIRECTION",
    highlight.ROLE_NATURE: "HIGHLIGHT_NATURE",
}

# U+FE0E (VARIATION SELECTOR-15) forces *text* presentation: ♥ ⏱ ⚔ ☀ are emoji-capable
# codepoints, so terminals like Windows Terminal otherwise render them as wide, full-
# colour emoji — double-width (breaks alignment) and immune to our theme tint. Pinning
# them to text keeps them single-cell, monochrome and themeable. Rich already measures
# them as width-1, so this only nudges the *terminal* to agree. Geometric/box glyphs
# (◎ ▤ ▦ ✎ ◐ ◑ ❖ ☾ █ ░) have no emoji form and need no selector.
_VS = "\uFE0E"

# The slash-command crib shown in the right sidebar (first of several planned widgets).
_COMMANDS = [
    ("◎", "/explore"), ("▤", "/inventory"), ("♥" + _VS, "/hp"), ("⏱" + _VS, "/time"),
    ("◎", "/location"), ("▦", "/map"), ("✎", "/journal"), ("?", "/help"),
]

# day/night clock: time label -> (glyph, palette color key) for the World card.
_DAYNIGHT = {
    "early morning": ("◐", "HIGHLIGHT_TIME"),
    "morning":       ("☀" + _VS, "HIGHLIGHT_TIME"),
    "midday":        ("☀" + _VS, "HIGHLIGHT_TIME"),
    "afternoon":     ("☀" + _VS, "HIGHLIGHT_TIME"),
    "evening":       ("◑", "HIGHLIGHT_TIME"),
    "night":         ("☾", "HIGHLIGHT_LOCATION"),
    "deep night":    ("☾", "HIGHLIGHT_LOCATION"),
}


def _supports_pointer_shapes() -> bool:
    """True on terminals that implement kitty's OSC-22 mouse-pointer-shape protocol, so we
    can show a hand cursor over clickable entities. Kitty and Ghostty support it; others
    would silently ignore the escape, but we gate on the known families to stay tidy."""
    term = os.environ.get("TERM", "")
    return (bool(os.environ.get("KITTY_WINDOW_ID"))
            or "kitty" in term or "ghostty" in term
            or os.environ.get("TERM_PROGRAM", "") in ("ghostty", "kitty"))


def _hex(rgb) -> str:
    """(r,g,b[,a]) → '#rrggbb' (alpha dropped; terminals don't blend it)."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(c1, c2, t: float):
    """Linear blend c1→c2 by t∈[0,1] → (r,g,b). Used by the HP-drain blink and the
    combat telegraph to ease colors smoothly instead of hard on/off toggles."""
    t = max(0.0, min(1.0, t))
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def _theme_from_palette(name: str, d: dict) -> Theme:
    """Build a Textual `Theme` from one of our palette theme dicts, so the chrome
    (borders, panels, footer, cursors, selection) is drawn from the same colors as
    the narrative highlights — one cohesive look per theme."""
    return Theme(
        name=f"thegame-{name}",
        primary=_hex(d["HIGHLIGHT_LOCATION"]),     # cursors/links/selection emphasis
        secondary=_hex(d["HIGHLIGHT_NPC"]),
        accent=_hex(d["PROMPT_COLOR"]),            # gold signature: titles, footer keys
        foreground=_hex(d["TEXT_COLOR"]),
        background=_hex(d["INPUT_BG"]),            # deepest layer (behind panels)
        surface=_hex(d["BG_COLOR"]),               # panel fill (lifts off background)
        panel=_hex(d["MENU_PANEL_BG"]),
        success=_hex(d["HIGHLIGHT_ITEM"]),
        warning=_hex(d["HIGHLIGHT_TIME"]),
        error=_hex(d["HIGHLIGHT_DANGER"]),
        dark=(name != "light"),
        variables={
            "footer-key-foreground": _hex(d["PROMPT_COLOR"]),
            "footer-description-foreground": _hex(d["TEXT_COLOR"]),
            "block-cursor-background": _hex(d["PROMPT_COLOR"]),
            "block-cursor-foreground": _hex(d["BG_COLOR"]),
            "block-cursor-text-style": "bold",
            "input-selection-background": _hex(d["INPUT_SELECTION_BG"]) + " 55%",
            "scrollbar": _hex(d["MENU_BUTTON_HOVER"]),
            "border": _hex(d["MENU_PANEL_BORDER"]),
            # Clickable narrative entities carry an `@click` meta, which Textual treats as a
            # link. We leave the base link colour alone (entities keep their semantic colour
            # + our underline) and only style the *hovered* one — so passing the mouse over
            # an inspectable name lights it up as a brass chip: clear "this is clickable"
            # feedback. (The mouse-pointer SHAPE stays the terminal's I-beam — a TUI can't
            # portably change the OS cursor; the hover highlight is the affordance instead.)
            "link-background-hover": _hex(d["PROMPT_COLOR"]),
            "link-color-hover": _hex(d["BG_COLOR"]),
            "link-style-hover": "bold",
        },
    )


class _Reveal:
    """One block being typed out by the universal typewriter. `get_text()` returns the
    full target string (dynamic for the streaming-narrative block, whose text grows as
    deltas arrive); `render(s)` turns a revealed prefix into a Rich renderable. `ended`
    is True once the target is final (always True for static blocks); the item is `done`
    only once the whole *final* text has been revealed."""
    __slots__ = ("widget", "render", "get_text", "dynamic", "shown", "ended", "done")

    def __init__(self, widget, render, get_text, dynamic):
        self.widget = widget
        self.render = render
        self.get_text = get_text
        self.dynamic = dynamic
        self.shown = 0.0
        self.ended = not dynamic
        self.done = False


# ── modal for menus and the combat HUD (flat OptionList; same latch pattern) ─────

class ChoiceScreen(ModalScreen):
    """A blocking choice popup: optional status/body text above a flat list of
    options. Selecting an option (Enter or click) runs on the UI thread, so it
    stores the chosen value and releases the worker's latch directly, then
    dismisses. Esc returns '__back__' (the driver treats that as back/cancel)."""

    def __init__(self, title, subtitle, body, options, layout, status_lines, deliver):
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._body = body
        self._options = list(options)            # [(label, value)]
        self._status_lines = status_lines or []  # [(text, rgb|None)]
        self._deliver = deliver                  # callback(value) -> stores + sets latch

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            if self._subtitle:
                yield Static(self._subtitle, id="modal-subtitle")
            for text, rgb in self._status_lines:
                yield Static(Text(text, style=_hex(rgb) if rgb else ""), classes="modal-status")
            if self._body:
                yield Static(self._body, classes="modal-body")
            with Vertical(id="modal-options"):
                for i, (label, _v) in enumerate(self._options):
                    yield Button(label, id=f"opt-{i}")

    def on_mount(self) -> None:
        self.query_one("#modal-box").border_title = self._title
        first = self.query("#modal-options Button").first()
        if first:
            first.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._deliver(self._options[int(event.button.id.removeprefix("opt-"))][1])
        self.dismiss()

    def on_key(self, event) -> None:
        if event.key == "escape":            # Esc = back / cancel
            self._deliver("__back__")
            self.dismiss()
            event.stop()
            return
        # Arrow keys move the highlight between options (Enter/Space/click selects, via
        # Textual's Button). Up/Left = previous, Down/Right = next, wrapping.
        if event.key in ("up", "down", "left", "right"):
            buttons = list(self.query("#modal-options Button"))
            if not buttons:
                return
            try:
                idx = buttons.index(self.focused)
            except ValueError:
                idx = 0
            step = -1 if event.key in ("up", "left") else 1
            buttons[(idx + step) % len(buttons)].focus()
            event.stop()


# ── the app == the ui ───────────────────────────────────────────────────────────

class GameApp(App):
    ENABLE_COMMAND_PALETTE = False  # no Ctrl+P palette; keep the footer clean

    # Frame time for the smooth animations (HP drain, combat telegraph, typewriter).
    # We sample near our 120 FPS repaint cap (UI_MAX_FPS) so motion is fine-grained;
    # every timed animation is expressed as a *duration* and derives its frame count
    # from this, so the cap and the look stay in sync. At a 60 FPS cap the extra ticks
    # just coalesce — finer sampling never makes anything worse, only smoother.
    _ANIM_DT = 1 / 120

    # Typewriter pace — constant chars/sec across ALL prose (pygame used 120; slower
    # here for a calmer read). One knob to tune speed; `_REVEAL_INTERVAL` is just the
    # tick granularity (the per-tick char budget is derived, so CPS stays exact).
    TYPEWRITER_CPS = 120
    _REVEAL_INTERVAL = _ANIM_DT

    CSS = """
    Screen { layout: vertical; background: $background; }

    /* ── header band (title + live status) ───────────────────────────── */
    #appheader { height: auto; padding: 1 2 0 2; }
    #statusbar { width: 100%; color: $text-muted; }

    /* ── main body: story panel (left) + sidebar host (right) ────────── */
    #body { height: 1fr; padding: 1 2; }
    /* the bordered card; holds the scrolling transcript + a live stream region. */
    #story {
        width: 1fr; height: 1fr;
        border: round $surface-lighten-2; border-title-color: $accent; border-title-align: left;
        padding: 1 2; background: $surface;
    }
    /* the transcript is a column of block widgets (not a RichLog): the streaming
       block grows *in place* and stays put — no separate live region, no jump — and
       each block is individually addressable (foundation for clickable/animatable
       widgets later). */
    #transcript {
        width: 100%; height: 1fr; padding: 0; background: $surface;
        scrollbar-color: $surface-lighten-2; scrollbar-background: $surface;
    }
    .blk { width: 100%; height: auto; }
    .blk-narrative, .blk-player, .blk-panel { margin-bottom: 1; }
    /* the loading line stands a bit prouder than ordinary prose */
    .blk-loading { padding: 1 0; text-style: bold; }
    /* the combat-intro banner: full-width, centered, flashes then clears */
    .blk-combat-intro { width: 100%; height: auto; padding: 1 0; margin-bottom: 1; }
    /* sidebar host: no border of its own — it's just a column of cards. */
    #sidebar {
        width: 34; height: 1fr; margin-left: 2;
        background: transparent; padding: 0;
        scrollbar-color: $surface-lighten-2; scrollbar-background: $background;
    }
    /* each module is a borderless Collapsible card: clickable ▶/▼ header, lifts via a
       value step, separated by blank space (editorial "cards", not box-in-box). */
    #sidebar Collapsible {
        height: auto; width: 100%; margin-bottom: 1;
        background: $surface; border: none; padding: 0;
    }
    #sidebar CollapsibleTitle { color: $accent; text-style: bold; padding: 0 1; }
    #sidebar CollapsibleTitle:hover { color: $accent; background: $boost; }
    #sidebar CollapsibleTitle:focus { color: $accent; text-style: bold reverse; }
    #sidebar Collapsible Contents { padding: 1 2 0 2; }
    .card-sub { color: $text-muted; margin-bottom: 1; }
    .card-line { color: $text-muted; }
    .cmd { color: $text-muted; }
    /* inspect: a compact selectable list + a detail pane below it */
    #inspect-list {
        height: auto; max-height: 12; width: 100%;
        background: $surface; border: none; padding: 0;
        scrollbar-color: $surface-lighten-2; scrollbar-background: $surface;
    }
    #inspect-list:focus { border: none; }
    #inspect-list > .option-list--option-highlighted { background: $accent; color: $background; }
    #inspect-detail { color: $text-muted; padding-top: 1; }

    /* ── skip hint (shown only while text is typing out) + input + footer ── */
    #skip-hint { height: auto; padding: 0 3; color: $text-muted; text-style: italic; display: none; }
    #skip-hint.on { display: block; }
    #cmd {
        height: 3; margin: 0 2 1 2; border: round $surface-lighten-2;
        border-title-color: $accent; background: $surface;
    }
    #cmd:focus { border: round $accent; }

    /* ── modal (menus + combat HUD) ──────────────────────────────────── */
    ChoiceScreen { align: center middle; background: $background 70%; }
    #modal-box {
        width: 60; max-width: 80%; height: auto; max-height: 90%;
        border: round $accent; border-title-color: $accent; border-title-align: center;
        background: $panel; padding: 1 2;
    }
    #modal-subtitle { width: 100%; text-align: center; color: $text-muted; padding-bottom: 1; }
    .modal-status { width: 100%; }
    .modal-body { padding: 1 0; color: $foreground; }
    #modal-options { height: auto; width: 100%; padding-top: 1; }
    #modal-options Button {
        width: 100%; height: 1; margin-bottom: 1; border: none;
        background: $boost; color: $foreground; text-align: center;
    }
    #modal-options Button:focus { background: $accent; color: $background; text-style: bold; }
    #modal-options Button:hover { background: $accent 25%; color: $foreground; }
    """

    # priority=True so Quit fires even when a modal (e.g. the opening menu) has focus.
    # Only Ctrl+Q is ours (priority so it fires over modals). We deliberately do NOT
    # bind Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+K / Ctrl+Backspace — Textual's Input already
    # uses those for copy / cut / paste / delete-to-end / delete-word, and stealing them
    # both broke editing and made Ctrl+K misbehave. Skip-reveal is "press any key".
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", key_display="Ctrl+Q", priority=True),
        Binding("f9", "toggle_daynight", "Day/Night", show=False),
    ]

    def __init__(self, worker=None, theme_name: str | None = None):
        super().__init__()
        # The driver runs here; tests pass a fake worker to exercise the bridge
        # without an LLM. Default is the real game driver.
        if worker is None:
            from game.driver import game_thread
            worker = game_thread
        self._worker = worker
        self._theme_name = theme_name or getattr(config, "UI_THEME", "dark") or "dark"
        if self._theme_name not in palette.THEMES:
            self._theme_name = "dark"

        # ── bridge state (mirrors pygame GameUI) ───────────────────────────────
        self.running = True
        self.input_ready = threading.Event()
        self.menu_ready = threading.Event()
        self.combat_ready = threading.Event()
        self.combat_intro_ready = threading.Event()
        self.pending_input = ""
        self.menu_choice = ""
        self.combat_choice = ""
        self.awaiting_input = False
        self._allow_empty = False   # honored by on_input_submitted (mirrors pygame)
        self._exiting = False
        self._worker_thread: threading.Thread | None = None

        # ── context for highlighting / status (plain data, read directly) ──────
        self.player_name = ""
        self.known_locations: list[str] = []
        self.known_items: list[str] = []
        self.known_descriptors: list[str] = []
        self.known_npcs: list[str] = []
        self.entity_info: dict[str, str] = {}
        self._status: dict | None = None
        # ── day/night lighting: warm the whole palette a touch by in-game day, cool it
        #    by night (a photographic white-balance over the active theme, computed in
        #    game/palette). `_phase` is the (temp, bright) currently applied; neutral
        #    until a time label arrives, so the flat theme shows verbatim at startup.
        self._daynight = bool(getattr(config, "UI_DAYNIGHT", True))
        self._phase: tuple[float, float] = palette.NEUTRAL_PHASE
        self._phase_dirty = False   # a phase change is waiting for the reveal to go idle
        # Mouse-pointer affordance: on kitty/ghostty we flip the OS pointer to a hand while
        # it's over a clickable entity, so there's real "this is clickable" feedback beyond
        # the underline. Other terminals keep their default (I-beam) — out of our control.
        self._pointer_shapes = _supports_pointer_shapes() and hasattr(self, "_set_pointer_shape")
        self._pointer_clickable = False
        self._inspect_map: dict[str, str] = {}      # OptionList id -> detail text
        self._inspect_by_name: dict[str, str] = {}  # lower name -> OptionList id
        self._inspect_index: dict[str, str] = {}    # OptionList id -> list position
        # ── HP-bar drain: on damage the bar blinks once (brightens then dims) and
        #    then eases down to the new value, instead of snapping. State machine
        #    driven by one UI-thread timer; idle (timer None) means show the real HP.
        self._hp_timer = None
        self._hp_shown_pct: float | None = None     # displayed % while animating
        self._hp_blink = 0.0                         # 0..1 brightness of the blink
        self._hp_blink_seq: list[float] = []
        self._hp_phase: str | None = None            # "blink" | "drain" | None
        self._hp_drain_step = 0.0

        # ── transcript model: retained blocks so a theme switch can re-render ───
        self._blocks: list[tuple] = []
        self._spinner: Static | None = None        # transient animated "thinking" block
        self._spinner_timer = None
        self._spinner_i = 0
        # ── universal typewriter: ALL new prose (narrative/system/combat) reveals at a
        #    constant chars-per-second, one block at a time (earliest first) — mirrors
        #    the pygame UI (`game/ui.py` typewriter_speed). Player echo, panels and the
        #    spinner are instant. A single UI-thread timer drains a reveal queue, so the
        #    pace is identical whether text was streamed or arrived whole. ───────────
        self._reveal_queue: list[_Reveal] = []
        self._reveal_timer = None
        self._reveal_idle = threading.Event()
        self._reveal_idle.set()
        # streaming-narrative scratch (a dynamic reveal item whose text grows live)
        self._live = ""
        self._tw_final: str | None = None
        self._tw_area_intro = False
        self._tw_ending = False
        self._stream_item: _Reveal | None = None
        # ── combat-intro flash: a transient banner that blinks N× then clears, pacing
        #    the worker via `combat_intro_ready` (mirrors the pygame overlay). ─────────
        self._combat_intro_widget: Static | None = None
        self._combat_intro_timer = None
        self._combat_intro_title = ""
        self._combat_intro_seq: list[float] = []   # eased brightness ramp (smooth pulse)

    # ── layout ───────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Vertical(id="appheader"):
            yield Static(id="app-title")
            yield Static(id="statusbar")
        with Horizontal(id="body"):
            with Vertical(id="story"):
                yield VerticalScroll(id="transcript")
            with VerticalScroll(id="sidebar"):
                # Each module is a Collapsible (clickable ▶/▼ header) so it minimizes —
                # and stays a discrete widget (foundation for clickable/animated cards).
                with Collapsible(title="World", collapsed=False, id="card-world"):
                    yield Static("—", id="side-location", classes="card-sub")
                with Collapsible(title="Inspect", collapsed=False, id="card-inspect"):
                    yield OptionList(id="inspect-list")
                    yield Static("Select a name to inspect.", id="inspect-detail",
                                 classes="card-line")
                with Collapsible(title="Journal", collapsed=False, id="card-journal"):
                    yield Static("No active quests.", id="side-journal", classes="card-line")
                with Collapsible(title="Commands", collapsed=True, id="card-commands"):
                    for glyph, name in _COMMANDS:
                        yield Static(f"{glyph}  {name}", classes="cmd")
        yield Static("", id="skip-hint")
        yield Input(placeholder="What do you do?", id="cmd")
        yield Footer()

    def on_mount(self) -> None:
        # Register a Textual theme per palette theme; apply the configured one.
        for name, d in palette.THEMES.items():
            self.register_theme(_theme_from_palette(name, d))
        self.theme = f"thegame-{self._theme_name}"

        self.query_one("#story").border_title = "Story"
        self.query_one("#cmd", Input).border_title = ">>"
        theme = self._pal()
        title = Text("placeholder name", style="bold " + _hex(theme["PROMPT_COLOR"]))
        self.query_one("#app-title", Static).update(title)
        self._update_statusbar()
        # Start the driver on its own thread — the analog of safe_game_thread in
        # game_ui.main(). Loops while the driver returns "menu" (Save & main menu).
        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()

    def _run_worker(self) -> None:
        try:
            while self.running and self._worker(self) == "menu":
                pass
        except Exception:
            traceback.print_exc()
            self.running = False
            self._release_all_waiters()
        # Driver finished (quit) — close the app from the worker side.
        self._from_thread(self._quit_app)

    def _pal(self) -> dict:
        base = palette.THEMES.get(self._theme_name, palette.THEMES["dark"])
        # Apply the day/night lighting. At the neutral phase tint_theme is an exact
        # copy, but we skip it then so the common, un-tinted path stays allocation-free.
        if self._daynight and self._phase != palette.NEUTRAL_PHASE:
            return palette.tint_theme(base, *self._phase)
        return base

    def _refresh_chrome(self) -> None:
        """Re-register the active Textual theme from the *tinted* palette and force a CSS
        refresh, so the chrome (panel borders, footer, cursors, selection) follows the
        day/night lighting too — not just the narrative content. Cheap: it rebuilds one
        Theme and re-resolves CSS variables; called only when the phase/theme changes."""
        self.register_theme(_theme_from_palette(self._theme_name, self._pal()))
        self._invalidate_css()
        self.refresh_css(animate=False)

    # ── thread-safe marshalling ────────────────────────────────────────────────
    def _from_thread(self, fn, *args) -> None:
        """call_from_thread, tolerant of a tearing-down app so the worker never
        crashes mid-draw on quit."""
        # NB: compare the underlying function, not the bound method — `self._quit_app`
        # makes a *new* bound-method object on every access, so `fn is self._quit_app`
        # is always False. (That bug let a teardown swallow the final quit marshal, so
        # typed /quit & /exit showed the save line but never called self.exit().)
        if not self.running and getattr(fn, "__func__", None) is not GameApp._quit_app:
            return
        try:
            self.call_from_thread(fn, *args)
        except Exception:
            pass

    # ── highlighting / block rendering ─────────────────────────────────────────
    def _render(self, text: str, *, area_intro: bool = False) -> Text:
        """Build a Rich Text with role spans colored from the current theme — the
        Textual analog of pygame's _build_highlights, off the shared spans."""
        theme = self._pal()
        base = _hex(theme["AREA_INTRO_COLOR"]) if area_intro else ""
        rt = Text(text, style=base)
        claimed: set[int] = set()
        for start, end, role, key in highlight.compute_highlight_spans(
            text, player_name=self.player_name, locations=self.known_locations,
            items=self.known_items, descriptors=self.known_descriptors, npcs=self.known_npcs,
        ):
            if start in claimed:  # first span to claim a position wins (pygame precedence)
                continue
            color = _hex(theme[_ROLE_KEY[role]])
            # An entity we have an Inspect entry for becomes clickable: underline marks it
            # as interactive, and the @click meta routes a click to action_inspect, which
            # opens it in the sidebar's Inspect card. Flavor highlights (keywords,
            # descriptors) carry no key and stay plain colored text.
            if key and key in self.entity_info:
                rt.stylize(Style(color=color, underline=True,
                                 meta={"@click": f"app.inspect({key!r})"}), start, end)
            else:
                rt.stylize(color, start, end)
            claimed.update(range(start, end))
        return rt

    def _block_renderable(self, b: tuple):
        theme = self._pal()
        kind = b[0]
        if kind == "narrative":
            return self._render(b[1], area_intro=b[2])
        if kind == "player":
            return Text(f"> {b[1]}", style=_hex(theme["PROMPT_COLOR"]))
        if kind == "system":
            return Text(b[1], style=_hex(theme["SYSTEM_COLOR"]))
        if kind == "combat":
            return Text(b[1], style=_hex(theme["HIGHLIGHT_COMBAT"]))
        if kind == "panel":
            # box.SIMPLE = horizontal rules only (no vertical/corner glyphs), so the
            # inline card flows with the prose and avoids Terminal.app's border-gap
            # artifacts on long lines.
            return Panel(b[2], title=b[1], border_style=_hex(theme["HIGHLIGHT_INTERACT"]),
                         title_align="left", box=box.SIMPLE, padding=(0, 1))
        return Text(str(b))

    def _block_widget(self, b: tuple) -> Static:
        return Static(self._block_renderable(b), classes=f"blk blk-{b[0]}")

    def _revealable_text(self, b: tuple) -> str:
        """The string a block types out (player echo carries its '> ' prefix)."""
        return f"> {b[1]}" if b[0] == "player" else b[1]

    def _partial_renderer(self, b: tuple):
        """Return f(revealed_prefix) -> renderable, styled per block kind. Theme is
        captured now; a mid-reveal theme switch is rare and self-corrects on commit."""
        theme = self._pal()
        kind = b[0]
        if kind == "narrative":
            area = b[2]
            return lambda s: self._render(s, area_intro=area)
        if kind == "player":
            return lambda s: Text(s, style=_hex(theme["PROMPT_COLOR"]))
        if kind == "combat":
            return lambda s: Text(s, style=_hex(theme["HIGHLIGHT_COMBAT"]))
        return lambda s: Text(s, style=_hex(theme["SYSTEM_COLOR"]))  # system

    def _transcript(self) -> VerticalScroll:
        return self.query_one("#transcript", VerticalScroll)

    def _scroll_end(self) -> None:
        self._transcript().scroll_end(animate=False)

    def _rerender_all(self) -> None:
        # A theme switch repaints everything fully revealed (no re-animation).
        self._reveal_queue.clear()
        if self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer = None
        self._reveal_idle.set()
        t = self._transcript()
        t.remove_children()
        for b in self._blocks:
            t.mount(self._block_widget(b))
        self._scroll_end()

    # ── block emission ──────────────────────────────────────────────────────────
    def _emit_instant(self, b: tuple) -> None:
        self._blocks.append(b)
        self._from_thread(self._mount_instant, b)

    def _mount_instant(self, b: tuple) -> None:
        self._transcript().mount(self._block_widget(b))
        self._scroll_end()

    def _emit_animated(self, b: tuple) -> None:
        self._blocks.append(b)
        self._from_thread(self._mount_animated, b)

    def _mount_animated(self, b: tuple) -> None:
        self._clear_spinner()
        w = Static("", classes=f"blk blk-{b[0]}")
        self._transcript().mount(w)
        text = self._revealable_text(b)
        self._enqueue_reveal(w, self._partial_renderer(b), lambda: text, dynamic=False)
        self._scroll_end()

    # ── the universal reveal queue (one UI-thread timer, constant CPS) ───────────
    def _enqueue_reveal(self, widget, render, get_text, dynamic) -> _Reveal:
        item = _Reveal(widget, render, get_text, dynamic)
        self._reveal_queue.append(item)
        self._reveal_idle.clear()
        self._set_skip_hint(True)
        if self._reveal_timer is None:
            self._reveal_timer = self.set_interval(self._REVEAL_INTERVAL, self._reveal_tick)
        return item

    def _reveal_tick(self) -> None:
        item = next((it for it in self._reveal_queue if not it.done), None)
        if item is None:                      # queue drained → idle, stop ticking
            self._reveal_queue.clear()
            if self._reveal_timer is not None:
                self._reveal_timer.stop()
                self._reveal_timer = None
            self._set_skip_hint(False)
            self._reveal_idle.set()
            # A day/night phase change that landed mid-reveal was deferred (so it couldn't
            # erase the streaming block) — apply the scrollback recolour now that we're idle.
            if self._phase_dirty:
                self._phase_dirty = False
                self._rerender_all()
            return
        full = item.get_text()
        n = len(full)
        item.shown = min(n, item.shown + self.TYPEWRITER_CPS * self._REVEAL_INTERVAL)
        item.widget.update(item.render(full[:int(item.shown)]))
        self._scroll_end()
        # done only when the *final* text is fully shown (dynamic items wait for `ended`)
        if int(item.shown) >= n and item.ended:
            item.widget.update(item.render(full))
            item.done = True

    def _reveal_all(self) -> None:
        """Snap every queued block to its full current text — the skip action. Dynamic
        (streaming) items that haven't ended yet show all received text and finalize
        once `ended`."""
        for it in self._reveal_queue:
            if it.done:
                continue
            full = it.get_text()
            it.shown = len(full)
            it.widget.update(it.render(full))
            if it.ended:
                it.done = True
        self._scroll_end()

    def _set_skip_hint(self, on: bool) -> None:
        # Grey indicator just below the story area: tells the user any key skips.
        try:
            hint = self.query_one("#skip-hint", Static)
        except Exception:
            return
        if on:
            hint.update("press any key to skip…")
            hint.add_class("on")
        else:
            hint.remove_class("on")
            hint.update("")

    # ── GameUIProtocol: context / status ───────────────────────────────────────
    def set_context(self, player_name, locations, items, npcs=None, info=None) -> None:
        self.player_name = player_name
        self.known_locations = locations
        self.known_items = items
        self.known_descriptors = highlight.extract_location_descriptors(locations)
        self.known_npcs = npcs or []
        self.entity_info = {k.lower(): v for k, v in (info or {}).items()}
        self._from_thread(self._refresh_inspect)

    def set_status(self, hp, max_hp, location, time_label, weapon, armor) -> None:
        prev = self._status
        self._status = dict(hp=hp, max_hp=max_hp, location=location,
                            time_label=time_label, weapon=weapon, armor=armor)
        # Animate the bar only when HP actually drops (combat hit, narrative wound);
        # heals and the first paint just snap. `from_pct` is the old fill % to ease from.
        from_pct = None
        if prev and prev.get("max_hp") and max_hp:
            old = 100 * prev["hp"] / prev["max_hp"]
            new = 100 * hp / max_hp
            if new < old - 0.01:
                from_pct = old
        self._from_thread(self._apply_status, from_pct)

    def _apply_status(self, from_pct) -> None:
        self._sync_phase()                 # day/night lighting follows the time label
        if from_pct is not None:
            self._start_hp_drain(from_pct)
        else:
            self._stop_hp_anim()
            self._update_statusbar()

    # ── day/night lighting phase ────────────────────────────────────────────────
    def _sync_phase(self) -> None:
        """Pull the lighting phase from the current time label; if the bucket actually
        changed, recolour the whole reading surface (retained narrative + inspect) to
        the new 'lighting'. The status bar / world card are repainted by the caller."""
        s = self._status
        label = s["time_label"] if s else ""
        target = palette.phase_for(label) if self._daynight else palette.NEUTRAL_PHASE
        if target == self._phase:
            return
        self._phase = target
        self._refresh_chrome()       # tint the panel borders/footer to match
        self._recolor_surface()

    def _recolor_surface(self) -> None:
        """Recolour retained narrative + inspect to the current lighting — but NEVER while
        a reveal/stream is mid-flight. `_rerender_all` rebuilds the transcript from
        `self._blocks`, and a streaming narrative isn't in `_blocks` until it ends, so a
        rebuild then would drop the live widget and erase the response. The driver pushes
        status (→ phase) *before* it finalises the stream, so this guard matters. When busy
        we defer to the next idle; the live text already types out in the new palette."""
        self._refresh_inspect()
        if self._reveal_idle.is_set():
            self._phase_dirty = False
            self._rerender_all()
        else:
            self._phase_dirty = True

    def action_toggle_daynight(self) -> None:
        """Toggle the day/night lighting (handy for A/B-ing the effect)."""
        self._apply_daynight(not self._daynight)
        self.notify(f"Day/night lighting {'on' if self._daynight else 'off'}")

    def _apply_daynight(self, enabled: bool) -> None:
        self._daynight = enabled
        s = self._status
        self._phase = (palette.phase_for(s["time_label"])
                       if enabled and s else palette.NEUTRAL_PHASE)
        self._refresh_chrome()
        self._recolor_surface()
        self._update_statusbar()

    # ── HP-bar drain animation (blink once, then ease down) ─────────────────────
    # Wall-clock durations; the frame counts derive from `_ANIM_DT`, so the look is the
    # same at 60 or 120 FPS — higher just samples the curves more finely. (Originally
    # specced as "brighter over 3 frames, dim over 2" at ~22 FPS; kept the same feel.)
    _HP_BLINK_UP = 0.13      # seconds brightening to the peak
    _HP_BLINK_DOWN = 0.09    # seconds dimming back to none
    _HP_DRAIN_SECS = 0.26    # seconds to ease the whole drop down

    @classmethod
    def _build_blink_ramp(cls) -> list[float]:
        """Eased 0→1→0 brightness ramp for the pre-drain blink, sampled at `_ANIM_DT`."""
        nu = max(1, round(cls._HP_BLINK_UP / cls._ANIM_DT))
        nd = max(1, round(cls._HP_BLINK_DOWN / cls._ANIM_DT))
        up = [math.sin((math.pi / 2) * (i + 1) / nu) for i in range(nu)]    # ease → 1
        down = [math.cos((math.pi / 2) * (i + 1) / nd) for i in range(nd)]  # ease 1 → 0
        return up + down

    def _start_hp_drain(self, from_pct: float) -> None:
        self._hp_shown_pct = from_pct
        self._hp_blink_seq = self._build_blink_ramp()   # quick blink before the drain
        self._hp_blink = 0.0
        self._hp_phase = "blink"
        self._hp_drain_step = 0.0
        if self._hp_timer is None:
            self._hp_timer = self.set_interval(self._ANIM_DT, self._hp_tick)
        self._update_statusbar()   # show the full old bar immediately, pre-blink

    def _hp_tick(self) -> None:
        s = self._status
        if not s or not s["max_hp"] or self._hp_shown_pct is None:
            self._stop_hp_anim()
            return
        target = 100 * s["hp"] / s["max_hp"]
        if self._hp_phase == "blink":
            if self._hp_blink_seq:
                self._hp_blink = self._hp_blink_seq.pop(0)
            else:
                self._hp_blink = 0.0
                self._hp_phase = "drain"
                # ease the whole drop over ~_HP_DRAIN_SECS (min step so tiny hits move)
                self._hp_drain_step = max(
                    0.6, (self._hp_shown_pct - target) * self._ANIM_DT / self._HP_DRAIN_SECS)
        elif self._hp_phase == "drain":
            if self._hp_shown_pct - target <= self._hp_drain_step:
                self._hp_shown_pct = target
                self._update_statusbar()
                self._stop_hp_anim()
                return
            self._hp_shown_pct -= self._hp_drain_step
        self._update_statusbar()

    def _stop_hp_anim(self) -> None:
        if self._hp_timer is not None:
            self._hp_timer.stop()
            self._hp_timer = None
        self._hp_shown_pct = None
        self._hp_blink = 0.0
        self._hp_phase = None

    def _update_statusbar(self) -> None:
        s = self._status
        if not s:
            return
        theme = self._pal()
        real_pct = int(100 * s["hp"] / s["max_hp"]) if s["max_hp"] else 0
        # While draining, show the animated value (and a blink brightening the fill).
        disp_pct = int(round(self._hp_shown_pct)) if self._hp_shown_pct is not None else real_pct
        disp_pct = max(0, min(100, disp_pct))
        filled = round(disp_pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        fill = theme["STATUS_HP_FILL"]
        if self._hp_blink > 0:
            fill = _blend(fill, (255, 255, 255), self._hp_blink)
        t = Text()
        if self.player_name:
            t.append(self.player_name, style="bold " + _hex(theme["HIGHLIGHT_NAME"]))
            t.append("   ")
        t.append("HP ", style=_hex(theme["STATUS_LABEL_COLOR"]))
        t.append(f"[{bar}] {disp_pct}%", style=_hex(fill))
        t.append("    ◎ ", style=_hex(theme["STATUS_LABEL_COLOR"]))
        t.append(f"{s['location']}", style=_hex(theme["HIGHLIGHT_LOCATION"]))
        t.append("    ⏱ ", style=_hex(theme["STATUS_LABEL_COLOR"]))
        t.append(f"{s['time_label']}", style=_hex(theme["HIGHLIGHT_TIME"]))
        t.append("    ⚔ ", style=_hex(theme["STATUS_LABEL_COLOR"]))
        t.append(f"{s['weapon']} / {s['armor']}", style=_hex(theme["STATUS_VALUE_COLOR"]))
        self.query_one("#statusbar", Static).update(t)
        # World card: place + a small day/night clock (glyph follows the time label).
        glyph, gkey = _DAYNIGHT.get(s["time_label"], ("⏱", "HIGHLIGHT_TIME"))
        loc = Text()
        loc.append(f"◎ {s['location']}\n", style=_hex(theme["SYSTEM_COLOR"]))
        loc.append(f"{glyph} ", style=_hex(theme[gkey]))
        loc.append(s["time_label"], style=_hex(theme["HIGHLIGHT_TIME"]))
        self.query_one("#side-location", Static).update(loc)

    # ── GameUIProtocol: inspect sidebar (Stage 5A) ──────────────────────────────
    def _refresh_inspect(self) -> None:
        """Rebuild the Inspect list from the highlight context: people, places, items.
        Each row carries the same detail text as the hover map; selecting one shows it
        in the detail pane below. Robust everywhere (works over SSH and in-browser)."""
        try:
            ol = self.query_one("#inspect-list", OptionList)
        except Exception:
            return
        ol.clear_options()
        self._inspect_map.clear()
        self._inspect_by_name.clear()
        self._inspect_index.clear()
        theme = self._pal()
        n = 0
        pos = 0  # running list position (counts disabled headers too, for click→highlight)

        def add(option) -> int:
            nonlocal pos
            ol.add_option(option)
            here = pos
            pos += 1
            return here

        def section(label: str, names: list[str], role_key: str) -> None:
            nonlocal n
            seen = set()
            rows = []
            for name in names:
                if not name or name.lower() in seen:
                    continue
                seen.add(name.lower())
                detail = self.entity_info.get(name.lower())
                if not detail:
                    continue
                rows.append((name, detail))
            if not rows:
                return
            add(Option(Text(label, style="bold " + _hex(theme["PROMPT_COLOR"])),
                       disabled=True))
            for name, detail in rows:
                oid = f"insp-{n}"
                self._inspect_map[oid] = detail
                self._inspect_by_name[name.lower()] = oid
                self._inspect_index[oid] = add(
                    Option(Text(f"  {name}", style=_hex(theme[role_key])), id=oid))
                n += 1

        people = ([self.player_name] if self.player_name else []) + list(self.known_npcs)
        section("People", people, "HIGHLIGHT_NPC")
        section("Places", list(self.known_locations), "HIGHLIGHT_LOCATION")
        section("Items", list(self.known_items), "HIGHLIGHT_ITEM")
        if n == 0:
            add(Option(Text("Nothing known yet.",
                            style=_hex(theme["SYSTEM_COLOR"])), disabled=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        detail = self._inspect_map.get(event.option.id or "")
        if detail is None:
            return
        theme = self._pal()
        self.query_one("#inspect-detail", Static).update(
            Text(detail, style=_hex(theme["SYSTEM_COLOR"])))

    def action_inspect(self, name: str) -> None:
        """Clicking an underlined entity in the narrative opens it here: expand the
        Inspect card, highlight that row, and show its detail. (No-op for a name we
        have no Inspect entry for — the span wouldn't have been clickable anyway.)"""
        oid = self._inspect_by_name.get((name or "").lower())
        if not oid:
            return
        try:
            card = self.query_one("#card-inspect", Collapsible)
            ol = self.query_one("#inspect-list", OptionList)
            detail_pane = self.query_one("#inspect-detail", Static)
        except Exception:
            return
        card.collapsed = False
        idx = self._inspect_index.get(oid)
        if idx is not None:
            ol.highlighted = idx   # OptionList auto-scrolls the highlight into view
        detail = self._inspect_map.get(oid)
        if detail:
            detail_pane.update(Text(detail, style=_hex(self._pal()["SYSTEM_COLOR"])))

    # ── GameUIProtocol: journal card (Stage 5C) ─────────────────────────────────
    def set_quests(self, quests) -> None:
        # quests: list[(title, detail)] of the player's active objectives.
        self._from_thread(self._render_journal, list(quests))

    def _render_journal(self, quests) -> None:
        try:
            card = self.query_one("#side-journal", Static)
        except Exception:
            return
        theme = self._pal()
        if not quests:
            card.update(Text("No active quests.", style=_hex(theme["SYSTEM_COLOR"])))
            return
        t = Text()
        for i, (title, detail) in enumerate(quests):
            if i:
                t.append("\n")
            t.append(f"❖ {title}\n", style="bold " + _hex(theme["HIGHLIGHT_INTERACT"]))
            t.append(f"   {detail}", style=_hex(theme["SYSTEM_COLOR"]))
        card.update(t)

    # ── GameUIProtocol: transcript output ───────────────────────────────────────
    # Prose types out (narrative/system/combat); the player's own echo, info panels
    # and the spinner are instant — same split as the pygame UI.
    def add_narrative(self, text, area_intro=False, instant=False) -> None:
        # `instant` is used for the resume recap so the whole "catching up" block (welcome
        # lines + inventory panel + recap) appears at once instead of half-streaming.
        (self._emit_instant if instant else self._emit_animated)(("narrative", text, area_intro))

    def add_player_input(self, text) -> None:
        self._emit_instant(("player", text))

    def add_system(self, text, instant=False) -> None:
        (self._emit_instant if instant else self._emit_animated)(("system", text))

    def add_panel(self, title, body) -> None:
        self._emit_instant(("panel", title, body))   # bordered card: never streamed

    def add_combat_text(self, text, animate=True) -> None:
        (self._emit_animated if animate else self._emit_instant)(("combat", text))

    # ── GameUIProtocol: streaming narrative ─────────────────────────────────────
    # The streamed block is just a dynamic reveal item in the same queue: its target
    # text grows as deltas arrive, and the universal typewriter reveals it at the same
    # constant CPS as everything else (so streamed and non-streamed prose look alike).
    def begin_narrative_stream(self) -> None:
        self._live = ""
        self._tw_final = None
        self._tw_area_intro = False
        self._tw_ending = False
        self._from_thread(self._start_stream_reveal)

    def _start_stream_reveal(self) -> None:
        self._clear_spinner()
        w = Static("", classes="blk blk-narrative")
        self._transcript().mount(w)
        self._stream_item = self._enqueue_reveal(
            w,
            lambda s: self._render(s, area_intro=self._tw_area_intro if self._tw_ending else False),
            lambda: (self._tw_final if self._tw_ending else self._live),
            dynamic=True,
        )
        self._scroll_end()

    def append_narrative_stream(self, delta) -> None:
        # Worker thread: just grow the accumulator the reveal item reads.
        self._live += delta

    def end_narrative_stream(self, final_text, area_intro=False) -> None:
        # Retain for re-render; flag the dynamic item final so the typewriter can finish.
        self._blocks.append(("narrative", final_text, area_intro))
        self._tw_final = final_text
        self._tw_area_intro = area_intro
        self._tw_ending = True
        if self._stream_item is not None:
            self._stream_item.ended = True
            self._stream_item = None

    # ── GameUIProtocol: loading indicator ───────────────────────────────────────
    # A transient "thinking…" block; streaming (or stop_loading) removes it.
    def start_loading(self) -> None:
        self._from_thread(self._show_spinner)

    def stop_loading(self) -> None:
        self._from_thread(self._clear_spinner)

    # A rotating-orb spinner (visually larger than a braille dot), brass + bold, that
    # animates while the model thinks.
    _SPINNER_FRAMES = ["◐", "◓", "◑", "◒"]

    def _show_spinner(self) -> None:
        if self._spinner is None:
            self._spinner = Static("", classes="blk blk-loading")
            self._transcript().mount(self._spinner)
            self._spinner_i = 0
            self._spin()  # paint frame 0 immediately
            self._spinner_timer = self.set_interval(0.12, self._spin)
            self._scroll_end()

    def _spin(self) -> None:
        if self._spinner is None:
            return
        theme = self._pal()
        glyph = self._SPINNER_FRAMES[self._spinner_i % len(self._SPINNER_FRAMES)]
        dots = "." * (1 + (self._spinner_i // 2) % 3)
        self._spinner_i += 1
        t = Text()
        t.append(f"{glyph}  ", style="bold " + _hex(theme["PROMPT_COLOR"]))
        t.append(f"thinking{dots}", style=_hex(theme["SYSTEM_COLOR"]))
        self._spinner.update(t)

    def _clear_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        if self._spinner is not None:
            self._spinner.remove()
            self._spinner = None

    # ── GameUIProtocol: blocking input ──────────────────────────────────────────
    def get_input(self, prompt="", allow_empty=False) -> str:
        self.pending_input = ""
        self._allow_empty = allow_empty
        self.input_ready.clear()
        self.awaiting_input = True
        self._from_thread(self._focus_input)
        self.input_ready.wait()
        self.awaiting_input = False
        return self.pending_input if self.running else ""

    def _focus_input(self) -> None:
        self.query_one("#cmd", Input).focus()

    def show_menu(self, title, options, subtitle="", layout="vertical", body="") -> str:
        self.menu_choice = ""
        self.menu_ready.clear()
        self._from_thread(self.push_screen,
                          ChoiceScreen(title, subtitle, body, options, layout, None,
                                       self._deliver_menu))
        self.menu_ready.wait()
        return self.menu_choice if self.running else ""

    def _deliver_menu(self, value) -> None:
        self.menu_choice = value
        self.menu_ready.set()

    # ── GameUIProtocol: combat ──────────────────────────────────────────────────
    def begin_combat_intro(self, title, flashes=3, interval=0.12) -> None:
        # Flash a banner N× (toggle a Static via set_interval) and only release the
        # worker once the flashes finish, so `wait_for_combat_intro` paces the encounter
        # (the analog of the pygame combat-intro overlay).
        self.combat_intro_ready.clear()
        if not self.running:
            self.combat_intro_ready.set()
            return
        self._from_thread(self._start_combat_intro, title, max(1, flashes), interval)

    # Smooth telegraph: instead of a hard bold↔dim strobe, the banner glows up and back
    # down along an eased (sine) brightness ramp, so the intro reads as a pulse, not a
    # flicker. `_INTRO_FRAME` is the fine tick; `flashes` sets how many pulses. Each pulse
    # lasts ~`_INTRO_PULSE_SECS`; the frame count derives from the tick, so it samples
    # finely at 120 FPS and keeps the same length at 60.
    _INTRO_FRAME = _ANIM_DT
    _INTRO_PULSE_SECS = 0.62
    _INTRO_FRAMES_PER_PULSE = max(2, round(_INTRO_PULSE_SECS / _ANIM_DT))

    @classmethod
    def _build_intro_pulse(cls, flashes: int) -> list[float]:
        n = cls._INTRO_FRAMES_PER_PULSE
        seq: list[float] = []
        for _ in range(max(1, flashes)):
            seq.extend(math.sin(math.pi * i / (n - 1)) for i in range(n))
        return seq

    def _start_combat_intro(self, title, flashes, interval) -> None:
        # UI thread. Guarded so a render bug can never strand the worker on the latch.
        # `interval` is accepted for protocol parity but the smooth pulse paces itself.
        try:
            self._clear_spinner()
            self._combat_intro_title = title
            self._combat_intro_seq = self._build_intro_pulse(flashes)
            w = Static(self._combat_banner(title, 0.0), classes="blk blk-combat-intro")
            self._combat_intro_widget = w
            self._transcript().mount(w)
            self._scroll_end()
            self._combat_intro_timer = self.set_interval(self._INTRO_FRAME,
                                                         self._tick_combat_intro)
        except Exception:
            self._finish_combat_intro()

    def _tick_combat_intro(self) -> None:
        try:
            if not self._combat_intro_seq:
                self._finish_combat_intro()
                return
            b = self._combat_intro_seq.pop(0)
            w = self._combat_intro_widget
            if w is not None:
                w.update(self._combat_banner(self._combat_intro_title, b))
            if not self._combat_intro_seq:
                self._finish_combat_intro()
        except Exception:
            self._finish_combat_intro()

    def _finish_combat_intro(self) -> None:
        # Stop the pulse, drop the transient banner (the "═══ COMBAT ═══" log line from
        # run_combat_ui is the persistent header — same as the pygame overlay vanishing),
        # and ALWAYS release the latch so the worker can never hang on a render bug.
        if self._combat_intro_timer is not None:
            self._combat_intro_timer.stop()
            self._combat_intro_timer = None
        self._combat_intro_seq = []
        if self._combat_intro_widget is not None:
            self._combat_intro_widget.remove()
            self._combat_intro_widget = None
        self.combat_intro_ready.set()

    def _combat_banner(self, title: str, b: float) -> Text:
        # b∈[0,1] brightness: ease the danger color from a faint base up to a vivid peak.
        theme = self._pal()
        danger = theme["HIGHLIGHT_DANGER"]
        dim = _blend(danger, theme["BG_COLOR"], 0.65)
        bright = _blend(danger, (255, 255, 255), 0.30)
        style = _hex(_blend(dim, bright, b))
        if b > 0.55:
            style = "bold " + style
        return Text(f"⚔  {title}  ⚔", style=style, justify="center")

    def wait_for_combat_intro(self) -> None:
        if not self.running:
            return
        self.combat_intro_ready.wait(timeout=10)   # bounded: guards above always fire it

    def show_combat_hud(self, title, status_lines, options, layout="horizontal") -> str:
        self.combat_choice = ""
        self.combat_ready.clear()
        self._from_thread(self.push_screen,
                          ChoiceScreen(title, "", "", options, layout, status_lines,
                                       self._deliver_combat))
        self.combat_ready.wait()
        return "flee" if not self.running else self.combat_choice

    def _deliver_combat(self, value) -> None:
        self.combat_choice = value
        self.combat_ready.set()

    def wait_for_text_output(self) -> None:
        # Block until the reveal queue is fully drained (so combat text or a following
        # beat doesn't land on top of a still-typing block). Bounded so a missing
        # finalize can never hang the worker.
        if self.running:
            self._reveal_idle.wait(timeout=20)

    # ── GameUIProtocol: misc ────────────────────────────────────────────────────
    def clear(self) -> None:
        self._blocks.clear()
        self._spinner = None
        self._stream_item = None
        self._from_thread(self._clear_transcript)

    def _clear_transcript(self) -> None:
        self._reveal_queue.clear()
        if self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer = None
        if self._combat_intro_timer is not None:
            self._combat_intro_timer.stop()
            self._combat_intro_timer = None
        self._combat_intro_widget = None
        self._reveal_idle.set()
        self._transcript().remove_children()

    def rehighlight_all(self) -> None:
        self._from_thread(self._rerender_all)

    # ── theming (GameUIProtocol) ────────────────────────────────────────────────
    def set_theme(self, name: str) -> None:
        if name not in palette.THEMES:
            return
        self._theme_name = name
        self._from_thread(self._apply_theme_ui, name)

    def get_theme_name(self) -> str:
        return self._theme_name

    def set_daynight(self, enabled: bool) -> None:
        self._from_thread(self._apply_daynight, bool(enabled))

    def get_daynight(self) -> bool:
        return self._daynight

    def _apply_theme_ui(self, name: str) -> None:
        self.theme = f"thegame-{name}"        # swaps all chrome (borders/panels/footer)
        self._refresh_chrome()                # re-apply the day/night tint on the new theme
        th = self._pal()
        title = Text("placeholder name", style="bold " + _hex(th["PROMPT_COLOR"]))
        self.query_one("#app-title", Static).update(title)
        self._update_statusbar()
        self._rerender_all()                  # recolour narrative for the new theme

    def _release_all_waiters(self) -> None:
        self.input_ready.set()
        self.menu_ready.set()
        self.combat_ready.set()
        self.combat_intro_ready.set()

    # ── input / shutdown handlers (UI thread) ──────────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        # Typing any character while text is revealing skips the animation (the char
        # still lands in the box, so the player just keeps typing their command).
        if event.value and not self._reveal_idle.is_set():
            self._reveal_all()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.awaiting_input:
            return
        # Enter while text is still typing out = skip the reveal, not a (blank) submit.
        if not self._reveal_idle.is_set():
            self._reveal_all()
            if event.value == "":
                return
        # Strip ends (so " /help" still registers) and honor allow_empty: a blank line
        # is ignored on a normal turn (matches pygame) but submitted where the driver
        # asked for it (character-creation prompts pass allow_empty=True for defaults).
        value = event.value.strip()
        if not value and not self._allow_empty:
            event.input.value = ""
            return
        self.pending_input = value
        event.input.value = ""
        self.input_ready.set()

    def on_key(self, event) -> None:
        # Any key skips the typewriter while it's revealing (Enter/space/etc.). Printable
        # keys are consumed by the focused Input first (handled in on_input_changed); this
        # catches the rest (e.g. Escape — which skips here instead of opening Pause).
        if not self._reveal_idle.is_set():
            self._reveal_all()
            event.stop()
            return
        # Esc mid-play opens the pause menu (driver maps PAUSE_SENTINEL → pause_menu).
        if event.key == "escape" and self.awaiting_input:
            self.pending_input = PAUSE_SENTINEL
            self.input_ready.set()
            event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # Show a hand pointer over inspectable entities (spans carrying an `@click` meta).
        # Textual's own pointer system is per-widget, so it can't tell an entity from the
        # prose around it; we drive it per-character off the style under the cursor.
        if not self._pointer_shapes:
            return
        style = getattr(event, "style", None)
        clickable = bool(style and style.meta.get("@click"))
        if clickable != self._pointer_clickable:
            self._pointer_clickable = clickable
            try:
                self._set_pointer_shape("pointer" if clickable else "default")
            except Exception:
                self._pointer_shapes = False   # terminal balked — stop trying

    def on_unmount(self) -> None:
        # Don't leave a hand pointer behind on the way out.
        if self._pointer_shapes and self._pointer_clickable:
            try:
                self._set_pointer_shape("default")
            except Exception:
                pass

    def action_quit(self) -> None:
        self._quit_app()

    def _quit_app(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        self.running = False
        self._release_all_waiters()
        self.exit()
