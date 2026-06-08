import random
from .engine import EngineState
from .schema import EnemyDescriptor

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


class CLICombatInterface(CombatInterface):
    def show_intro(self, enemy_type: str):
        print(f"\n{'='*40}")
        print(f"  COMBAT — {enemy_type}")
        print(f"{'='*40}")

    def log(self, message: str, animate: bool = False):
        print(f"  {message}")

    def choose_action(self, state: EngineState, alive_enemies: list[dict]) -> str:
        print(f"\n  {state.player.name}: {state.hp}/{state.max_hp} HP | Armor: {state.equipped_armor.armor_value}")
        print(f"  Weapon: {state.equipped_weapon.name} (1-{state.equipped_weapon.damage_range})")
        print()
        for e in alive_enemies:
            print(f"  {e['name']}: {e['hp']}/{e['max_hp']} HP | Armor: {e['armor']}")
        print(f"\n{'─'*40}")
        print("  1. Attack")
        print("  2. Use item")
        print("  3. Flee")
        print(f"{'─'*40}")

        while True:
            choice = input("  > ").strip()
            if choice == "1":
                return "attack"
            elif choice == "2":
                return "item"
            elif choice == "3":
                return "flee"
            else:
                print("  Enter 1, 2, or 3.")

    def choose_target(self, alive_enemies: list[dict]) -> dict:
        if len(alive_enemies) == 1:
            return alive_enemies[0]
        print()
        for i, e in enumerate(alive_enemies):
            print(f"  {i+1}. {e['name']} ({e['hp']}/{e['max_hp']} HP)")
        while True:
            pick = input("  Target: ").strip()
            try:
                idx = int(pick) - 1
                if 0 <= idx < len(alive_enemies):
                    return alive_enemies[idx]
            except (ValueError, IndexError):
                pass
            print(f"  Invalid selection. Enter the number of a target.")

    def choose_item(self, state: EngineState) -> int | None:
        usable = state.consumables
        print()
        for i, item in enumerate(usable):
            print(f"  {i+1}. {item.name} — {item.description}")
        pick = input("  Use: ").strip()
        try:
            idx = int(pick) - 1
            if 0 <= idx < len(usable):
                return idx
        except (ValueError, IndexError):
            pass
        print("\n  Invalid choice.")
        return None


def run_combat(state: EngineState, encounter: EnemyDescriptor, interface: CombatInterface = None) -> dict:
    if interface is None:
        interface = CLICombatInterface()

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
                interface.log(f"You strike {target['name']} for {damage} damage. (rolled {roll} - {target['armor']} armor)")
            else:
                interface.log(f"Your attack glances off {target['name']}'s armor. (rolled {roll} - {target['armor']} armor)")

            if target["hp"] <= 0:
                interface.log(f"{target['name']} falls.", animate=True)
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
                interface.log("You disengage and fall back.", animate=True)
                combat_log.append("player fled")
                result = "fled"
                break
            else:
                interface.log("You try to break away but can't find an opening.", animate=True)

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
                    interface.log(f"{e['name']} strikes you for {damage} damage. (rolled {roll} - {armor_val} armor)")
                else:
                    interface.log(f"{e['name']}'s attack glances off your armor. (rolled {roll} - {armor_val} armor)")

                if state.hp <= 0:
                    interface.log("You collapse.", animate=True)
                    combat_log.append("player defeated")
                    result = "defeat"
                    break

        # check victory
        if result == "ongoing" and all(e["hp"] <= 0 for e in enemies):
            interface.log("The fight ends.", animate=True)
            combat_log.append("all enemies defeated")
            result = "victory"

        # one round elapsed; age any active buffs
        state.tick_buffs()

    return {
        "result": result,
        "log": combat_log,
        "enemies_defeated": [e["name"] for e in enemies if e["hp"] <= 0],
    }