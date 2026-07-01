"""Shared, toolkit-free narrative highlighting.

Both back-ends compute the same role-tagged spans over the narrative; only the
*rendering* differs (pygame blits colored glyphs, Textual builds a Rich `Text`).
This module is the single source of that pure regex logic, lifted out of the pygame
UI (now `legacy/ui.py`) in the Textual port. It imports no UI toolkit.

`compute_highlight_spans` returns spans in **application order**; callers fill a
per-position map with first-wins precedence (earlier spans claim a character before
later ones), which reproduces the original pygame behavior exactly: the dynamic
categories (name → location → item → descriptor → npc) win over the static keyword
groups, and within a category list order decides ties.
"""

from __future__ import annotations

import re

# ── semantic roles (neutral names; each back-end maps these to its own color) ───
ROLE_NAME = "name"            # the player
ROLE_LOCATION = "location"    # named places
ROLE_ITEM = "item"            # carried/known items
ROLE_DESCRIPTOR = "descriptor"  # words drawn from place names (dim, no tooltip)
ROLE_NPC = "npc"              # people
ROLE_DANGER = "danger"        # violence / threat
ROLE_MAGIC = "magic"          # the arcane
ROLE_TIME = "time"            # time of day / light
ROLE_INTERACT = "interact"    # usable features
ROLE_DIRECTION = "direction"  # compass headings
ROLE_NATURE = "nature"        # terrain / weather

# Static keyword groups, applied after the dynamic categories. Order is precedence:
# earlier groups win a character over later ones (and all lose to name/location/
# item/descriptor/npc). Word lists are verbatim from the original pygame
# `_build_highlights`.
KEYWORD_GROUPS: list[tuple[str, list[str]]] = [
    (ROLE_DANGER, [
        "blood", "bloody", "wound", "wounded", "wounds", "danger", "dangerous",
        "threat", "ambush", "attack", "attacks", "hostile", "deadly", "dead",
        "death", "corpse", "kill", "killed", "slain", "slay", "blade", "sword",
        "dagger", "knife", "axe", "spear", "arrow", "bow", "poison", "venom",
        "scream", "screams", "scar", "scarred", "fire", "flame", "flames", "burning",
    ]),
    (ROLE_MAGIC, [
        "magic", "magical", "spell", "spells", "rune", "runes", "enchanted",
        "enchantment", "arcane", "sorcery", "sorcerer", "witch", "wizard", "mage",
        "curse", "cursed", "ritual", "sigil", "ward", "glyph", "conjure", "summon",
        "hex", "relic", "talisman", "amulet", "charm",
    ]),
    (ROLE_TIME, [
        "dawn", "daybreak", "sunrise", "morning", "midday", "noon", "afternoon",
        "dusk", "twilight", "sunset", "evening", "nightfall", "night", "midnight",
        "moon", "moonlight", "moonlit", "starlight", "candlelight", "torchlight",
    ]),
    (ROLE_INTERACT, [
        "door", "doors", "gate", "gates", "lever", "switch", "altar", "statue",
        "chest", "bridge", "stairs", "staircase", "ladder", "well", "lock", "key",
        "handle", "rope", "trapdoor", "hatch", "shrine", "pedestal", "mechanism", "latch",
    ]),
    (ROLE_DIRECTION, [
        "north", "south", "east", "west", "northeast", "northwest", "southeast",
        "southwest", "northward", "southward", "eastward", "westward",
    ]),
    (ROLE_NATURE, [
        "forest", "woods", "tree", "trees", "river", "stream", "creek", "mountain",
        "mountains", "hill", "hills", "rain", "snow", "wind", "fog", "mist", "mud",
        "moss", "storm", "thunder", "lightning", "sea", "ocean", "lake", "swamp",
        "marsh", "meadow", "valley", "cliff", "field", "grass", "roots",
    ]),
]

_DESCRIPTOR_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "at", "in", "on", "by", "for", "with", "from",
    "near", "toward", "towards", "above", "below", "off", "into", "over", "under", "through", "across",
    "edge", "road", "path",
}


def extract_location_descriptors(locations: list[str]) -> list[str]:
    """Distinctive words pulled from known place names, used as a dim secondary
    highlight (e.g. 'kettle' from 'Brine Kettle Inn'). Longest-first so the regex
    matching prefers the most specific token."""
    words = set()
    for loc in locations:
        for token in re.findall(r"[a-zA-Z]+", loc.lower()):
            if len(token) < 4:
                continue
            if token in _DESCRIPTOR_STOPWORDS:
                continue
            words.add(token)
    return sorted(words, key=len, reverse=True)


def compute_highlight_spans(
    text: str,
    *,
    player_name: str = "",
    locations: list[str] | None = None,
    items: list[str] | None = None,
    descriptors: list[str] | None = None,
    npcs: list[str] | None = None,
) -> list[tuple[int, int, str, str | None]]:
    """Role-tag spans of `text`. Returns `(start, end, role, key)` tuples in
    application order; `key` is the lowercase entity name for tooltip lookup, or
    `None` for descriptor/keyword spans that carry no entity. Callers apply spans
    first-wins per character position to reproduce precedence."""
    locations = locations or []
    items = items or []
    descriptors = descriptors or []
    npcs = npcs or []
    spans: list[tuple[int, int, str, str | None]] = []

    if player_name:
        for m in re.finditer(re.escape(player_name), text, re.IGNORECASE):
            spans.append((m.start(), m.end(), ROLE_NAME, player_name.lower()))
    for loc in locations:
        if len(loc) < 3:
            continue
        for m in re.finditer(re.escape(loc), text, re.IGNORECASE):
            spans.append((m.start(), m.end(), ROLE_LOCATION, loc.lower()))
    for item in items:
        if len(item) < 3:
            continue
        for m in re.finditer(re.escape(item), text, re.IGNORECASE):
            spans.append((m.start(), m.end(), ROLE_ITEM, item.lower()))
    for descriptor in descriptors:
        for m in re.finditer(rf"\b{re.escape(descriptor)}\b", text, re.IGNORECASE):
            spans.append((m.start(), m.end(), ROLE_DESCRIPTOR, None))
    for npc in npcs:
        if len(npc) < 3:
            continue
        for m in re.finditer(re.escape(npc), text, re.IGNORECASE):
            spans.append((m.start(), m.end(), ROLE_NPC, npc.lower()))
    for role, words in KEYWORD_GROUPS:
        for keyword in words:
            for m in re.finditer(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
                spans.append((m.start(), m.end(), role, None))

    return spans
