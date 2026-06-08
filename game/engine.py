from dataclasses import dataclass, field


# How many combat rounds a consumable buff lasts when applied.
DEFAULT_BUFF_ROUNDS = 3


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
class PlayerCharacter:
    name: str
    background: str
    tone: str


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
    npc_relationships: dict[str, int] = field(default_factory=dict)
    session_turn: int = 0
    active_npc: str | None = None
    npc_idle_turns: int = 0

    def advance_time(self, action_type: str):
        increments = {
            "none": 0.0,
            "short": 0.25,
            "medium": 1.0,
            "long": 4.0,
        }
        self.time_of_day = (self.time_of_day + increments.get(action_type, 0.0)) % 24.0

    def apply_state_changes(self, changes):
        if changes.location:
            self.location = changes.location
            self.active_npc = None
            self.npc_idle_turns = 0
            if changes.location_is_new:
                self.visited_locations.append(changes.location)

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

        for npc, delta in changes.relationship_delta.items():
            self.npc_relationships[npc] = self.npc_relationships.get(npc, 0) + delta

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

        self.advance_time(changes.action_type)
        self.session_turn += 1

        if changes.npc_encountered:
            self.active_npc = changes.npc_encountered
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

    def _relationships_string(self) -> str:
        if not self.npc_relationships:
            return "none"
        return ", ".join(f"{npc}: {rel}" for npc, rel in self.npc_relationships.items())

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
LOCATION: {self.location}
ACTIVE NPC: {self.active_npc or "none"}
NPC RELATIONSHIPS: {self._relationships_string()}
TIME: {time_label}
HP: {self.hp}/{self.max_hp}
EQUIPPED: {self.equipped_weapon.name} (1-{self.equipped_weapon.damage_range} dmg) | {self.equipped_armor.name} ({self.equipped_armor.armor_value} armor)
INVENTORY: {self._inventory_string()}
ACTIVE EFFECTS: {self._buffs_string()}
ACTIVE QUESTS: {self._quests_string()}
TONE: {self.player.tone}
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