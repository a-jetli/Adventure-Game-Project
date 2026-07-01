from dataclasses import dataclass, field


# How many combat rounds a consumable buff lasts when applied.
DEFAULT_BUFF_ROUNDS = 3

# Reverse directions, used to record the return edge in the location graph.
OPPOSITE_DIRECTION = {
    "north": "south", "south": "north", "east": "west", "west": "east",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
    "up": "down", "down": "up", "in": "out", "out": "in",
    "inside": "outside", "outside": "inside", "left": "right", "right": "left",
}


@dataclass
class ActiveBuff:
    kind: str          # "damage" or "armor"
    amount: int
    rounds_left: int


@dataclass
class WeaponData:
    name: str
    damage_range: int
    description: str = ""


@dataclass
class ArmorData:
    name: str
    armor_value: int
    description: str = ""


@dataclass
class ConsumableData:
    name: str
    effect: str
    description: str = ""


@dataclass
class TrinketData:
    name: str
    description: str = ""


@dataclass
class QuestData:
    id: str
    title: str
    description: str
    status: str = "active"
    stages: list[str] = field(default_factory=list)


@dataclass
class NPCRecord:
    """A durable, structured record of a single NPC. The id is the stable
    identity (a slug); everything else can change over time. description and
    voice anchor consistency; facts holds promises/knowledge; location is the
    engine's last knowledge of where they are (or said they'd be)."""
    id: str
    name: str
    role: str = ""
    location: str | None = None
    disposition: int = 0
    description: str = ""
    voice: str = ""
    facts: list[str] = field(default_factory=list)
    last_seen_turn: int = 0

    @property
    def label(self) -> str:
        """A human-readable handle: the real name if known, else the id with its
        hyphens spaced out — so a still-unnamed NPC shows 'ledger keeper apron
        man', never the raw 'ledger-keeper-apron-man' slug."""
        return self.name or self.id.replace("-", " ")


def _clean_npc_name(name: str | None, npc_id: str) -> str:
    """A real display name, or "" when the model handed back the id slug instead
    of a name (a recurring small-model slip). A genuine name carries a capital or
    a space; an id slug is lowercase-and-hyphenated, or just the id verbatim."""
    n = (name or "").strip()
    if not n or n == npc_id:
        return ""
    if n == n.lower() and "-" in n:
        return ""
    return n


@dataclass
class WorldFact:
    """A durable consequence of play. location scopes it to a place; None means
    it's a world-level fact surfaced everywhere."""
    text: str
    location: str | None = None
    turn: int = 0


@dataclass
class PlayerCharacter:
    name: str
    background: str
    tone: str
    setting: str = ""  # the world/genre this story lives in; blank = grounded low fantasy


