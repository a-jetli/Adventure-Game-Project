from pydantic import BaseModel
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
    weapons_add: list[WeaponItem] = []
    weapons_remove: list[str] = []
    armor_add: list[ArmorItem] = []
    armor_remove: list[str] = []
    consumables_add: list[ConsumableItem] = []
    consumables_remove: list[str] = []
    trinkets_add: list[TrinketItem] = []
    trinkets_remove: list[str] = []


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
    inventory: InventoryUpdate = InventoryUpdate()
    npc_encountered: str | None = None
    relationship_delta: dict[str, int] = {}
    new_log_needed: bool = False
    combat_triggered: bool = False
    encounter: EnemyDescriptor | None = None
    action_type: Literal["none", "short", "medium", "long"] = "none"


class LLMResponse(BaseModel):
    narrative: str
    state_changes: StateChanges