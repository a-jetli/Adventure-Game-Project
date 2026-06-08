import os
import json
import threading
from datetime import datetime
from .schema import LLMResponse
from .engine import EngineState, PlayerCharacter, WeaponData, ArmorData, ConsumableData, TrinketData, QuestData, ActiveBuff

FILE_LOCK = threading.RLock()


LOGS_DIR = "logs"
REGIONS_DIR = os.path.join(LOGS_DIR, "regions")
NPCS_DIR = os.path.join(LOGS_DIR, "npcs")
EVENTS_DIR = os.path.join(LOGS_DIR, "events")
WORLD_FILE = os.path.join(LOGS_DIR, "world.md")
SESSION_FILE = os.path.join(LOGS_DIR, "session.md")
SAVE_FILE = os.path.join(LOGS_DIR, "save.json")


def init_logs():
    for directory in [LOGS_DIR, REGIONS_DIR, NPCS_DIR, EVENTS_DIR]:
        os.makedirs(directory, exist_ok=True)


def write_world_seed(narrative: str, state: EngineState):
    with FILE_LOCK:
        with open(WORLD_FILE, "w") as f:
            f.write(f"# World Log\n\n")
            f.write(f"**Player:** {state.player.name} | {state.player.background}\n")
            f.write(f"**Session started:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"## Opening\n\n{narrative}\n")


def write_region(location: str, narrative: str, state_snapshot: dict):
    filename = _slugify(location) + ".md"
    filepath = os.path.join(REGIONS_DIR, filename)
    session_turn = state_snapshot["session_turn"]
    time_label = state_snapshot["time_label"]
    with FILE_LOCK:
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(f"# {location}\n\n")
                f.write(f"**First visited:** Turn {session_turn} | {time_label}\n\n")
                f.write(f"## Discovery\n\n{narrative}\n")
        else:
            with open(filepath, "a") as f:
                f.write(f"\n## Turn {session_turn} | {time_label}\n\n{narrative}\n")


def write_npc(npc_id: str, narrative: str, state_snapshot: dict):
    filename = _slugify(npc_id) + ".md"
    filepath = os.path.join(NPCS_DIR, filename)
    session_turn = state_snapshot["session_turn"]
    location = state_snapshot["location"]
    with FILE_LOCK:
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(f"# {npc_id}\n\n")
                f.write(f"**First encountered:** Turn {session_turn} | {location}\n\n")
                f.write(f"## First Encounter\n\n{narrative}\n")
        else:
            with open(filepath, "a") as f:
                f.write(f"\n## Turn {session_turn} | {location}\n\n{narrative}\n")


def write_event(narrative: str, state_snapshot: dict):
    session_turn = state_snapshot["session_turn"]
    location = state_snapshot["location"]
    time_label = state_snapshot["time_label"]
    filename = f"turn_{session_turn:04d}.md"
    filepath = os.path.join(EVENTS_DIR, filename)
    with FILE_LOCK:
        with open(filepath, "w") as f:
            f.write(f"# Event — Turn {session_turn}\n\n")
            f.write(f"**Location:** {location} | **Time:** {time_label}\n\n")
            f.write(f"{narrative}\n")


def save_session(hot_context: list[str], state: EngineState):
    with FILE_LOCK:
        with open(SESSION_FILE, "w") as f:
            f.write("# Session Log\n\n")
            f.write("## Engine State\n\n")
            f.write(f"```\n{state.to_prompt_string()}\n```\n\n")
            f.write("## Context\n\n")
            for line in hot_context:
                f.write(f"{line}\n\n")


def process_response(response: LLMResponse, state_snapshot: dict):
    changes = response.state_changes

    if changes.location and changes.location_is_new:
        write_region(changes.location, response.narrative, state_snapshot)
    elif changes.location and not changes.location_is_new:
        if changes.new_log_needed:
            write_region(changes.location, response.narrative, state_snapshot)

    if changes.npc_encountered:
        write_npc(changes.npc_encountered, response.narrative, state_snapshot)

    if changes.new_log_needed and not changes.location:
        write_event(response.narrative, state_snapshot)


def load_region(location: str) -> str | None:
    filename = _slugify(location) + ".md"
    filepath = os.path.join(REGIONS_DIR, filename)
    with FILE_LOCK:
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return f.read()
    return None


def load_npc(npc_id: str) -> str | None:
    filename = _slugify(npc_id) + ".md"
    filepath = os.path.join(NPCS_DIR, filename)
    with FILE_LOCK:
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return f.read()
    return None


def save_game(state: EngineState, hot_context: list[str]):
    data = {
        "player": {
            "name": state.player.name,
            "background": state.player.background,
            "tone": state.player.tone
        },
        "location": state.location,
        "time_of_day": state.time_of_day,
        "hp": state.hp,
        "max_hp": state.max_hp,
        "weapons": [
            {"name": w.name, "damage_range": w.damage_range, "description": w.description}
            for w in state.weapons
        ],
        "armor": [
            {"name": a.name, "armor_value": a.armor_value, "description": a.description}
            for a in state.armor
        ],
        "consumables": [
            {"name": c.name, "effect": c.effect, "description": c.description}
            for c in state.consumables
        ],
        "trinkets": [
            {"name": t.name, "description": t.description}
            for t in state.trinkets
        ],
        "quests": [
            {"id": q.id, "title": q.title, "description": q.description,
             "status": q.status, "stages": q.stages}
            for q in state.quests
        ],
        "buffs": [
            {"kind": b.kind, "amount": b.amount, "rounds_left": b.rounds_left}
            for b in state.buffs
        ],
        "equipped_weapon": {
            "name": state.equipped_weapon.name,
            "damage_range": state.equipped_weapon.damage_range,
            "description": state.equipped_weapon.description
        },
        "equipped_armor": {
            "name": state.equipped_armor.name,
            "armor_value": state.equipped_armor.armor_value,
            "description": state.equipped_armor.description
        },
        "visited_locations": state.visited_locations,
        "npc_relationships": state.npc_relationships,
        "session_turn": state.session_turn,
        "active_npc": state.active_npc,
        "npc_idle_turns": state.npc_idle_turns,
        "hot_context": hot_context
    }
    with FILE_LOCK:
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f, indent=2)


