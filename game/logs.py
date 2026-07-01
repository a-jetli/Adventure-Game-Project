import os
import json
import threading
from datetime import datetime
from .schema import LLMResponse
from .engine import (
    EngineState, PlayerCharacter, WeaponData, ArmorData, ConsumableData,
    TrinketData, QuestData, ActiveBuff, NPCRecord, WorldFact,
)

FILE_LOCK = threading.RLock()


# ── data root (per-session isolation) ──────────────────────────────────────────
# Every save/log/book/stat path derives from a single root. It defaults to ./logs
# (unchanged for local desktop play), but the web demo launches each browser session
# in its own process with a unique GAME_DATA_DIR (e.g. sessions/<uuid>/), so two
# visitors never collide and one can't read another's saves. `set_data_dir()` lets a
# host (or a test) repoint the whole tree at runtime; all module globals below are
# reassigned, and every function reads them live, so the switch is total.

def set_data_dir(root: str) -> None:
    """Point all save/log/book/stat paths at `root`. Reassigns the module globals so
    functions here (and `logs.X` references elsewhere) pick up the new location."""
    global DATA_DIR, LOGS_DIR, REGIONS_DIR, NPCS_DIR, EVENTS_DIR, WORLD_FILE
    global SESSION_FILE, SAVE_FILE, SAVES_DIR, BOOKS_DIR, DEBUG_FILE, STATS_FILE
    DATA_DIR = LOGS_DIR = root
    REGIONS_DIR = os.path.join(root, "regions")
    NPCS_DIR = os.path.join(root, "npcs")
    EVENTS_DIR = os.path.join(root, "events")
    WORLD_FILE = os.path.join(root, "world.md")
    SESSION_FILE = os.path.join(root, "session.md")
    SAVE_FILE = os.path.join(root, "save.json")    # legacy single-slot path
    SAVES_DIR = os.path.join(root, "saves")         # one file per named slot
    BOOKS_DIR = os.path.join(root, "books")         # exported, human-readable books
    DEBUG_FILE = os.path.join(root, "debug_narrative.txt")  # used by game/driver.py
    STATS_FILE = os.path.join(root, "session_stats.json")   # used by game/stats.py


# Resolve the root once at import from the environment (default ./logs). For the web
# demo, set GAME_DATA_DIR per connection before launching the process.
set_data_dir(os.environ.get("GAME_DATA_DIR", "logs"))


def init_logs():
    for directory in [LOGS_DIR, REGIONS_DIR, NPCS_DIR, EVENTS_DIR, SAVES_DIR, BOOKS_DIR]:
        os.makedirs(directory, exist_ok=True)


def write_world_seed(narrative: str, state: EngineState):
    with FILE_LOCK:
        with open(WORLD_FILE, "w") as f:
            f.write("# World Log\n\n")
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


def update_region_gist(location: str, gist: str):
    """Maintain a one-line `**Gist:**` description near the top of a region's
    log file, rewritten in place when it changes. Skips if the region file
    doesn't exist yet (the in-memory state still carries the gist for tooltips)."""
    if not gist:
        return
    filepath = os.path.join(REGIONS_DIR, _slugify(location) + ".md")
    line = f"**Gist:** {gist.strip()}"
    with FILE_LOCK:
        if not os.path.exists(filepath):
            return
        lines = open(filepath, "r").read().splitlines()
        for i, l in enumerate(lines):
            if l.startswith("**Gist:**"):
                if lines[i] == line:
                    return  # unchanged
                lines[i] = line
                break
        else:
            title_idx = next((i for i, l in enumerate(lines) if l.startswith("# ")), 0)
            lines.insert(title_idx + 1, line)
        with open(filepath, "w") as f:
            f.write("\n".join(lines) + "\n")


def write_npc(npc_id: str, name: str, narrative: str, state_snapshot: dict):
    filename = _slugify(npc_id) + ".md"
    filepath = os.path.join(NPCS_DIR, filename)
    session_turn = state_snapshot["session_turn"]
    location = state_snapshot["location"]
    with FILE_LOCK:
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                f.write(f"# {name} ({npc_id})\n\n")
                f.write(f"**First encountered:** Turn {session_turn} | {location}\n\n")
                f.write(f"## First Encounter\n\n{narrative}\n")
        else:
            with open(filepath, "a") as f:
                f.write(f"\n## Turn {session_turn} | {location}\n\n{narrative}\n")


