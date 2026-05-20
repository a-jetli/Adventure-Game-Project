import os
import re
import random
import threading
import time
import pygame
from dotenv import load_dotenv
from openai import OpenAI
from schema import LLMResponse
from engine import EngineState, PlayerCharacter
from stats import SessionStats, CallRecord
from logs import (
    init_logs, write_world_seed, process_response,
    save_session, save_game, load_game, load_region, load_npc, wipe_save,
)
from ui import GameUI
from game_logic import handle_local_command, call_llm, summarize_context


load_dotenv()
session_stats = SessionStats()


MODEL_NARRATIVE = "gpt-5.4-nano"
MODEL_SUMMARY = "gpt-4o-mini"
DEBUG_LOG = "logs/debug_narrative.txt"


# ── debug logging ─────────────────────────────────────────────────────────────

def _debug_log_clear():
    os.makedirs("logs", exist_ok=True)
    with open(DEBUG_LOG, "w") as f:
        f.write("")


def _debug_log(turn: int, player_input: str, narrative: str):
    with open(DEBUG_LOG, "a") as f:
        f.write(f"\n--- Turn {turn} ---\n")
        f.write(f"INPUT: {player_input}\n")
        f.write(f"OUTPUT: {narrative}\n")


# ── LLM calls ─────────────────────────────────────────────────────────────────

def load_system_prompt() -> str:
    with open("system_prompt.md", "r") as f:
        return f.read()





# ── helpers ───────────────────────────────────────────────────────────────────

def _format_inventory_display(state: EngineState) -> str:
    def names(parts):
        return ", ".join(parts) if parts else "none"

    lines = [
        "Inventory",
        "Equipment:",
        f"- Weapon: {state.equipped_weapon.name} (1-{state.equipped_weapon.damage_range} dmg)",
        f"- Armor:  {state.equipped_armor.name} ({state.equipped_armor.armor_value} armor)",
        "Bag:",
        f"- Weapons: {names([w.name for w in state.weapons])}",
        f"- Armor: {names([a.name for a in state.armor])}",
        f"- Consumables: {names([c.name for c in state.consumables])}",
        f"- Trinkets: {names([t.name for t in state.trinkets])}",
    ]
    return "\n".join(lines)


def _known_npcs_for_ui(state: EngineState) -> list[str]:
    npcs = []
    if state.active_npc:
        npcs.append(state.active_npc)
    for npc_name in state.npc_relationships.keys():
        if npc_name and npc_name not in npcs:
            npcs.append(npc_name)
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


# ── local commands ────────────────────────────────────────────────────────────



# ── opening menu ──────────────────────────────────────────────────────────────

def opening_menu(ui: GameUI, has_save: bool) -> str:
    while ui.running:
        subtitle = "Choose an option to begin."
        if not has_save:
            subtitle = "No save file found. Start a new game."
        choice = ui.show_menu(
            "THE GAME",
            [
                ("New game", "new"),
                ("Load file", "load"),
                ("Wipe save", "wipe"),
            ],
            subtitle=subtitle,
        )
        if not ui.running:
            return "quit"

        if choice == "new":
            ui.add_system("Starting new game...")
            return "new"

        if choice == "load":
            if has_save:
                ui.add_system("Loading save file...")
                return "load"
            ui.add_system("No save file found.")
            continue

        if choice == "wipe":
            if not has_save:
                ui.add_system("No save file to wipe.")
                continue
            confirm = ui.show_menu(
                "Confirm Wipe",
                [("Yes, wipe save", "confirm_wipe"), ("Cancel", "cancel_wipe")],
                subtitle="This deletes logs/save.json.",
            )
            if confirm == "confirm_wipe":
                wipe_save()
                ui.add_system("Save file wiped.")
                has_save = False
            else:
                ui.add_system("Wipe canceled.")
            continue

        if choice in ("quit", "exit"):
            return "quit"

    return "quit"


# ── combat ────────────────────────────────────────────────────────────────────

from combat import CombatInterface, run_combat

