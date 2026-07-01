"""Shared, toolkit-free color data for every front-end.

Lifted verbatim from the pygame UI (now `legacy/ui.py`) in the Textual port so both
back-ends consume one source of truth. This module imports **no** UI toolkit.

- pygame (`legacy/ui.py`) does `from game.palette import *` to get these as module
  globals, then `apply_theme()` swaps them (it keeps living in `legacy/ui.py` because
  it mutates that module's globals, which the render code reads at call time).
- Textual (`game/tui.py`) reads `THEMES[name]` directly and maps the role
  keys (`HIGHLIGHT_*`, `BG_COLOR`, …) to a Textual theme / CSS variables.

Color values are `(r, g, b)` or `(r, g, b, a)` tuples. `THEME_KEYS` lists the
themeable names; a theme is a dict of overrides applied over the dark defaults.
"""

# ── base surface ────────────────────────────────────────────────────────────
# Default theme is "dark" — a muted, editorial palette (per the design brief):
# quiet, grounded, low-chroma, aged materials. Structural neutrals (cool blue-grey
# charcoals) make up ~95% of the screen; colour is rare punctuation with strict
# semantic ownership — COOL sage = the world (places/nature/directions), WARM brass
# = the player & interaction (name/items/usable/time-of-day light), dusty SALMON =
# danger/health. Saturation stays low; nothing should feel luminous or neon.
BG_COLOR = (23, 24, 27)                  # 17181B — neutral charcoal panel/surface (faint cool)
TEXT_COLOR = (215, 216, 218)             # D7D8DA — soft primary text (never pure white)

# ── input bar ─────────────────────────────────────────────────────────────────
INPUT_BG = (14, 15, 17)                  # 0E0F11 — deepest structural neutral (near-black charcoal)
INPUT_BORDER = (60, 62, 68)              # 39424E — faint neutral edge
INPUT_TEXT = (215, 216, 218)             # D7D8DA
INPUT_SELECTION_BG = (44, 46, 52)        # muted neutral-slate selection

# ── menus ─────────────────────────────────────────────────────────────────────
MENU_OVERLAY = (10, 11, 13, 200)
MENU_PANEL_BG = (20, 21, 24)             # 10161D
MENU_PANEL_BORDER = (60, 62, 68)         # 39424E — subtle, blends
MENU_BUTTON_BG = (30, 32, 37)            # 1B232D
MENU_BUTTON_HOVER = (60, 62, 68)         # 39424E
MENU_BUTTON_TEXT = (215, 216, 218)       # D7D8DA

# ── accents ───────────────────────────────────────────────────────────────────
PROMPT_COLOR = (211, 155, 87)            # D39B57 — aged brass (player / interaction)
SYSTEM_COLOR = (140, 148, 157)           # 8C949D — secondary reading neutral
CURSOR_COLOR = (215, 216, 218)           # D7D8DA

# ── command toolbar (collapsible, top) ──────────────────────────────────────────
HINT_PANEL_BG = (20, 21, 24, 150)        # 141518, faint
HINT_PANEL_BORDER = (60, 62, 68, 110)    # 3C3E44 neutral
HINT_LABEL_COLOR = (140, 148, 157)       # 8C949D
HINT_TEXT_COLOR = (102, 112, 122)        # 66707A — low-emphasis neutral
HINT_EDGE_GAP = 12                       # gap from the window's right/top edge
HINT_TEXT_GAP = 16                       # gap between narrative text and the widget