def append_world_facts(facts, state_snapshot: dict):
    """Append newly recorded world facts to a human-readable section of the
    world log. facts is the list of WorldFactItem from the response."""
    if not facts:
        return
    session_turn = state_snapshot["session_turn"]
    with FILE_LOCK:
        with open(WORLD_FILE, "a") as f:
            for wf in facts:
                scope = wf.location or "world"
                f.write(f"- [{scope}] {wf.text} (turn {session_turn})\n")


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

    for upd in changes.npcs:
        if upd.present:
            write_npc(upd.id, upd.name or upd.id, response.narrative, state_snapshot)

    append_world_facts(changes.world_facts_add, state_snapshot)

    if changes.location_summary:
        loc = changes.location or state_snapshot.get("location")
        if loc and loc != "unknown":
            update_region_gist(loc, changes.location_summary)

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


def _slot_path(slot: str) -> str:
    return os.path.join(SAVES_DIR, _slugify(slot) + ".json")


def _state_to_dict(state: EngineState, hot_context: list[str]) -> dict:
    data = {
        "player": {
            "name": state.player.name,
            "background": state.player.background,
            "tone": state.player.tone,
            "setting": state.player.setting,
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
        "npcs": {
            npc_id: {
                "id": r.id, "name": r.name, "role": r.role, "location": r.location,
                "disposition": r.disposition, "description": r.description,
                "voice": r.voice, "facts": r.facts, "last_seen_turn": r.last_seen_turn,
            }
            for npc_id, r in state.npcs.items()
        },
        "world_facts": [
            {"text": f.text, "location": f.location, "turn": f.turn}
            for f in state.world_facts
        ],
        "location_types": state.location_types,
        "location_graph": state.location_graph,
        "location_descriptions": state.location_descriptions,
        "synopsis": state.synopsis,
        "journal": state.journal,
        "last_chronicle_turn": state.last_chronicle_turn,
        "last_world_tick_turn": state.last_world_tick_turn,
        "session_turn": state.session_turn,
        "active_npc": state.active_npc,
        "npc_idle_turns": state.npc_idle_turns,
        "hot_context": hot_context
    }
    return data


def save_game(state: EngineState, hot_context: list[str], slot: str = "autosave"):
    os.makedirs(SAVES_DIR, exist_ok=True)
    data = _state_to_dict(state, hot_context)
    data["slot_name"] = slot
    data["saved_at"] = datetime.now().isoformat()
    with FILE_LOCK:
        with open(_slot_path(slot), "w") as f:
            json.dump(data, f, indent=2)


def _resolve_slot_path(slot: str) -> str | None:
    """Path to a slot's file, falling back to the legacy single save for the
    default slots so old saves keep loading."""
    path = _slot_path(slot)
    if os.path.exists(path):
        return path
    if slot in ("autosave", "save") and os.path.exists(SAVE_FILE):
        return SAVE_FILE
    return None


def list_saves() -> list[dict]:
    """Metadata for every save slot, newest first. Includes a legacy
    logs/save.json as the 'save' slot if present."""
    entries = []
    seen_paths = set()

    def _meta(slot: str, path: str):
        try:
            with open(path, "r") as f:
                d = json.load(f)
        except Exception:
            return None
        return {
            "slot": slot,
            "name": d.get("slot_name") or d.get("player", {}).get("name", slot),
            "player": d.get("player", {}).get("name", "?"),
            "location": d.get("location", "?"),
            "turn": d.get("session_turn", 0),
            "saved_at": d.get("saved_at", ""),
            "path": path,
        }

    with FILE_LOCK:
        if os.path.isdir(SAVES_DIR):
            for fn in sorted(os.listdir(SAVES_DIR)):
                if fn.endswith(".json"):
                    path = os.path.join(SAVES_DIR, fn)
                    m = _meta(fn[:-5], path)
                    if m:
                        entries.append(m)
                        seen_paths.add(os.path.abspath(path))
        if os.path.exists(SAVE_FILE) and os.path.abspath(SAVE_FILE) not in seen_paths:
            m = _meta("save", SAVE_FILE)
            if m:
                entries.append(m)

    entries.sort(key=lambda e: e["saved_at"], reverse=True)
    return entries


def delete_save(slot: str) -> bool:
    with FILE_LOCK:
        path = _slot_path(slot)
        if os.path.exists(path):
            os.remove(path)
            return True
        # legacy
        if slot in ("autosave", "save") and os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
            return True
        return False


def load_game(slot: str = "autosave") -> tuple[EngineState, list[str]] | None:
    with FILE_LOCK:
        path = _resolve_slot_path(slot)
        if path is None:
            return None
        with open(path, "r") as f:
            data = json.load(f)

        player = PlayerCharacter(
            name=data["player"]["name"],
            background=data["player"]["background"],
            tone=data["player"]["tone"],
            setting=data["player"].get("setting", ""),  # old saves predate settings
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

        active_npc = data.get("active_npc")
        if "npcs" in data:
            npcs = {
                npc_id: NPCRecord(
                    id=r["id"], name=r["name"], role=r.get("role", ""),
                    location=r.get("location"), disposition=r.get("disposition", 0),
                    description=r.get("description", ""), voice=r.get("voice", ""),
                    facts=r.get("facts", []), last_seen_turn=r.get("last_seen_turn", 0),
                )
                for npc_id, r in data["npcs"].items()
            }
        else:
            # For older saves: convert the old simple {name: how-they-feel} map into
            # full NPC records, each keyed by an id made from the name.
            npcs = {}
            for name, disp in data.get("npc_relationships", {}).items():
                npc_id = _slugify(name)
                npcs[npc_id] = NPCRecord(id=npc_id, name=name, disposition=disp)
            if active_npc:
                active_npc = _slugify(active_npc)

        world_facts = [
            WorldFact(text=f["text"], location=f.get("location"), turn=f.get("turn", 0))
            for f in data.get("world_facts", [])
        ]
        location_types = data.get("location_types", {})
        location_graph = data.get("location_graph", {})
        location_descriptions = data.get("location_descriptions", {})

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
            npcs=npcs,
            world_facts=world_facts,
            location_types=location_types,
            location_graph=location_graph,
            location_descriptions=location_descriptions,
            synopsis=data.get("synopsis", ""),
            journal=data.get("journal", []),
            last_chronicle_turn=data.get("last_chronicle_turn", 0),
            last_world_tick_turn=data.get("last_world_tick_turn", 0),
            session_turn=data["session_turn"],
            active_npc=active_npc,
            npc_idle_turns=data.get("npc_idle_turns", 0)
        )

        hot_context = data["hot_context"]
        return state, hot_context


def _slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "_").replace("/", "_").replace("-", "_")