class GUICombatInterface(CombatInterface):
    def __init__(self, ui: GameUI, enemy_type: str):
        self.ui = ui
        self.enemy_type = enemy_type

    def show_intro(self, enemy_type: str):
        self.ui.begin_combat_intro(f"COMBAT — {enemy_type}", flashes=1, interval=0.18)
        self.ui.wait_for_combat_intro()

    def log(self, message: str):
        self.ui.add_combat_text(message)

    def choose_action(self, state: EngineState, alive_enemies: list[dict]) -> str:
        status_lines = [
            (f"You: {state.hp}/{state.max_hp} HP", (210, 210, 205)),
            (f"Weapon: {state.equipped_weapon.name} ({state.equipped_weapon.damage_range} dmg)", (140, 180, 120)),
            (f"Armor: {state.equipped_armor.name} ({state.equipped_armor.armor_value})", (100, 160, 180)),
        ]
        status_lines.append(("Enemies:", (205, 110, 110)))
        for e in alive_enemies:
            status_lines.append((f"  {e['name']}: {e['hp']}/{e['max_hp']} | A {e['armor']}", (205, 110, 110)))

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
            (f"You: {state.hp}/{state.max_hp} HP", (210, 210, 205)),
            ("Consumables:", (140, 180, 120)),
        ]
        for item in usable:
            item_lines.append((f"  {item.name} [{_consumable_effect_label(item.effect)}]", (140, 180, 120)))

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
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    system_prompt = load_system_prompt()

    existing_save = load_game()
    menu_choice = opening_menu(ui, has_save=existing_save is not None)
    if menu_choice == "quit" or not ui.running:
        ui.running = False
        return

    if menu_choice == "load":
        existing_save = load_game()
        if existing_save:
            state, hot_context = existing_save
            ui.set_context(
                state.player.name,
                state.visited_locations,
                _all_items_for_ui(state),
                _known_npcs_for_ui(state),
            )
            ui.add_system(f"Welcome back, {state.player.name}. Turn {state.session_turn}.")
            ui.add_system(f"Location: {state.location} | HP: {state.hp}/{state.max_hp}")
            ui.add_system(_format_inventory_display(state))
        else:
            ui.add_system("No save found. Starting new game.")
            state, hot_context = new_game(ui, client, system_prompt)
    else:
        state, hot_context = new_game(ui, client, system_prompt)

    if not ui.running or state is None:
        return

    # main loop
    while ui.running:
        player_input = ui.get_input()
        if not ui.running:
            break

        if player_input.lower() in ("quit", "exit"):
            time.sleep(0.5)
            save_session(hot_context, state)
            save_game(state, hot_context)
            session_stats.flush()
            ui.add_system(session_stats.summary())
            ui.add_system("Session saved. Press any key to close.")
            ui.get_input(allow_empty=True)
            ui.running = False
            break

        local = handle_local_command(player_input, state)
        if local:
            ui.add_player_input(player_input)
            ui.add_system(local)
            continue

        ui.add_player_input(player_input)

        if len(hot_context) > 8:
            summary = summarize_context(client, hot_context, MODEL_SUMMARY, session_stats)
            hot_context = [summary] + hot_context[3:]

        ui.add_system("...")

        response = call_llm(client, system_prompt, state, hot_context[-5:], player_input, MODEL_NARRATIVE, session_stats)
        state.apply_state_changes(response.state_changes)

        # remove loading indicator
        ui.remove_loading_indicator()

        # update highlighting context
        ui.set_context(
            state.player.name,
            state.visited_locations,
            _all_items_for_ui(state),
            _known_npcs_for_ui(state),
        )

        ui.add_narrative(response.narrative)
        _debug_log(state.session_turn, player_input, response.narrative)

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
                ui.add_combat_text("You have fallen.")
                save_session(hot_context, state)
                session_stats.flush()
                ui.add_system(session_stats.summary())
                ui.add_system("Press any key to close.")
                ui.get_input(allow_empty=True)
                ui.running = False
                break
            hot_context.append(f"[Combat] {', '.join(combat_result['log'])}")


        hot_context.append(
            f"[Turn {state.session_turn}] Player: {player_input} | {response.narrative}"
        )


# ── new game ──────────────────────────────────────────────────────────────────

def new_game(ui: GameUI, client, system_prompt) -> tuple:
    global session_stats
    from stats import SessionStats
    session_stats = SessionStats()
    _debug_log_clear()

    ui.add_system("Welcome.\n")

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

    ui.add_system("Preferred tone — grim / whimsical / neutral:")
    tone = ui.get_input(allow_empty=True)
    if not ui.running:
        return None, None
    if tone.strip().lower() in ("quit", "exit"):
        ui.running = False
        return None, None
    tone = tone.strip() or "neutral"
    ui.add_player_input(tone)

    player = PlayerCharacter(name=name, background=background, tone=tone)
    state = EngineState(player=player)
    hot_context = []

    ui.set_context(name, [], [], [])
    ui.add_system("Generating world...")

    seed_response = call_llm(
        client, system_prompt, state, [],
        "Begin. Generate the opening scene. Do not reference the player's past — this is the very first moment. Seed one concrete story thread: a rumor, a visible landmark with implied history, a distant event the player can hear or see evidence of, or a clear sign that something happened here recently. Give the player something to pursue without telling them to pursue it.",
        MODEL_NARRATIVE, session_stats
    )
    state.apply_state_changes(seed_response.state_changes)
    write_world_seed(seed_response.narrative, state)
    snapshot = {
        "session_turn": state.session_turn,
        "location": state.location,
        "time_label": state._time_label(),
    }
    threading.Thread(target=process_response, args=(seed_response, snapshot), daemon=True).start()

    ui.set_context(name, state.visited_locations, _all_items_for_ui(state), _known_npcs_for_ui(state))
    ui.add_narrative(seed_response.narrative)
    hot_context.append(f"[Scene]: {seed_response.narrative}")

    return state, hot_context


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    ui = GameUI()

    def safe_game_thread():
        try:
            game_thread(ui)
        except Exception as e:
            import traceback
            traceback.print_exc()
            ui.running = False
            ui.input_ready.set()
            ui.menu_ready.set()

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