# ── narrative highlights ────────────────────────────────────────────────────────
# WARM family = player & interaction (human/agency); COOL family = the world.
HIGHLIGHT_NAME = (224, 170, 103)         # the player — E0AA67 brightest brass (signature)
HIGHLIGHT_NPC = (200, 142, 78)           # people — C88E4E warm (human)
HIGHLIGHT_LOCATION = (135, 184, 168)     # named places — 87B8A8 muted sage (world)
HIGHLIGHT_ITEM = (200, 160, 106)         # carried/known items — C8A06A warm tan (possession)
HIGHLIGHT_DESCRIPTOR = (94, 122, 114)    # words from place names — 5E7A72 dim cool
HIGHLIGHT_TIME = (203, 168, 119)         # time of day / light — CBA877 pale warm light
HIGHLIGHT_DANGER = (219, 126, 119)       # violence / threat — DB7E77 dusty salmon
HIGHLIGHT_INTERACT = (211, 155, 87)      # usable features — D39B57 brass (interaction)
HIGHLIGHT_DIRECTION = (111, 155, 144)    # compass headings — 6F9B90 cool
HIGHLIGHT_NATURE = (127, 174, 158)       # terrain / weather — 7FAE9E sage (world)
HIGHLIGHT_MAGIC = (154, 138, 166)        # the arcane — 9A8AA6 dusty mauve (low chroma)
HIGHLIGHT_COMBAT = (230, 138, 130)       # combat log text — E68A82 dusty salmon

# base tint for a whole block describing a newly-entered area — a faded-canvas warm
# cast, very low chroma, so the prose reads as "a place" without shouting
AREA_INTRO_COLOR = (168, 154, 130)       # A89A82 — faded canvas

# ── persistent status bar (top) ───────────────────────────────────────────────
STATUS_BAR_BG = (20, 21, 24)             # 10161D
STATUS_BAR_BORDER = (60, 62, 68)         # 39424E
STATUS_LABEL_COLOR = (102, 112, 122)     # 66707A — dim "HP" / "Wpn" labels
STATUS_VALUE_COLOR = (184, 190, 197)     # B8BEC5 — secondary-bright values
STATUS_HP_BG = (30, 32, 37)              # 1B232D — empty portion of the HP bar
STATUS_HP_FILL = (219, 126, 119)         # DB7E77 — filled portion (dusty salmon)

# ── entity detail: pygame hover tooltip / Textual Inspect card ────────────────
TOOLTIP_BG = (20, 21, 24, 248)           # 141518
TOOLTIP_BORDER = (60, 62, 68)            # 39424E
TOOLTIP_TITLE_COLOR = (211, 155, 87)     # D39B57 brass
TOOLTIP_TEXT_COLOR = (184, 190, 197)     # B8BEC5

PARAGRAPH_GAP = 10


# ── themes ────────────────────────────────────────────────────────────────────
# Every colour above is the "dark" theme. A theme is just a dict of overrides for
# these names; apply_theme() (in legacy/ui.py) swaps the module globals, and because
# every render call reads the names at call-time, the whole UI recolours with no
# other change.
THEME_KEYS = [
    "BG_COLOR", "TEXT_COLOR", "INPUT_BG", "INPUT_BORDER", "INPUT_TEXT",
    "INPUT_SELECTION_BG", "MENU_OVERLAY", "MENU_PANEL_BG", "MENU_PANEL_BORDER",
    "MENU_BUTTON_BG", "MENU_BUTTON_HOVER", "MENU_BUTTON_TEXT", "PROMPT_COLOR",
    "SYSTEM_COLOR", "CURSOR_COLOR", "HINT_PANEL_BG", "HINT_PANEL_BORDER",
    "HINT_LABEL_COLOR", "HINT_TEXT_COLOR", "HIGHLIGHT_NAME", "HIGHLIGHT_NPC",
    "HIGHLIGHT_LOCATION", "HIGHLIGHT_ITEM", "HIGHLIGHT_DESCRIPTOR", "HIGHLIGHT_TIME",
    "HIGHLIGHT_DANGER", "HIGHLIGHT_INTERACT", "HIGHLIGHT_DIRECTION", "HIGHLIGHT_NATURE",
    "HIGHLIGHT_MAGIC", "HIGHLIGHT_COMBAT", "AREA_INTRO_COLOR", "STATUS_BAR_BG",
    "STATUS_BAR_BORDER", "STATUS_LABEL_COLOR", "STATUS_VALUE_COLOR", "STATUS_HP_BG",
    "STATUS_HP_FILL", "TOOLTIP_BG", "TOOLTIP_BORDER", "TOOLTIP_TITLE_COLOR",
    "TOOLTIP_TEXT_COLOR",
]

_THEME_DARK = {k: globals()[k] for k in THEME_KEYS}