def export_book(state) -> str:
    """Compile the player's journal into a keepable Markdown 'book' and return the
    path written. The journal chapters are already chronological (the chronicler
    appends in turn order); the synopsis and world facts become a short appendix.
    Pure read of state -> one file write; no engine coupling."""
    os.makedirs(BOOKS_DIR, exist_ok=True)
    name = state.player.name or "Wanderer"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BOOKS_DIR, f"{_slugify(name)}_{ts}.md")

    lines = [
        f"# {name}'s Tale",
        "",
        f"*A chronicle set down across {state.session_turn} turns of play, "
        f"{datetime.now().strftime('%Y-%m-%d')}.*",
    ]
    if state.journal:
        for ch in state.journal:
            title = (ch.get("title") or "Untitled").strip()
            text = (ch.get("text") or "").strip()
            lines += ["", "", f"## {title}", "", text]
    else:
        lines += ["", "", "*The journal is empty yet — play on, and your story will "
                  "fill these pages.*"]

    synopsis = (state.synopsis or "").strip()
    if synopsis:
        lines += ["", "", "---", "", "## Epilogue — the story so far", "", synopsis]

    if state.world_facts:
        lines += ["", "", "---", "", "## Deeds left upon the world", ""]
        for f in state.world_facts:
            scope = f.location or "the world"
            lines.append(f"- {f.text} *({scope})*")

    with FILE_LOCK:
        with open(path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
    return path