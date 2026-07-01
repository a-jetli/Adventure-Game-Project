from pydantic import BaseModel, Field
from typing import Literal


class WeaponItem(BaseModel):
    name: str
    damage_range: int
    description: str = ""


class ArmorItem(BaseModel):
    name: str
    armor_value: int
    description: str = ""


class ConsumableItem(BaseModel):
    name: str
    effect: str  # "heal_20", "buff_damage_5", etc — engine interprets
    description: str = ""


class TrinketItem(BaseModel):
    name: str
    description: str = ""


class InventoryUpdate(BaseModel):
    weapons_add: list[WeaponItem] = Field(default_factory=list)
    weapons_remove: list[str] = Field(default_factory=list)
    armor_add: list[ArmorItem] = Field(default_factory=list)
    armor_remove: list[str] = Field(default_factory=list)
    consumables_add: list[ConsumableItem] = Field(default_factory=list)
    consumables_remove: list[str] = Field(default_factory=list)
    trinkets_add: list[TrinketItem] = Field(default_factory=list)
    trinkets_remove: list[str] = Field(default_factory=list)


class Quest(BaseModel):
    id: str
    title: str
    description: str
    status: Literal["active", "completed", "failed"] = "active"
    stages: list[str] = Field(default_factory=list)


class QuestUpdate(BaseModel):
    id: str
    status: Literal["active", "completed", "failed"] | None = None
    stage: str | None = None


class NPCUpdate(BaseModel):
    id: str  # stable slug — REUSE the existing id if this NPC already exists
    name: str | None = None
    role: str | None = None  # archetype tag (merchant, guard, commoner, ...)
    location: str | None = None  # where they are / declared they'll be next
    disposition_delta: int = 0
    description: str | None = None  # set once, on first meeting
    voice: str | None = None  # set once, on first meeting
    note: str | None = None  # a durable fact to append (promise, knowledge)
    present: bool = True  # are they in the scene this turn


class WorldFactItem(BaseModel):
    text: str
    location: str | None = None  # null = global / world-level fact


class EnemyDescriptor(BaseModel):
    enemy_type: str
    difficulty: Literal["trivial", "easy", "medium", "hard", "deadly"]
    count: int
    hp: int
    armor: int
    damage_range: int


class StateChanges(BaseModel):
    location: str | None = None
    location_is_new: bool = False
    location_type: str | None = None  # archetype tag, set when location_is_new
    location_summary: str | None = None  # short gist of the place; tooltip + log header
    from_direction: str | None = None  # how the player travelled here from the last place
    inventory: InventoryUpdate = Field(default_factory=InventoryUpdate)
    npcs: list[NPCUpdate] = Field(default_factory=list)
    new_log_needed: bool = False
    combat_triggered: bool = False
    encounter: EnemyDescriptor | None = None
    action_type: Literal["none", "short", "medium", "long"] = "none"
    # Set ONLY when the action explicitly waits/rests/sleeps until a named time of day
    # (e.g. "I wait until morning", "we make camp for the night"). Jumps the clock forward
    # to that time of day; otherwise leave null and let action_type advance time normally.
    set_time_of_day: Literal[
        "early morning", "morning", "midday", "afternoon", "evening", "night", "deep night"
    ] | None = None
    hp_delta: int = 0
    quest_added: Quest | None = None
    quest_updated: QuestUpdate | None = None
    world_facts_add: list[WorldFactItem] = Field(default_factory=list)


class LLMResponse(BaseModel):
    narrative: str
    state_changes: StateChanges


class WorldDevelopment(BaseModel):
    """One small thing that shifted in the world offscreen, between scenes. Only
    ever advances things that already exist — see the world-director prompt."""
    summary: str  # one-line description of what changed
    world_fact: str | None = None  # a durable consequence to record
    world_fact_location: str | None = None  # place it's tied to (null = global)
    npc_id: str | None = None  # an EXISTING npc this concerns (reuse exact id)
    npc_new_location: str | None = None  # where that npc moved to
    npc_note: str | None = None  # a durable fact to append to that npc
    quest_id: str | None = None  # an EXISTING active quest to nudge
    quest_stage: str | None = None  # present-tense progress line for it


class WorldTick(BaseModel):
    developments: list[WorldDevelopment] = Field(default_factory=list)