def load_game() -> tuple[EngineState, list[str]] | None:
    with FILE_LOCK:
        if not os.path.exists(SAVE_FILE):
            return None
        with open(SAVE_FILE, "r") as f:
            data = json.load(f)

        player = PlayerCharacter(
            name=data["player"]["name"],
            background=data["player"]["background"],
            tone=data["player"]["tone"]
        )

        weapons = [
            WeaponData(name=w["name"], damage_range=w["damage_range"], description=w.get("description", ""))
            for w in data.get("weapons", [])
        ]
        armor = [
            ArmorData(name=a["name"], armor_value=a["armor_value"], description=a.get("description", ""))
            for a in data.get("armor", [])
        ]
        consumables = [
            ConsumableData(name=c["name"], effect=c["effect"], description=c.get("description", ""))
            for c in data.get("consumables", [])
        ]
        trinkets = [
            TrinketData(name=t["name"], description=t.get("description", ""))
            for t in data.get("trinkets", [])
        ]
        quests = [
            QuestData(id=q["id"], title=q["title"], description=q["description"],
                      status=q.get("status", "active"), stages=q.get("stages", []))
            for q in data.get("quests", [])
        ]
        buffs = [
            ActiveBuff(kind=b["kind"], amount=b["amount"], rounds_left=b["rounds_left"])
            for b in data.get("buffs", [])
        ]

        eq_w = data.get("equipped_weapon", {"name": "fists", "damage_range": 4, "description": ""})
        eq_a = data.get("equipped_armor", {"name": "none", "armor_value": 0, "description": ""})

        state = EngineState(
            player=player,
            location=data["location"],
            time_of_day=data["time_of_day"],
            hp=data["hp"],
            max_hp=data["max_hp"],
            weapons=weapons,
            armor=armor,
            consumables=consumables,
            trinkets=trinkets,
            equipped_weapon=WeaponData(name=eq_w["name"], damage_range=eq_w["damage_range"], description=eq_w.get("description", "")),
            equipped_armor=ArmorData(name=eq_a["name"], armor_value=eq_a["armor_value"], description=eq_a.get("description", "")),
            quests=quests,
            buffs=buffs,
            visited_locations=data["visited_locations"],
            npc_relationships=data["npc_relationships"],
            session_turn=data["session_turn"],
            active_npc=data.get("active_npc"),
            npc_idle_turns=data.get("npc_idle_turns", 0)
        )

        hot_context = data["hot_context"]
        return state, hot_context


def wipe_save() -> bool:
    with FILE_LOCK:
        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
            return True
        return False


def _slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "_").replace("/", "_").replace("-", "_")