# "light" — warm paper, inspired by Solarized Light + a parchment cast. Reads like
# an old book page; accents are deepened so they stay legible on cream.
_THEME_LIGHT = {**_THEME_DARK, **{
    "BG_COLOR": (244, 238, 222), "TEXT_COLOR": (58, 54, 46),
    "INPUT_BG": (252, 248, 238), "INPUT_BORDER": (205, 193, 168),
    "INPUT_TEXT": (50, 46, 38), "INPUT_SELECTION_BG": (214, 224, 238),
    "MENU_OVERLAY": (40, 36, 28, 140), "MENU_PANEL_BG": (250, 245, 233),
    "MENU_PANEL_BORDER": (208, 196, 170), "MENU_BUTTON_BG": (236, 228, 210),
    "MENU_BUTTON_HOVER": (224, 214, 190), "MENU_BUTTON_TEXT": (58, 54, 46),
    "PROMPT_COLOR": (150, 100, 12), "SYSTEM_COLOR": (104, 96, 78),
    "CURSOR_COLOR": (50, 46, 38), "HINT_PANEL_BG": (236, 228, 210, 150),
    "HINT_PANEL_BORDER": (208, 196, 170, 120), "HINT_LABEL_COLOR": (116, 108, 90),
    "HINT_TEXT_COLOR": (140, 130, 110), "HIGHLIGHT_NAME": (150, 100, 12),
    "HIGHLIGHT_NPC": (177, 90, 32), "HIGHLIGHT_LOCATION": (38, 108, 158),
    "HIGHLIGHT_ITEM": (63, 125, 58), "HIGHLIGHT_DESCRIPTOR": (138, 128, 104),
    "HIGHLIGHT_TIME": (150, 104, 40), "HIGHLIGHT_DANGER": (178, 58, 52),
    "HIGHLIGHT_INTERACT": (28, 134, 120), "HIGHLIGHT_DIRECTION": (74, 106, 150),
    "HIGHLIGHT_NATURE": (95, 125, 46), "HIGHLIGHT_MAGIC": (122, 79, 176),
    "HIGHLIGHT_COMBAT": (178, 58, 52), "AREA_INTRO_COLOR": (120, 92, 44),
    "STATUS_BAR_BG": (236, 228, 210), "STATUS_BAR_BORDER": (208, 196, 170),
    "STATUS_LABEL_COLOR": (130, 120, 100), "STATUS_VALUE_COLOR": (52, 48, 40),
    "STATUS_HP_BG": (222, 206, 196), "STATUS_HP_FILL": (188, 80, 72),
    "TOOLTIP_BG": (250, 245, 233, 250), "TOOLTIP_BORDER": (200, 188, 162),
    "TOOLTIP_TITLE_COLOR": (120, 82, 24), "TOOLTIP_TEXT_COLOR": (78, 72, 60),
}}

