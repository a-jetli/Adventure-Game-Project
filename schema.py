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
    inventory: InventoryUpdate = Field(default_factory=InventoryUpdate)
    npc_encountered: str | None = None
    relationship_delta: dict[str, int] = Field(default_factory=dict)
    new_log_needed: bool = False
    combat_triggered: bool = False
    encounter: EnemyDescriptor | None = None
    action_type: Literal["none", "short", "medium", "long"] = "none"


class LLMResponse(BaseModel):
    narrative: str
    state_changes: StateChanges