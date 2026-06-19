import os
import queue
import threading
import time
import pygame
from game import config
from game.engine import EngineState, PlayerCharacter
from game.stats import SessionStats
from game.logs import (
    init_logs, write_world_seed, process_response,
    save_session, save_game, load_game,
    list_saves, delete_save, export_book,
)
from game.ui import GameUI, PAUSE_SENTINEL
from game.combat import CombatInterface, run_combat
from game.game_logic import (
    handle_local_command, call_llm, update_synopsis, load_system_prompt,
    format_inventory_display, generate_recap, SEED_INSTRUCTION, _disposition_word,
    format_npc_directory, format_world_map, format_world_chronicle, format_quest_log,
    write_journal_chapter, run_world_tick, apply_world_tick, PLAY_AS_ACTION,
)


session_stats = SessionStats()

# The background chronicler writes a journal chapter on a soft cadence (every
# CHRONICLE_EVERY turns) OR sooner when a significant event lands, but never
# closer together than CHRONICLE_MIN_GAP turns — so the diary reads continuously
# without clustering or costing a call every turn.
CHRONICLE_EVERY = 6
CHRONICLE_MIN_GAP = 3

# The offscreen world-director advances existing threads on a soft cadence or when
# time passes (long travel / rest), never closer than WORLD_TICK_MIN_GAP turns.
WORLD_TICK_EVERY = 8
WORLD_TICK_MIN_GAP = 4


DEBUG_LOG = "logs/debug_narrative.txt"
DEBUG_LOCK = threading.RLock()


# ── debug logging ─────────────────────────────────────────────────────────────

def _debug_log_clear():
    with DEBUG_LOCK:
        os.makedirs("logs", exist_ok=True)
        with open(DEBUG_LOG, "w") as f:
            f.write("")


def _debug_log(turn: int, player_input: str, narrative: str):
    with DEBUG_LOCK:
        os.makedirs(os.path.dirname(DEBUG_LOG), exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"\n--- Turn {turn} ---\n")
            f.write(f"INPUT: {player_input}\n")
            f.write(f"OUTPUT: {narrative}\n")




# ── helpers ───────────────────────────────────────────────────────────────────

def _known_npcs_for_ui(state: EngineState) -> list[str]:
    npcs = []
    for rec in state.npcs.values():
        if rec.name and rec.name not in npcs:
            npcs.append(rec.name)
    return npcs


def _consumable_effect_label(effect: str) -> str:
    if effect.startswith("heal_"):
        try:
            amount = int(effect.split("_")[1])
            return f"heal +{amount}"
        except Exception:
            return "heal"
    return effect.replace("_", " ")


def _all_items_for_ui(state: EngineState) -> list[str]:
    return (
        [w.name for w in state.weapons] +
        [a.name for a in state.armor] +
        [c.name for c in state.consumables] +
        [t.name for t in state.trinkets]
    )


def _known_places(state: EngineState) -> list[str]:
    """Every place the engine knows of — not just visited ones, but also
    destinations it has heard of (graph endpoints), places it can describe, and
    anywhere a world fact is pinned. So a landmark the player hasn't walked to
    yet still highlights and shows a tooltip."""
    places = set(state.visited_locations)
    places.update(state.location_descriptions.keys())
    places.update(f.location for f in state.world_facts if f.location)
    for src, edges in state.location_graph.items():
        places.add(src)
        places.update(edges.values())
    places.discard("unknown")
    places.discard("")
    return sorted(p for p in places if p)


def _entity_info_for_ui(state: EngineState) -> dict[str, str]:
    """Hover-tooltip text for the highlighted words in the narrative, drawn from
    live engine state — who someone is, where a place connects, what an item is."""
    info: dict[str, str] = {}

    if state.player.name:
        info[state.player.name] = f"{state.player.name}\nYou — {state.player.background}"

    for rec in state.npcs.values():
        if not rec.name:
            continue
        tags = [t for t in (rec.role, _disposition_word(rec.disposition)) if t]
        head = f"{rec.name} — {', '.join(tags)}" if tags else rec.name
        body = []
        if rec.location:
            body.append(f"Last known at {rec.location}.")
        if rec.facts:
            body.append(rec.facts[-1])
        info[rec.name] = head + ("\n" + " ".join(body) if body else "")

    # incoming edges (dest -> how you'd approach it), so even an unvisited
    # landmark gets a useful tooltip line.
    incoming: dict[str, tuple[str, str]] = {}
    for src, edges in state.location_graph.items():
        for d, dest in edges.items():
            incoming.setdefault(dest, (src, d))

    for place in _known_places(state):
        lines = []
        desc = state.location_descriptions.get(place)
        if desc:
            lines.append(desc)
        conns = state.connections_from(place)
        if conns:
            lines.append("Paths: " + ", ".join(f"{d} to {p}" for d, p in conns.items()))
        elif place in incoming:
            src, d = incoming[place]
            lines.append(f"Lies {d} of {src}.")
        facts = [f.text for f in state.world_facts if f.location == place]
        if facts:
            lines.append(" ".join(facts[-2:]))
        info[place] = place + ("\n" + "\n".join(lines) if lines else "")

    for w in state.weapons:
        info[w.name] = f"{w.name} (1-{w.damage_range} dmg)" + (f"\n{w.description}" if w.description else "")
    for a in state.armor:
        info[a.name] = f"{a.name} ({a.armor_value} armor)" + (f"\n{a.description}" if a.description else "")
    for c in state.consumables:
        tag = f" ({c.effect})" if c.effect else ""
        info[c.name] = f"{c.name}{tag}" + (f"\n{c.description}" if c.description else "")
    for t in state.trinkets:
        info[t.name] = t.name + (f"\n{t.description}" if t.description else "")

    return info