# "earthy" — Gruvbox (dark, material): warm bark-brown base, cream fg, and the
# Gruvbox accent set (yellow / orange / aqua / green / blue / red / purple).
_THEME_EARTHY = {**_THEME_DARK, **{
    "BG_COLOR": (40, 40, 40), "TEXT_COLOR": (235, 219, 178),
    "INPUT_BG": (50, 48, 47), "INPUT_BORDER": (102, 92, 84),
    "INPUT_TEXT": (235, 219, 178), "INPUT_SELECTION_BG": (80, 73, 69),
    "MENU_OVERLAY": (20, 18, 16, 210), "MENU_PANEL_BG": (50, 48, 46),
    "MENU_PANEL_BORDER": (102, 92, 84), "MENU_BUTTON_BG": (60, 56, 54),
    "MENU_BUTTON_HOVER": (80, 73, 69), "MENU_BUTTON_TEXT": (235, 219, 178),
    "PROMPT_COLOR": (250, 189, 47), "SYSTEM_COLOR": (213, 196, 161),
    "CURSOR_COLOR": (235, 219, 178), "HINT_PANEL_BG": (50, 48, 46, 130),
    "HINT_PANEL_BORDER": (102, 92, 84, 90), "HINT_LABEL_COLOR": (168, 153, 132),
    "HINT_TEXT_COLOR": (146, 131, 116), "HIGHLIGHT_NAME": (250, 189, 47),
    "HIGHLIGHT_NPC": (254, 128, 25), "HIGHLIGHT_LOCATION": (131, 165, 152),
    "HIGHLIGHT_ITEM": (184, 187, 38), "HIGHLIGHT_DESCRIPTOR": (168, 153, 132),
    "HIGHLIGHT_TIME": (216, 178, 120), "HIGHLIGHT_DANGER": (251, 73, 52),
    "HIGHLIGHT_INTERACT": (142, 192, 124), "HIGHLIGHT_DIRECTION": (146, 131, 116),
    "HIGHLIGHT_NATURE": (152, 151, 26), "HIGHLIGHT_MAGIC": (211, 134, 155),
    "HIGHLIGHT_COMBAT": (251, 73, 52), "AREA_INTRO_COLOR": (216, 182, 120),
    "STATUS_BAR_BG": (50, 48, 46), "STATUS_BAR_BORDER": (80, 73, 69),
    "STATUS_LABEL_COLOR": (168, 153, 132), "STATUS_VALUE_COLOR": (235, 219, 178),
    "STATUS_HP_BG": (60, 40, 36), "STATUS_HP_FILL": (251, 73, 52),
    "TOOLTIP_BG": (40, 37, 34, 248), "TOOLTIP_BORDER": (102, 92, 84),
    "TOOLTIP_TITLE_COLOR": (250, 189, 47), "TOOLTIP_TEXT_COLOR": (213, 196, 161),
}}

# "cyber" — neon-noir for sci-fi / cyberpunk stories. A near-black indigo base under
# rain-slick neon: the WARM family (player & interaction) becomes hot magenta / electric
# blue — human signal cutting through the grid — while the COOL family (the world) is
# all cyan & teal, like signage and holograms. Danger is a hot red alarm; magic/tech is
# neon violet. High chroma on accents, but the base stays dark & desaturated so the
# neon reads as glow, not noise.
_THEME_CYBER = {**_THEME_DARK, **{
    "BG_COLOR": (13, 14, 22), "TEXT_COLOR": (198, 208, 220),
    "INPUT_BG": (8, 9, 15), "INPUT_BORDER": (40, 48, 72),
    "INPUT_TEXT": (198, 208, 220), "INPUT_SELECTION_BG": (30, 44, 66),
    "MENU_OVERLAY": (4, 6, 12, 210), "MENU_PANEL_BG": (16, 18, 28),
    "MENU_PANEL_BORDER": (44, 54, 82), "MENU_BUTTON_BG": (22, 26, 40),
    "MENU_BUTTON_HOVER": (44, 54, 82), "MENU_BUTTON_TEXT": (198, 208, 220),
    "PROMPT_COLOR": (245, 92, 196), "SYSTEM_COLOR": (120, 134, 158),
    "CURSOR_COLOR": (224, 240, 255), "HINT_PANEL_BG": (16, 18, 28, 150),
    "HINT_PANEL_BORDER": (44, 54, 82, 110), "HINT_LABEL_COLOR": (110, 124, 150),
    "HINT_TEXT_COLOR": (84, 96, 120), "HIGHLIGHT_NAME": (255, 110, 206),
    "HIGHLIGHT_NPC": (224, 120, 224), "HIGHLIGHT_LOCATION": (64, 224, 220),
    "HIGHLIGHT_ITEM": (90, 224, 188), "HIGHLIGHT_DESCRIPTOR": (70, 120, 130),
    "HIGHLIGHT_TIME": (245, 206, 110), "HIGHLIGHT_DANGER": (255, 84, 96),
    "HIGHLIGHT_INTERACT": (96, 208, 255), "HIGHLIGHT_DIRECTION": (88, 180, 210),
    "HIGHLIGHT_NATURE": (72, 200, 190), "HIGHLIGHT_MAGIC": (180, 130, 255),
    "HIGHLIGHT_COMBAT": (255, 96, 120), "AREA_INTRO_COLOR": (120, 150, 180),
    "STATUS_BAR_BG": (16, 18, 28), "STATUS_BAR_BORDER": (44, 54, 82),
    "STATUS_LABEL_COLOR": (96, 110, 138), "STATUS_VALUE_COLOR": (190, 204, 220),
    "STATUS_HP_BG": (28, 22, 40), "STATUS_HP_FILL": (255, 84, 120),
    "TOOLTIP_BG": (16, 18, 28, 248), "TOOLTIP_BORDER": (44, 54, 82),
    "TOOLTIP_TITLE_COLOR": (245, 92, 196), "TOOLTIP_TEXT_COLOR": (190, 204, 220),
}}

