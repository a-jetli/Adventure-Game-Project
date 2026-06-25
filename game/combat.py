import random
from .engine import EngineState
from .schema import EnemyDescriptor


# ── combat prose: vary the lines and scale them to how hard a blow landed ──────
# Math is unchanged; these only pick how a hit is described.

def _hit_tier(damage: int, target_max_hp: int) -> str:
    frac = damage / max(1, target_max_hp)
    if frac < 0.12:
        return "glancing"
    if frac < 0.30:
        return "solid"
    return "brutal"


# Flavor lines are kept weapon- and setting-agnostic on purpose: the same pools read
# right whether the player is swinging a sword, firing a pipe-rifle, or throwing a
# punch. The LLM handles the weapon-specific color in the trigger and aftermath beats;
# these just narrate the dice with momentum, so they must not assume blades or armor.
_PLAYER_HIT = {
    "glancing": ["You catch {name} a glancing hit", "You graze {name}", "You clip {name}"],
    "solid": ["You land a solid hit on {name}", "You hit {name} square", "You drive {name} back a step"],
    "brutal": ["You hammer {name} with everything you have", "You hit {name} dead-on", "You crack {name} hard enough to stagger them"],
}
_ENEMY_HIT = {
    "glancing": ["{name} grazes you", "{name} clips you", "{name} catches you a glancing hit"],
    "solid": ["{name} catches you square", "{name} drives a hit home", "{name} lands a hard one"],
    "brutal": ["{name} smashes into you", "{name} rocks you to the heels", "{name} hits you like a falling beam"],
}
_PLAYER_MISS = ["{name} slips aside and you come up short.", "You miss {name} clean.", "Your hit goes wide of {name}."]
_ENEMY_MISS = ["{name} comes at you and misses.", "You ride {name}'s hit and it glances off.", "{name} swings on you wide."]
_KILL = ["{name} drops and stays down.", "{name} folds and doesn't rise.", "{name} goes down hard."]


def _line(pool, name: str) -> str:
    return random.choice(pool).format(name=name)

class CombatInterface:
    def show_intro(self, enemy_type: str):
        pass

    def log(self, message: str, animate: bool = False):
        pass

    def on_player_action_complete(self):
        pass

    def choose_action(self, state: EngineState, alive_enemies: list[dict]) -> str:
        # Returns "attack", "item", "flee"
        pass

    def choose_target(self, alive_enemies: list[dict]) -> dict:
        pass

    def choose_item(self, state: EngineState) -> int | None:
        # Returns index in state.consumables, or None
        pass


def run_combat(state: EngineState, encounter: EnemyDescriptor, interface: CombatInterface) -> dict:
    enemies = []
    for i in range(encounter.count):
        enemies.append({
            "name": f"{encounter.enemy_type} {i+1}" if encounter.count > 1 else encounter.enemy_type,
            "hp": encounter.hp,
            "max_hp": encounter.hp,
            "armor": encounter.armor,
            "damage_range": encounter.damage_range,
        })

    combat_log = []
    result = "ongoing"

    interface.show_intro(encounter.enemy_type)

    while result == "ongoing":
        alive = [e for e in enemies if e["hp"] > 0]
        if not alive:
            result = "victory"
            combat_log.append("all enemies defeated")
            break

        choice = interface.choose_action(state, alive)

        if choice == "attack":
            target = interface.choose_target(alive)
            weapon_range = max(1, state.equipped_weapon.damage_range + state.damage_buff)
            roll = random.randint(1, weapon_range)
            damage = max(0, roll - target["armor"])
            target["hp"] = max(0, target["hp"] - damage)

            if damage > 0:
                lead = _line(_PLAYER_HIT[_hit_tier(damage, target["max_hp"])], target["name"])
                interface.log(f"{lead} for {damage} damage. (rolled {roll} - {target['armor']} armor)")
            else:
                interface.log(f"{_line(_PLAYER_MISS, target['name'])} (rolled {roll} - {target['armor']} armor)")

            if target["hp"] <= 0:
                interface.log(_line(_KILL, target["name"]), animate=True)
                combat_log.append(f"{target['name']} defeated")

        elif choice == "item":
            if not state.consumables:
                interface.log("No consumables to use.")
                continue

            pick = interface.choose_item(state)
            if pick is None:
                continue

            chosen = state.consumables[pick]
            effect_result = state.apply_consumable_effect(chosen)
            if effect_result is not None:
                interface.log(effect_result)
            else:
                # Narrative-only item used mid-fight: no LLM available here, so
                # fall back to its description rather than a dead "no effect".
                msg = f"You use {chosen.name}."
                if chosen.description:
                    msg += f" {chosen.description}"
                interface.log(msg)
            state.consumables.remove(chosen)
            combat_log.append(f"used {chosen.name}")

        elif choice == "flee":
            flee_roll = random.randint(1, 10)
            if flee_roll >= 4:
                interface.log(_line([
                    "You break off and put distance between you.",
                    "You disengage and fall back before they can close.",
                    "You turn and go, and they let you.",
                ], ""), animate=True)
                combat_log.append("player fled")
                result = "fled"
                break
            else:
                interface.log(_line([
                    "You try to break away, but there's no opening yet.",
                    "You move to run and a blade cuts you off.",
                    "They press in before you can turn — no way clear.",
                ], ""), animate=True)

        interface.on_player_action_complete()

        # enemy turns
        if result == "ongoing":
            for e in enemies:
                if e["hp"] <= 0:
                    continue
                roll = random.randint(1, e["damage_range"])
                armor_val = state.equipped_armor.armor_value + state.armor_buff
                damage = max(0, roll - armor_val)

                if damage > 0:
                    state.hp = max(0, state.hp - damage)
                    lead = _line(_ENEMY_HIT[_hit_tier(damage, state.max_hp)], e["name"])
                    interface.log(f"{lead} for {damage} damage. (rolled {roll} - {armor_val} armor)")
                else:
                    interface.log(f"{_line(_ENEMY_MISS, e['name'])} (rolled {roll} - {armor_val} armor)")

                if state.hp <= 0:
                    interface.log("The blow drops you. The ground comes up, and the noise of the fight goes far away.", animate=True)
                    combat_log.append("player defeated")
                    result = "defeat"
                    break

        # check victory
        if result == "ongoing" and all(e["hp"] <= 0 for e in enemies):
            interface.log(_line([
                "The last of them goes down, and the noise drains out of the place.",
                "It's over. You're still standing, breathing hard.",
                "Quiet comes back. Nothing left moving but you.",
            ], ""), animate=True)
            combat_log.append("all enemies defeated")
            result = "victory"

        # one round elapsed; age any active buffs
        state.tick_buffs()

    return {
        "result": result,
        "log": combat_log,
        "enemies_defeated": [e["name"] for e in enemies if e["hp"] <= 0],
    }