def _refresh_ui(ui: GameUI, state: EngineState):
    """Push current engine state into the highlight context, hover tooltips, and
    the persistent status bar. Called whenever state changes."""
    ui.set_context(
        state.player.name,
        _known_places(state),
        _all_items_for_ui(state),
        _known_npcs_for_ui(state),
        info=_entity_info_for_ui(state),
    )
    ui.set_status(
        state.hp, state.max_hp, state.location, state._time_label(),
        state.equipped_weapon.name, state.equipped_armor.name,
    )


# ── local commands ────────────────────────────────────────────────────────────



# ── opening menu ──────────────────────────────────────────────────────────────

def _save_label(meta: dict) -> str:
    """A one-line description of a save slot for menus."""
    when = (meta.get("saved_at") or "")[:16].replace("T", " ")
    bits = [meta.get("name") or meta.get("player", "save")]
    tail = []
    if meta.get("location"):
        tail.append(meta["location"])
    if meta.get("turn"):
        tail.append(f"turn {meta['turn']}")
    if when:
        tail.append(when)
    if tail:
        bits.append("— " + ", ".join(tail))
    return " ".join(bits)


def _unique_slot(name: str) -> str:
    """A save-slot name derived from the character name, avoiding collisions
    with existing slots."""
    base = (name or "adventurer").strip() or "adventurer"
    existing = {s["slot"] for s in list_saves()}
    from game.logs import _slugify
    slug = _slugify(base)
    if slug not in existing:
        return base
    n = 2
    while _slugify(f"{base} {n}") in existing:
        n += 1
    return f"{base} {n}"


def _choose_save(ui: GameUI, saves: list[dict]) -> str | None:
    options = [(_save_label(s), s["slot"]) for s in saves]
    options.append(("Back", "__back__"))
    choice = ui.show_menu("Load game", options, subtitle="Pick a save to continue.")
    if choice in ("__back__", "quit", "exit", "") or not ui.running:
        return None
    return choice


def _manage_saves(ui: GameUI):
    while ui.running:
        saves = list_saves()
        if not saves:
            ui.add_system("No saves to manage.")
            return
        options = [(_save_label(s), s["slot"]) for s in saves]
        options.append(("Back", "__back__"))
        choice = ui.show_menu("Manage saves", options, subtitle="Select a save to delete.")
        if choice in ("__back__", "quit", "exit", "") or not ui.running:
            return
        confirm = ui.show_menu(
            "Delete save?",
            [("Yes, delete it", "yes"), ("Cancel", "no")],
            subtitle=f"This permanently removes '{choice}'.",
        )
        if confirm == "yes":
            delete_save(choice)
            ui.add_system(f"Deleted save '{choice}'.")


def run_setup(ui: GameUI, forced: bool = False) -> bool:
    """First-run / settings flow: pick a provider, enter a key, write .env, and
    reload config so it takes effect this session. Returns True if a usable key
    is configured afterward."""
    if forced:
        ui.add_system(
            "Welcome. Before you can play, the game needs an API key for the model "
            "that narrates the world.\nYou can use OpenAI or any OpenAI-compatible "
            "provider. Your key is written to a local .env file and never leaves "
            "this machine."
        )
    preset_key = ui.show_menu(
        "Choose a provider",
        [(p["label"], k) for k, p in config.PROVIDER_PRESETS.items()] + [("Cancel", "__cancel__")],
        subtitle="Sets the endpoint and default models. You'll enter your key next.",
    )
    if preset_key in ("__cancel__", "__back__", "quit", "exit", "") or not ui.running:
        return not config.needs_setup()
    preset = config.PROVIDER_PRESETS[preset_key]

    ui.add_system(
        f"{preset['label']} selected. Paste your API key and press Enter "
        "(for a local model with no key, just press Enter)."
    )
    key = ui.get_input(allow_empty=True)
    if not ui.running:
        return False
    key = key.strip()
    if not key and preset_key != "ollama":
        ui.add_system("No key entered. You can set one later from Settings.")
        return not config.needs_setup()

    updates = {
        "LLM_API_KEY": key or "ollama",
        "LLM_BASE_URL": preset["LLM_BASE_URL"],
        "MODEL_NARRATIVE": preset["MODEL_NARRATIVE"],
        "MODEL_SUMMARY": preset["MODEL_SUMMARY"],
        "LLM_REASONING_EFFORT": preset["LLM_REASONING_EFFORT"],
    }
    config.write_env(updates)
    config.reload()
    ui.add_system(
        f"Setup saved. Provider: {preset['label']}, model: {config.MODEL_NARRATIVE}. "
        "You can change this later from Settings."
    )
    return not config.needs_setup()