@dataclass
class EngineState:
    player: PlayerCharacter
    location: str = "unknown"
    time_of_day: float = 8.0
    hp: int = 100
    max_hp: int = 100
    weapons: list[WeaponData] = field(default_factory=list)
    armor: list[ArmorData] = field(default_factory=list)
    consumables: list[ConsumableData] = field(default_factory=list)
    trinkets: list[TrinketData] = field(default_factory=list)
    equipped_weapon: WeaponData = field(default_factory=lambda: WeaponData("fists", 6))
    equipped_armor: ArmorData = field(default_factory=lambda: ArmorData("none", 0))
    quests: list[QuestData] = field(default_factory=list)
    buffs: list[ActiveBuff] = field(default_factory=list)
    visited_locations: list[str] = field(default_factory=list)
    npcs: dict[str, NPCRecord] = field(default_factory=dict)
    world_facts: list[WorldFact] = field(default_factory=list)
    location_types: dict[str, str] = field(default_factory=dict)
    location_graph: dict[str, dict[str, str]] = field(default_factory=dict)
    location_descriptions: dict[str, str] = field(default_factory=dict)  # place -> short gist
    synopsis: str = ""  # evolving "story so far" — durable campaign memory (LLM working memory)
    journal: list[dict] = field(default_factory=list)  # player-facing diary chapters: {turn,title,text}
    last_chronicle_turn: int = 0  # turn the last journal chapter was triggered at
    last_world_tick_turn: int = 0  # turn the last offscreen world tick was triggered at
    session_turn: int = 0
    turns_in_location: int = 0  # consecutive turns spent in the current place
    active_npc: str | None = None  # id of the NPC currently in focus
    npc_idle_turns: int = 0

    def advance_time(self, action_type: str):
        increments = {
            "none": 0.0,
            "short": 0.25,
            "medium": 1.0,
            "long": 4.0,
        }
        self.time_of_day = (self.time_of_day + increments.get(action_type, 0.0)) % 24.0

    # Start hour of each time-of-day band (mirror of `_time_label`'s boundaries), so the
    # narrator can jump the clock to a named time when the player waits/rests/sleeps.
    _LABEL_START_HOUR = {
        "early morning": 5.0, "morning": 8.0, "midday": 12.0, "afternoon": 14.0,
        "evening": 18.0, "night": 21.0, "deep night": 0.0,
    }

    def set_time_to_label(self, label: str):
        """Jump the clock *forward* to the start of a named time of day (waiting until
        morning, sleeping through to night). No-op for an unknown label."""
        target = self._LABEL_START_HOUR.get((label or "").strip().lower())
        if target is None:
            return
        delta = (target - self.time_of_day) % 24.0   # always move forward to next occurrence
        self.time_of_day = (self.time_of_day + delta) % 24.0

    def apply_state_changes(self, changes):
        # Track how long the player's been parked in one place, so the loop-breaker
        # can fire when a scene starts to stagnate. A genuine move resets it.
        if changes.location and changes.location != self.location:
            self.turns_in_location = 1
        else:
            self.turns_in_location += 1
        if changes.location:
            prev_location = self.location
            self.location = changes.location
            self.active_npc = None
            self.npc_idle_turns = 0
            if changes.location_is_new:
                self.visited_locations.append(changes.location)
            if changes.location_type:
                self.location_types[changes.location] = changes.location_type
            # Record the path travelled so geography stays consistent on return.
            if (changes.from_direction and prev_location
                    and prev_location not in ("", "unknown")
                    and prev_location != changes.location):
                d = changes.from_direction.strip().lower()
                self.location_graph.setdefault(prev_location, {})[d] = changes.location
                opp = OPPOSITE_DIRECTION.get(d)
                if opp:
                    self.location_graph.setdefault(changes.location, {})[opp] = prev_location

        # A short gist of the current place — set on arrival, updatable later if
        # the place materially changes. Powers the location detail (hover tooltip
        # in pygame, Inspect card in Textual).
        if changes.location_summary and self.location and self.location != "unknown":
            self.location_descriptions[self.location] = changes.location_summary.strip()

        # inventory updates
        inv = changes.inventory
        for w in inv.weapons_add:
            weapon = WeaponData(name=w.name, damage_range=w.damage_range, description=w.description)
            self.weapons.append(weapon)
            # auto-equip if better than current
            if weapon.damage_range > self.equipped_weapon.damage_range:
                self.equipped_weapon = weapon
        self.weapons = [w for w in self.weapons if w.name not in inv.weapons_remove]

        for a in inv.armor_add:
            armor = ArmorData(name=a.name, armor_value=a.armor_value, description=a.description)
            self.armor.append(armor)
            if armor.armor_value > self.equipped_armor.armor_value:
                self.equipped_armor = armor
        self.armor = [a for a in self.armor if a.name not in inv.armor_remove]

        for c in inv.consumables_add:
            self.consumables.append(ConsumableData(name=c.name, effect=c.effect, description=c.description))
        self.consumables = [c for c in self.consumables if c.name not in inv.consumables_remove]

        for t in inv.trinkets_add:
            self.trinkets.append(TrinketData(name=t.name, description=t.description))
        self.trinkets = [t for t in self.trinkets if t.name not in inv.trinkets_remove]

        # Add or update each NPC. The model refers to an NPC by a fixed id; we look
        # that id up (creating the record if it's new), fill in any fields it sent,
        # and add any new fact to keep. We stamp last_seen_turn on every NPC named
        # this turn.
        for upd in changes.npcs:
            rec = self.npcs.get(upd.id)
            if rec is None:
                rec = NPCRecord(id=upd.id, name=_clean_npc_name(upd.name, upd.id))
                self.npcs[upd.id] = rec
            clean_name = _clean_npc_name(upd.name, upd.id)
            if clean_name:
                rec.name = clean_name
            if upd.role:
                rec.role = upd.role
            if upd.location is not None:
                rec.location = upd.location
            if upd.description:
                rec.description = upd.description
            if upd.voice:
                rec.voice = upd.voice
            if upd.disposition_delta:
                rec.disposition += upd.disposition_delta
            if upd.note and upd.note not in rec.facts:
                rec.facts.append(upd.note)
            rec.last_seen_turn = self.session_turn

        for wf in changes.world_facts_add:
            if not any(f.text == wf.text and f.location == wf.location for f in self.world_facts):
                self.world_facts.append(WorldFact(text=wf.text, location=wf.location, turn=self.session_turn))

        if changes.hp_delta:
            self.hp = max(0, min(self.max_hp, self.hp + changes.hp_delta))

        if changes.quest_added:
            q = changes.quest_added
            if not any(existing.id == q.id for existing in self.quests):
                self.quests.append(QuestData(
                    id=q.id, title=q.title, description=q.description,
                    status=q.status, stages=list(q.stages),
                ))

        if changes.quest_updated:
            upd = changes.quest_updated
            for q in self.quests:
                if q.id == upd.id:
                    if upd.stage:
                        q.stages.append(upd.stage)
                    if upd.status is not None:
                        q.status = upd.status
                    break

        # A named wait/rest target is authoritative; otherwise advance by the action's pace.
        if getattr(changes, "set_time_of_day", None):
            self.set_time_to_label(changes.set_time_of_day)
        else:
            self.advance_time(changes.action_type)
        self.session_turn += 1

        present = [u.id for u in changes.npcs if u.present]
        if present:
            self.active_npc = present[-1]
            self.npc_idle_turns = 0
        elif self.active_npc:
            self.npc_idle_turns += 1
            if self.npc_idle_turns >= 2:
                self.active_npc = None
                self.npc_idle_turns = 0

    # ── consumable effects / buffs ─────────────────────────────────────────────

    @property
    def damage_buff(self) -> int:
        return sum(b.amount for b in self.buffs if b.kind == "damage")

    @property
    def armor_buff(self) -> int:
        return sum(b.amount for b in self.buffs if b.kind == "armor")

    def buff_label(self, kind: str) -> str:
        """Compact inline tag for a stat's active buffs, e.g. ' [+3, 2 rounds]'.
        Empty string when no buff of that kind is active."""
        relevant = [b for b in self.buffs if b.kind == kind]
        if not relevant:
            return ""
        total = sum(b.amount for b in relevant)
        rounds = max(b.rounds_left for b in relevant)
        unit = "round" if rounds == 1 else "rounds"
        return f" [+{total}, {rounds} {unit}]"

    def apply_consumable_effect(self, item) -> str | None:
        """Resolve a consumable's mechanical effect, mutating state. Returns a
        result message if the effect was mechanical, or None if the effect is
        purely narrative (caller should defer to the narrator). Does not remove
        the item from inventory — the caller decides that."""
        effect = item.effect or ""

        def amount_after(prefix: str) -> int:
            try:
                return int(effect[len(prefix):])
            except (ValueError, TypeError):
                return 0

        if effect.startswith("heal_"):
            before = self.hp
            self.hp = min(self.max_hp, self.hp + amount_after("heal_"))
            return f"You use {item.name}. Restored {self.hp - before} HP."

        for prefix in ("harm_", "damage_"):
            if effect.startswith(prefix):
                before = self.hp
                self.hp = max(0, self.hp - amount_after(prefix))
                return f"You use {item.name}. Lost {before - self.hp} HP."

        if effect.startswith("maxhp_"):
            amount = amount_after("maxhp_")
            self.max_hp += amount
            self.hp += amount
            return f"You use {item.name}. Maximum HP increased by {amount}."

        if effect.startswith("buff_damage_"):
            amount = amount_after("buff_damage_")
            self.buffs.append(ActiveBuff("damage", amount, DEFAULT_BUFF_ROUNDS))
            return f"You use {item.name}. +{amount} damage for {DEFAULT_BUFF_ROUNDS} rounds."

        if effect.startswith("buff_armor_"):
            amount = amount_after("buff_armor_")
            self.buffs.append(ActiveBuff("armor", amount, DEFAULT_BUFF_ROUNDS))
            return f"You use {item.name}. +{amount} armor for {DEFAULT_BUFF_ROUNDS} rounds."

        return None

    def tick_buffs(self):
        """Advance buff durations by one combat round and drop expired ones."""
        for b in self.buffs:
            b.rounds_left -= 1
        self.buffs = [b for b in self.buffs if b.rounds_left > 0]

    def _buffs_string(self) -> str:
        if not self.buffs:
            return "none"
        return ", ".join(f"+{b.amount} {b.kind} ({b.rounds_left} rounds)" for b in self.buffs)

    def _inventory_string(self) -> str:
        parts = []
        if self.weapons:
            parts.append(f"Weapons: {', '.join(w.name for w in self.weapons)}")
        if self.armor:
            parts.append(f"Armor: {', '.join(a.name for a in self.armor)}")
        if self.consumables:
            parts.append(f"Consumables: {', '.join(f'{c.name} ({c.effect})' for c in self.consumables)}")
        if self.trinkets:
            parts.append(f"Trinkets: {', '.join(t.name for t in self.trinkets)}")
        return " | ".join(parts) if parts else "nothing"

    def npcs_at(self, location: str) -> list[NPCRecord]:
        """NPCs the engine believes are at (or headed to) a location."""
        return [r for r in self.npcs.values() if r.location and r.location == location]

    def relevant_world_facts(self, location: str, include_all_below: int = 30,
                             scoped_cap: int = 12) -> list[WorldFact]:
        """World facts to surface as ground truth, newest first. While the ledger
        is small (≤ include_all_below), return ALL of it — a fact tied to a place
        you've left is still true and the model must not contradict it. Only once
        the ledger grows large do we fall back to scoping (this location + global),
        capped at scoped_cap so the prompt never floods."""
        if len(self.world_facts) <= include_all_below:
            return list(reversed(self.world_facts))
        relevant = [f for f in self.world_facts if f.location is None or f.location == location]
        return list(reversed(relevant))[:scoped_cap]

    def connections_from(self, location: str) -> dict[str, str]:
        """Known directional links out of a location ({direction: place})."""
        return self.location_graph.get(location, {})

    def _active_npc_name(self) -> str:
        if self.active_npc and self.active_npc in self.npcs:
            return self.npcs[self.active_npc].label
        return "none"

    def _quests_string(self) -> str:
        active = [q for q in self.quests if q.status == "active"]
        if not active:
            return "none"
        parts = []
        for q in active:
            s = f"[{q.id}] {q.title}: {q.description}"
            if q.stages:
                s += f" (progress: {q.stages[-1]})"
            parts.append(s)
        return " | ".join(parts)

    def to_prompt_string(self) -> str:
        time_label = self._time_label()
        return f"""PLAYER: {self.player.name} | {self.player.background}
WORLD / SETTING: {self.player.setting or "default — grounded low-to-mid fantasy"}
LOCATION: {self.location}
ACTIVE NPC: {self._active_npc_name()}
TIME: {time_label}
HP: {self.hp}/{self.max_hp}
EQUIPPED: {self.equipped_weapon.name} (1-{self.equipped_weapon.damage_range} dmg) | {self.equipped_armor.name} ({self.equipped_armor.armor_value} armor)
INVENTORY: {self._inventory_string()}
ACTIVE EFFECTS: {self._buffs_string()}
ACTIVE QUESTS: {self._quests_string()}
PLAYER'S CHOSEN TONE: {self.player.tone}
TURN: {self.session_turn}"""


    def _time_label(self) -> str:
        h = self.time_of_day
        if 5 <= h < 8:   return "early morning"
        if 8 <= h < 12:  return "morning"
        if 12 <= h < 14: return "midday"
        if 14 <= h < 18: return "afternoon"
        if 18 <= h < 21: return "evening"
        if 21 <= h < 24: return "night"
        return "deep night"