THEMES = {"dark": _THEME_DARK, "light": _THEME_LIGHT, "earthy": _THEME_EARTHY,
          "cyber": _THEME_CYBER}
THEME_LABELS = {"dark": "Dark", "light": "Light", "earthy": "Earthy & warm",
                "cyber": "Cyber (neon-noir)"}


# ── day/night lighting phase ────────────────────────────────────────────────────
# A gentle, theme-agnostic "white balance" laid over any palette so the whole screen
# warms a touch by in-game day and cools by night — the lighting changes, the theme's
# identity does not. `temp` ∈ [-1, +1]: +1 = warm midday (push toward amber), -1 = cool
# deep night (push toward blue). `bright` is a value multiplier (≈0.90 night … 1.05
# midday). Multiplicative tinting is exactly how a camera does white balance: it scales
# each channel, so relative luminance/contrast — and thus legibility — are preserved.
#
# In-game time-of-day → (temp, bright). Deliberately subtle; the moonlight/daylight cue
# should read as mood, never as a different theme.
DAYNIGHT_PHASES = {
    "early morning": (-0.15, 0.97),
    "morning":       (0.45, 1.02),
    "midday":        (0.85, 1.05),
    "afternoon":     (0.65, 1.03),
    "evening":       (-0.10, 0.98),
    "night":         (-0.65, 0.94),
    "deep night":    (-0.95, 0.90),
}

# Neutral phase = no tint at all (identity). Used before any time is known and when the
# day/night lighting is switched off, so the flat theme renders exactly as authored.
NEUTRAL_PHASE = (0.0, 1.0)

# Per-channel warm/cool slope vs `temp`: warming raises red and lowers blue (toward
# amber); cooling does the reverse (toward blue). Green stays put so skin/foliage hues
# don't drift. Tuned small on purpose.
_WARM_GAIN = (0.06, 0.0, -0.10)


def phase_for(time_label: str) -> tuple[float, float]:
    """In-game time label → (temp, bright) lighting phase; neutral if unknown."""
    return DAYNIGHT_PHASES.get((time_label or "").strip().lower(), NEUTRAL_PHASE)


def tint_theme(theme: dict, temp: float = 0.0, bright: float = 1.0) -> dict:
    """Return a copy of a theme dict with the day/night lighting applied. Each RGB is
    multiplied by a warm/cool, brightness-scaled gain per channel (alpha preserved).
    At the neutral phase this is a faithful copy, so callers can tint unconditionally."""
    temp = max(-1.0, min(1.0, temp))
    rf = (1 + _WARM_GAIN[0] * temp) * bright
    gf = (1 + _WARM_GAIN[1] * temp) * bright
    bf = (1 + _WARM_GAIN[2] * temp) * bright
    out: dict = {}
    for k, v in theme.items():
        r = min(255, max(0, round(v[0] * rf)))
        g = min(255, max(0, round(v[1] * gf)))
        b = min(255, max(0, round(v[2] * bf)))
        out[k] = (r, g, b) + tuple(v[3:])   # keep an alpha component if present
    return out

# What `from game.palette import *` exposes: every themeable color, the layout
# constants that lived alongside them, and the theme tables.
__all__ = THEME_KEYS + [
    "HINT_EDGE_GAP", "HINT_TEXT_GAP", "PARAGRAPH_GAP",
    "THEME_KEYS", "THEMES", "THEME_LABELS",
    "DAYNIGHT_PHASES", "NEUTRAL_PHASE", "phase_for", "tint_theme",
]