COMMANDS_HELP = (
    "Type anything to act — talk, move, fight, search. New here? Try /tutorial.\n"
    "Quick read-outs:\n"
    "  /inventory · /hp · /time · /location · /map\n"
    "  /quests · /people · /chronicle · /recap\n"
    "Do things:\n"
    "  /use [item] · /equip [item]\n"
    "Other:\n"
    "  /tutorial · /journal · /export · /settings · /theme · /help · /quit\n"
    "Hover a highlighted word for detail. Space skips the typewriter; scroll to read\n"
    "back. Esc pauses / backs out of menus."
)


# First-pass tutorial — a stack of read-aloud cards covering every feature. Shown
# via /tutorial, the opening menu's "How to play", and pointed at on a new game.
TUTORIAL_PAGES = [
    ("How to play", (
        "This is your story, told a turn at a time. Type what your character does in\n"
        "plain words — \"I push the door open\", \"I ask the smith about the bridge\",\n"
        "\"I draw my knife and charge\". There's no fixed list for actions; try anything.\n"
        "The world answers honestly and REMEMBERS — the people you meet, the places you\n"
        "go, and what you do all persist and come back later.\n"
        "You set the telling: at the start you choose a name, a background, and a tone\n"
        "(the voice the whole story is written in — \"grim and spare\", \"wry and warm\")."
    )),
    ("Reading the screen", (
        "Top bar: your HP, where you are, the time of day, and your equipped weapon and\n"
        "armor — always visible.\n"
        "Highlighted words are things the world is tracking — people, places, items,\n"
        "and more, each its own colour. Hover one with the mouse to see what it is.\n"
        "Text types itself in; press Space or Enter to skip to the end. Scroll up with\n"
        "the mouse wheel to re-read anything."
    )),
    ("Quick read-outs (instant — they don't cost a turn)", (
        "  /inventory  what you're carrying      /map        places you've been + links\n"
        "  /hp         your health               /people     who you've met & how they feel\n"
        "  /time       time of day               /chronicle  what you've changed in the world\n"
        "  /location   where you are             /recap      the story so far\n"
        "  /quests     your active objectives\n"
        "Act on your gear:   /use [item]    ·    /equip [item]"
    )),
    ("Your journey & saves", (
        "/journal opens your journey so far — story, quests, people, places, and the\n"
        "world chronicle, all in one place. /export writes it out as a keepable book.\n"
        "The game autosaves every turn. From the opening menu you can start a New game,\n"
        "Load a save, or Manage (delete) saves. Loading gives you a quick \"previously…\"\n"
        "recap so you remember where you left off."
    )),
    ("Settings & control", (
        "Esc pauses the game (Resume / Journal / Settings / Save & quit) and backs you\n"
        "out of any menu.\n"
        "  /settings   change the model/provider or the theme\n"
        "  /theme      pick Dark, Light, or Earthy\n"
        "  /help       the short command list      /quit   save and exit\n"
        "When a fight starts you'll get buttons: Attack, Use Item, or Flee."
    )),
]


def show_tutorial(ui: GameUI):
    """Walk a first-time player through every feature, as a stack of cards."""
    for title, body in TUTORIAL_PAGES:
        ui.add_panel(title, body)


def _theme_picker(ui: GameUI):
    """Pick a colour theme; applies live and persists to .env."""
    from game import ui as ui_module
    options = [
        (ui_module.THEME_LABELS[k] + (" (current)" if k == ui_module.CURRENT_THEME else ""), k)
        for k in ("dark", "light", "earthy")
    ]
    options.append(("Back", "__back__"))
    choice = ui.show_menu("Theme", options, subtitle="Pick a colour theme.")
    if choice in ui_module.THEMES:
        ui_module.apply_theme(choice)
        ui.rehighlight_all()  # recolour accents on text already on screen
        config.write_env({"UI_THEME": choice})
        ui.add_system(f"Theme set to {ui_module.THEME_LABELS[choice]}.")


def settings_menu(ui: GameUI):
    """In-UI settings: theme and provider/key. Reachable from the opening menu
    or via /settings during play."""
    while ui.running:
        choice = ui.show_menu(
            "Settings",
            [("Theme", "theme"),
             ("Provider & API key", "provider"),
             ("Back", "__back__")],
            subtitle="Change how the game looks and which model narrates it.",
        )
        if choice in ("__back__", "quit", "exit", "") or not ui.running:
            return
        if choice == "theme":
            _theme_picker(ui)
        elif choice == "provider":
            run_setup(ui)


def _journal_story(state: EngineState) -> str:
    """The Story section body: the chronicler's diary chapters if any have been
    written, otherwise the running synopsis as a fallback."""
    if state.journal:
        return "\n\n".join(f"— {ch['title']} —\n{ch['text']}" for ch in state.journal)
    return state.synopsis.strip() or "It's early yet — your story has barely begun."


def journal_menu(ui: GameUI, state: EngineState):
    """The 'journey so far' — a browsable record of the run. Pick a section and
    it's shown as a card. Reuses the same read-outs as the people/map/chronicle/
    quests commands; the story spine is the running synopsis."""
    sections = {
        "story": lambda: "Story so far\n" + _journal_story(state),
        "quests": lambda: format_quest_log(state),
        "people": lambda: format_npc_directory(state),
        "places": lambda: format_world_map(state),
        "chronicle": lambda: format_world_chronicle(state),
    }
    choice = ui.show_menu(
        "Journal",
        [("Story so far", "story"),
         ("Quests", "quests"),
         ("People", "people"),
         ("Places & map", "places"),
         ("Chronicle", "chronicle"),
         ("Export to book", "export"),
         ("Back", "__back__")],
        subtitle="Your journey so far — pick a section to read.",
    )
    if choice in ("__back__", "quit", "exit", "") or not ui.running:
        return
    if choice == "export":
        _export_book(ui, state)
        return
    title, _, body = sections.get(choice, lambda: "")().partition("\n")
    ui.add_panel(title, body)


def _export_book(ui: GameUI, state: EngineState):
    """Compile the journal into a keepable Markdown book and tell the player where
    it landed. Shared by the journal menu's Export entry and the /export command."""
    try:
        path = export_book(state)
    except Exception:
        ui.add_system("Couldn't write the book just now — try again in a moment.")
        return
    chapters = len(state.journal)
    if chapters:
        ui.add_system(f"Your tale ({chapters} chapter{'s' if chapters != 1 else ''}) "
                      f"was written to:\n{path}")
    else:
        ui.add_system(f"Exported to:\n{path}\n(The journal is still empty — play on "
                      "and it will fill out.)")


def _streaming_sink(ui: GameUI):
    """Build an on_delta callback that swaps the 'thinking' spinner for live
    narrative on the first streamed token. Returns (on_delta, streamed), where
    streamed[0] flips True once any text has begun streaming — so the caller knows
    whether to finalize a streamed block or fall back to add_narrative."""
    streamed = [False]

    def on_delta(text):
        if not streamed[0]:
            ui.stop_loading()
            ui.begin_narrative_stream()
            streamed[0] = True
        ui.append_narrative_stream(text)

    return on_delta, streamed


def _handle_defeat(ui: GameUI, client, system_prompt, state, hot_context, current_slot):
    """Combat defeat is a setback, not a Game Over. The player survives at a sliver
    of HP; the LLM narrates the aftermath (captured, robbed, left for dead) on a
    forced 'defeat' beat, and the cost lands in state through the normal schema.
    The story continues from here rather than the app closing."""
    state.hp = max(1, state.max_hp // 5)
    _refresh_ui(ui, state)
    ui.start_loading()
    on_delta, streamed = _streaming_sink(ui)
    try:
        aftermath = call_llm(
            client, system_prompt, state, hot_context[-10:],
            "[You were defeated — narrate the aftermath]",
            config.MODEL_NARRATIVE, session_stats, force_situation="defeat",
            on_delta=on_delta,
        )
    except Exception:
        aftermath = None
    ui.stop_loading()
    if aftermath is None:
        ui.add_combat_text("Beaten down and bleeding, you somehow cling to life.")
        return
    state.apply_state_changes(aftermath.state_changes)
    _refresh_ui(ui, state)
    area_intro = aftermath.state_changes.location_is_new
    if streamed[0]:
        ui.end_narrative_stream(aftermath.narrative, area_intro=area_intro)
    else:
        ui.add_narrative(aftermath.narrative, area_intro=area_intro)
    _debug_log(state.session_turn, "[defeat]", aftermath.narrative)
    snapshot = {
        "session_turn": state.session_turn,
        "location": state.location,
        "time_label": state._time_label(),
    }
    threading.Thread(target=process_response, args=(aftermath, snapshot), daemon=True).start()
    hot_context.append(f"[Defeat] {aftermath.narrative}")
    save_game(state, hot_context, current_slot)


def _save_and_quit(ui: GameUI, state, hot_context, current_slot):
    """Persist everything and end the session. Shared by typed `quit` and the
    pause menu's Save & quit."""
    time.sleep(0.5)
    save_session(hot_context, state)
    save_game(state, hot_context, current_slot)
    session_stats.flush()
    ui.add_system(session_stats.summary())
    ui.add_system(f"Saved to '{current_slot}'. Press any key to close.")
    ui.get_input(allow_empty=True)
    ui.running = False


def _save_to_menu(ui: GameUI, state, hot_context, current_slot):
    """Persist and return to the opening menu without ending the session. Shared
    by the pause menu's Save & main menu."""
    save_session(hot_context, state)
    save_game(state, hot_context, current_slot)
    session_stats.flush()


def pause_menu(ui: GameUI, state: EngineState) -> str:
    """Opened by Esc during play. Returns 'resume', 'menu', or 'quit'."""
    while ui.running:
        choice = ui.show_menu(
            "Paused",
            [("Resume", "resume"),
             ("Journal", "journal"),
             ("Settings", "settings"),
             ("Save & main menu", "menu"),
             ("Save & quit", "quit")],
            subtitle="Esc or Resume returns to the game.",
        )
        if choice == "journal":
            journal_menu(ui, state)
            continue
        if choice == "settings":
            settings_menu(ui)
            continue
        if choice == "menu":
            return "menu"
        if choice in ("quit", "exit"):
            return "quit"
        return "resume"  # resume, __back__ (Esc), or empty
    return "resume"


def opening_menu(ui: GameUI) -> tuple[str, str | None]:
    """Returns (mode, slot): ('new', None), ('load', slot), or ('quit', None)."""
    while ui.running:
        saves = list_saves()
        options = [("New game", "new")]
        if saves:
            options.append(("Load game", "load"))
            options.append(("Manage saves", "manage"))
        options.append(("How to play", "tutorial"))
        options.append(("Settings", "settings"))
        options.append(("Quit", "quit"))
        subtitle = "Choose an option to begin." if saves else "No saves yet. Start a new game."
        choice = ui.show_menu("THE GAME", options, subtitle=subtitle)
        if not ui.running:
            return ("quit", None)

        if choice == "new":
            ui.add_system("Starting new game...")
            return ("new", None)
        if choice == "tutorial":
            show_tutorial(ui)
            ui.add_system("(Press Enter to return to the menu.)")
            ui.get_input(allow_empty=True)
            ui.clear()  # don't leave the tutorial stacked behind the reopened menu
            continue
        if choice == "load":
            slot = _choose_save(ui, saves)
            if slot:
                ui.add_system(f"Loading '{slot}'...")
                return ("load", slot)
            continue
        if choice == "manage":
            _manage_saves(ui)
            continue
        if choice == "settings":
            settings_menu(ui)
            continue
        if choice in ("quit", "exit"):
            return ("quit", None)

    return ("quit", None)


# ── combat ────────────────────────────────────────────────────────────────────

class GUICombatInterface(CombatInterface):
    def __init__(self, ui: GameUI, enemy_type: str):
        self.ui = ui
        self.enemy_type = enemy_type

    def show_intro(self, enemy_type: str):
        self.ui.begin_combat_intro(f"COMBAT — {enemy_type}", flashes=1, interval=0.18)
        self.ui.wait_for_combat_intro()

    def log(self, message: str, animate: bool = False):
        self.ui.add_combat_text(message, animate=animate)
        if animate:
            self.ui.wait_for_text_output()

    def on_player_action_complete(self):
        self.ui.wait_for_text_output()
        time.sleep(0.4)

    def choose_action(self, state: EngineState, alive_enemies: list[dict]) -> str:
        weapon_dmg = state.equipped_weapon.damage_range + state.damage_buff
        armor_val = state.equipped_armor.armor_value + state.armor_buff
        status_lines = [
            (f"You: {state.hp}/{state.max_hp} HP", (220, 223, 229)),
            (f"Weapon: {state.equipped_weapon.name} ({weapon_dmg} dmg){state.buff_label('damage')}", (150, 208, 132)),
            (f"Armor: {state.equipped_armor.name} ({armor_val}){state.buff_label('armor')}", (122, 198, 230)),
        ]
        status_lines.append(("Enemies:", (235, 116, 110)))
        for e in alive_enemies:
            status_lines.append((f"  {e['name']}: {e['hp']}/{e['max_hp']} | A {e['armor']}", (235, 116, 110)))

        choice = self.ui.show_combat_hud(
            f"COMBAT — {self.enemy_type}",
            status_lines,
            [("Attack", "attack"), ("Use Item", "item"), ("Flee", "flee")],
        )
        if not self.ui.running or choice in ("quit", "exit"):
            return "flee"
        return choice

    def choose_target(self, alive_enemies: list[dict]) -> dict:
        return sorted(alive_enemies, key=lambda e: (e["hp"], e["name"]))[0]

    def choose_item(self, state: EngineState) -> int | None:
        usable = state.consumables
        item_lines = [
            (f"You: {state.hp}/{state.max_hp} HP", (220, 223, 229)),
            ("Consumables:", (150, 208, 132)),
        ]
        for item in usable:
            item_lines.append((f"  {item.name} [{_consumable_effect_label(item.effect)}]", (150, 208, 132)))

        item_options = [(item.name, f"item_{idx}") for idx, item in enumerate(usable)]
        item_options.append(("Cancel", "cancel"))

        item_choice = self.ui.show_combat_hud(
            f"COMBAT — {self.enemy_type}",
            item_lines,
            item_options,
            layout="vertical",
        )
        if item_choice in ("cancel", "quit", "exit"):
            return None

        try:
            return int(item_choice.split("_")[1])
        except Exception:
            return None


def run_combat_ui(ui: GameUI, state: EngineState, encounter) -> dict:
    ui.add_combat_text(f"═══ COMBAT — {encounter.enemy_type} ═══", animate=True)
    ui.wait_for_text_output()

    interface = GUICombatInterface(ui, encounter.enemy_type)
    return run_combat(state, encounter, interface)


# ── game thread ───────────────────────────────────────────────────────────────

def game_thread(ui: GameUI):
    init_logs()
    system_prompt = load_system_prompt()

    # First run with no key: walk the player through setup before anything else.
    if config.needs_setup():
        if not run_setup(ui, forced=True) or not ui.running:
            ui.running = False
            return

    mode, slot = opening_menu(ui)
    if mode == "quit" or not ui.running:
        ui.running = False
        return

    # Start on a clean transcript so anything shown at the menu (tutorial cards,
    # "theme set", "loading…") doesn't bleed into the game.
    ui.clear()

    # Build the client after any setup/Settings changes have been applied.
    client = config.make_client()
    current_slot = "autosave"
    if mode == "load":
        loaded = load_game(slot)
        if loaded:
            state, hot_context = loaded
            current_slot = slot
            _refresh_ui(ui, state)
            ui.add_system(f"Welcome back, {state.player.name}. Turn {state.session_turn}.")
            ui.add_system(f"Location: {state.location} | HP: {state.hp}/{state.max_hp}")
            inv = format_inventory_display(state)
            inv_title, _, inv_body = inv.partition("\n")
            ui.add_panel(inv_title, inv_body)
            recap = generate_recap(client, state, hot_context, config.MODEL_SUMMARY, session_stats)
            if recap:
                ui.add_system("\nPreviously...")
                ui.add_narrative(recap)
        else:
            ui.add_system("Save could not be loaded. Starting new game.")
            state, hot_context = new_game(ui, client, system_prompt)
            current_slot = _unique_slot(state.player.name) if state else "autosave"
    else:
        state, hot_context = new_game(ui, client, system_prompt)
        current_slot = _unique_slot(state.player.name) if state else "autosave"

    if not ui.running or state is None:
        return

    # Write the slot immediately so a new game shows up in Load right away.
    save_game(state, hot_context, current_slot)

    # Background journal writer ("chronicler"). Every so often a separate thread
    # writes the next journal chapter and drops it in a queue. Only the main game
    # thread ever changes game state, and it's the one that takes chapters off the
    # queue and adds them — so the two never touch the state at the same time and we
    # don't need any locking. (The threads are started with daemon=True, which just
    # means they won't keep the program running if you quit mid-write.)
    chronicle_queue: queue.Queue = queue.Queue()
    chronicle_busy = [False]

    def _drain_chronicle():
        applied = False
        while True:
            try:
                state.journal.append(chronicle_queue.get_nowait())
                applied = True
            except queue.Empty:
                break
        if applied:
            save_game(state, hot_context, current_slot)

    def _maybe_chronicle(event: bool = False):
        if chronicle_busy[0]:
            return
        gap = state.session_turn - state.last_chronicle_turn
        # Never cluster entries; otherwise fire on the soft cadence, or early when
        # something noteworthy happened this turn.
        if gap < CHRONICLE_MIN_GAP or (gap < CHRONICLE_EVERY and not event):
            return
        state.last_chronicle_turn = state.session_turn  # steady cadence even if a chapter fails
        chronicle_busy[0] = True
        synopsis, recent, tone, turn = state.synopsis, list(hot_context[-12:]), state.player.tone, state.session_turn

        def job():
            try:
                ch = write_journal_chapter(client, synopsis, recent, tone, turn,
                                           config.MODEL_SUMMARY, session_stats)
                if ch:
                    chronicle_queue.put(ch)
            finally:
                chronicle_busy[0] = False

        threading.Thread(target=job, daemon=True).start()

    # Background "world director": every so often it moves the world along while the
    # player is elsewhere — an NPC acts on a grudge, a tension builds — and only ever
    # touches things that already exist. It posts its changes to a queue the main
    # game thread applies, the same safe hand-off the journal writer uses. The player
    # sees these changes naturally next time they come up; there's no pop-up.
    world_tick_queue: queue.Queue = queue.Queue()
    world_tick_busy = [False]

    def _drain_world_tick():
        applied_any = False
        while True:
            try:
                tick = world_tick_queue.get_nowait()
            except queue.Empty:
                break
            for summary in apply_world_tick(state, tick):
                applied_any = True
                _debug_log(state.session_turn, "[world-tick]", summary)
        if applied_any:
            save_game(state, hot_context, current_slot)

    def _maybe_world_tick(event: bool = False):
        if world_tick_busy[0]:
            return
        # Nothing to advance until there are people or live quests in the world.
        if not state.npcs and not any(q.status == "active" for q in state.quests):
            return
        gap = state.session_turn - state.last_world_tick_turn
        if gap < WORLD_TICK_MIN_GAP or (gap < WORLD_TICK_EVERY and not event):
            return
        state.last_world_tick_turn = state.session_turn  # steady cadence even if it fails
        world_tick_busy[0] = True
        synopsis = state.synopsis
        facts_block = "\n".join(
            f"- {f.text}" + (f" ({f.location})" if f.location else "")
            for f in state.world_facts)
        npcs_block = "\n".join(
            f"- {r.id} | {r.name} [{r.role or 'unknown'}] | at {r.location or 'unknown'} | "
            f"disposition {r.disposition}" + (f" | {r.facts[-1]}" if r.facts else "")
            for r in state.npcs.values())
        quests_block = "\n".join(
            f"- {q.id} | {q.title}" + (f" | {q.stages[-1]}" if q.stages else "")
            for q in state.quests if q.status == "active")
        recent_block = "\n".join(hot_context[-6:])

        def job():
            try:
                tick = run_world_tick(client, synopsis, facts_block, npcs_block,
                                      quests_block, recent_block, config.MODEL_SUMMARY,
                                      session_stats)
                if tick and tick.developments:
                    world_tick_queue.put(tick)
            finally:
                world_tick_busy[0] = False

        threading.Thread(target=job, daemon=True).start()

    # main loop
    while ui.running:
        player_input = ui.get_input()
        if not ui.running:
            break

        _drain_chronicle()   # fold in any chapter the chronicler finished
        _drain_world_tick()  # fold in any offscreen developments the director made

        # Esc during play opens the pause menu rather than quitting.
        if player_input == PAUSE_SENTINEL:
            action = pause_menu(ui, state)
            if action == "quit":
                _save_and_quit(ui, state, hot_context, current_slot)
                break
            if action == "menu":
                _save_to_menu(ui, state, hot_context, current_slot)
                return "menu"  # back to the opening menu, session intact
            continue

        if player_input.lower() in ("quit", "exit", "/quit", "/exit"):
            _save_and_quit(ui, state, hot_context, current_slot)
            break

        # If set, pins the beat for this turn instead of guessing it from the words.
        forced_beat = None

        # EVERY command starts with "/", so ordinary prose ("I check the inventory")
        # can never trip a read-out. Non-slash input always becomes an LLM turn.
        if player_input.startswith("/"):
            cmd = player_input[1:].strip()
            low = cmd.lower()
            # /use of a *narrative* item plays as a real turn (the LLM narrates it),
            # so it falls through to the turn handler below instead of continuing.
            if low.split()[:1] == ["use"]:
                result = handle_local_command(cmd, state)
                if result is PLAY_AS_ACTION:
                    player_input = cmd  # e.g. "use the torch" -> played as an action
                    forced_beat = "item"  # give item use its own director's note
                else:
                    ui.add_player_input(player_input)
                    ui.add_system(result if isinstance(result, str) else "Nothing happens.")
                    continue
            else:
                ui.add_player_input(player_input)
                if low in ("settings", "options", "config"):
                    settings_menu(ui)
                elif low in ("theme", "themes"):
                    _theme_picker(ui)
                elif low in ("journal", "diary", "journey"):
                    journal_menu(ui, state)
                elif low in ("export", "book"):
                    _export_book(ui, state)
                elif low in ("tutorial", "tutorials", "howto", "how to play"):
                    show_tutorial(ui)
                elif low in ("help", "commands", "?", ""):
                    ui.add_panel("Commands", COMMANDS_HELP)
                else:
                    result = handle_local_command(cmd, state)
                    if isinstance(result, str):
                        if "\n" in result:  # multi-line read-outs get a card
                            title, _, body = result.partition("\n")
                            ui.add_panel(title, body)
                        else:
                            ui.add_system(result)
                    else:
                        ui.add_system(f"Unknown command: /{cmd}. Type /help for the list.")
                continue

        ui.add_player_input(player_input)

        # Once the recent-turn history gets long, roll the oldest turns up into the
        # running "story so far" summary and keep a good number of recent turns in
        # full. Recent turns kept word-for-word matter most for keeping the story
        # straight, and the extra text is cheap on a small model.
        if len(hot_context) > 16:
            evicted = hot_context[:6]
            state.synopsis = update_synopsis(client, state.synopsis, evicted, config.MODEL_SUMMARY, session_stats)
            hot_context = hot_context[6:]

        ui.start_loading()

        # Stream the narrative: the first delta swaps the spinner for live text;
        # the (invisible) state JSON streams after the prose. on_delta fires on the
        # game thread, and the UI methods take the render lock.
        on_delta, streamed = _streaming_sink(ui)
        response = call_llm(client, system_prompt, state, hot_context[-10:], player_input,
                            config.MODEL_NARRATIVE, session_stats, on_delta=on_delta,
                            force_situation=forced_beat)
        state.apply_state_changes(response.state_changes)

        ui.stop_loading()  # no-op if a delta already cleared it

        # refresh highlight context, tooltips, and the status bar
        _refresh_ui(ui, state)

        area_intro = response.state_changes.location_is_new
        if streamed[0]:
            ui.end_narrative_stream(response.narrative, area_intro=area_intro)
        else:  # no deltas arrived (e.g. instant/empty stream) — render normally
            ui.add_narrative(response.narrative, area_intro=area_intro)
        _debug_log(state.session_turn, player_input, response.narrative)

        # Record the turn in memory BEFORE resolving any combat it triggered, so the
        # transcript stays chronological and a defeat aftermath can see this turn.
        hot_context.append(
            f"[Turn {state.session_turn}] Player: {player_input} | {response.narrative}"
        )

        # async log writing
        snapshot = {
            "session_turn": state.session_turn,
            "location": state.location,
            "time_label": state._time_label(),
        }
        threading.Thread(target=process_response, args=(response, snapshot), daemon=True).start()

        if response.state_changes.combat_triggered:
            enc = response.state_changes.encounter
            combat_result = run_combat_ui(ui, state, enc)
            _debug_log(state.session_turn, "[combat]", f"Result: {combat_result['result']} | {', '.join(combat_result['log'])}")
            if combat_result["result"] == "defeat":
                _handle_defeat(ui, client, system_prompt, state, hot_context, current_slot)
            else:
                hot_context.append(f"[Combat] {', '.join(combat_result['log'])}")
            _refresh_ui(ui, state)  # HP/gear may have changed in the fight

        # Autosave to the active slot so a crash or close never loses a turn.
        save_game(state, hot_context, current_slot)

        # Maybe kick off a background journal chapter for the recent arc — sooner
        # when something noteworthy landed this turn (a new place, a quest beat, a fight).
        sc = response.state_changes
        significant_event = bool(
            sc.location_is_new
            or sc.quest_added
            or (sc.quest_updated and sc.quest_updated.status in ("completed", "failed"))
            or sc.combat_triggered
        )
        _maybe_chronicle(event=significant_event)
        # Let the world move when time passes (travel, rest) or on the soft cadence.
        _maybe_world_tick(event=sc.action_type in ("medium", "long"))


# ── new game ──────────────────────────────────────────────────────────────────

def new_game(ui: GameUI, client, system_prompt) -> tuple:
    global session_stats
    session_stats = SessionStats()
    _debug_log_clear()

    ui.add_system("Welcome. (New here? Type /tutorial any time for a quick tour.)\n")

    ui.add_system("Name:")
    name = ui.get_input(allow_empty=True)
    if not ui.running:
        return None, None
    if name.strip().lower() in ("quit", "exit"):
        ui.running = False
        return None, None
    name = name.strip() or "Wanderer"
    ui.add_player_input(name)

    ui.add_system("Background (leave blank to randomize):")
    background = ui.get_input(allow_empty=True)
    if not ui.running:
        return None, None
    if background.strip().lower() in ("quit", "exit"):
        ui.running = False
        return None, None
    background = background.strip() or "unknown wanderer, generate something fitting the world"
    ui.add_player_input(background)

    ui.add_system(
        "Tone & voice — in your own words, how should this story be told?\n"
        "Anything goes: \"grim and sparse\", \"wry, warm, a little absurd\",\n"
        "\"lush and dreamlike\", \"hardboiled noir\". This is the voice the whole\n"
        "game will be written in. Leave blank for the default."
    )
    tone = ui.get_input(allow_empty=True)
    if not ui.running:
        return None, None
    if tone.strip().lower() in ("quit", "exit"):
        ui.running = False
        return None, None
    tone = tone.strip() or "no preference — use your strongest, most fitting voice"
    ui.add_player_input(tone)

    player = PlayerCharacter(name=name, background=background, tone=tone)
    state = EngineState(player=player)
    hot_context = []

    ui.set_context(name, [], [], [])
    ui.add_system("Generating world...")

    # Stream the opening scene live — it's the first impression, so don't make the
    # player wait on a blank spinner for the whole thing.
    ui.start_loading()
    on_delta, streamed = _streaming_sink(ui)
    seed_response = call_llm(
        client, system_prompt, state, [], SEED_INSTRUCTION,
        config.MODEL_NARRATIVE, session_stats, on_delta=on_delta,
    )
    ui.stop_loading()
    state.apply_state_changes(seed_response.state_changes)
    write_world_seed(seed_response.narrative, state)
    snapshot = {
        "session_turn": state.session_turn,
        "location": state.location,
        "time_label": state._time_label(),
    }
    threading.Thread(target=process_response, args=(seed_response, snapshot), daemon=True).start()

    _refresh_ui(ui, state)
    if streamed[0]:
        ui.end_narrative_stream(seed_response.narrative, area_intro=True)
    else:
        ui.add_narrative(seed_response.narrative, area_intro=True)
    hot_context.append(f"[Scene]: {seed_response.narrative}")

    return state, hot_context


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    from game.ui import apply_theme
    apply_theme(config.UI_THEME)
    ui = GameUI()

    def safe_game_thread():
        try:
            # game_thread returns "menu" when the player picks Save & main menu;
            # loop so they land back on the opening menu instead of exiting.
            while ui.running and game_thread(ui) == "menu":
                pass
        except Exception:
            import traceback
            traceback.print_exc()
            ui.running = False
            ui._release_all_waiters()

    thread = threading.Thread(target=safe_game_thread, daemon=True)
    thread.start()

    while ui.running:
        dt = ui.clock.tick(60) / 1000.0
        ui.handle_events()
        ui.tick(dt)
        ui.render()

    pygame.quit()


if __name__ == "__main__":
    main()
