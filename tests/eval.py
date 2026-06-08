"""
Eval harness for the game's LLM contract.
Run from the project root: python3 eval.py

Tests schema compliance, state change correctness, and behavioral rules.
Prints a pass/fail summary and exits with code 1 if any tests fail.
"""

import os
import sys
import json
import hashlib
from dotenv import load_dotenv
from datetime import datetime
from openai import OpenAI
from game.engine import EngineState, PlayerCharacter, WeaponData, ArmorData
from game.schema import LLMResponse, StateChanges
from game.game_logic import load_system_prompt, call_llm
from game.stats import SessionStats, CallRecord

load_dotenv()

# ── minimal engine state for eval calls ──────────────────────────────────────

def _make_state(
    location: str = "the ruined gatehouse",
    location_is_new: bool = False,
    has_weapon: bool = True,
    has_npc: str | None = None,
) -> EngineState:
    player = PlayerCharacter(
        name="Aldric", background="Former soldier, dishonorably discharged", tone="grim"
    )
    state = EngineState(player=player)
    state.location = location
    if has_weapon:
        w = WeaponData(name="worn shortsword", damage_range=9, description="")
        state.weapons.append(w)
        state.equipped_weapon = w
        a = ArmorData(name="padded jerkin", armor_value=2, description="")
        state.armor.append(a)
        state.equipped_armor = a
    if has_npc:
        state.active_npc = has_npc
    state.visited_locations = [location] if not location_is_new else []
    return state


def _hot_context_for(turns: list[str]) -> list[str]:
    return [
        f"[Turn {i+1}] Player: {t} | The world responded."
        for i, t in enumerate(turns)
    ]


# ── test case definition ──────────────────────────────────────────────────────

class TestCase:
    def __init__(
        self,
        name: str,
        player_input: str,
        state: EngineState,
        hot_context: list[str],
        checks: list[tuple[str, callable]],
    ):
        self.name = name
        self.player_input = player_input
        self.state = state
        self.hot_context = hot_context
        self.checks = checks


def _build_test_cases() -> list[TestCase]:
    return [

        # ── schema compliance ─────────────────────────────────────────────────
        TestCase(
            name="schema/parses_correctly",
            player_input="I look around.",
            state=_make_state(),
            hot_context=[],
            checks=[
                ("response parses into LLMResponse",
                 lambda r: isinstance(r, LLMResponse)),
                ("narrative is non-empty string",
                 lambda r: isinstance(r.narrative, str) and len(r.narrative) > 10),
                ("state_changes is present",
                 lambda r: r.state_changes is not None),
            ],
        ),

        # ── survey — Type 8 (a look-around earns a full description) ───────────
        TestCase(
            name="survey/look_around_is_rich",
            player_input="I look around and take in my surroundings. What's my environment like?",
            state=_make_state(location_is_new=False),
            hot_context=_hot_context_for(["I arrived here", "I examined the gate"]),
            checks=[
                ("survey is substantial — at least 60 words",
                 lambda r: len(r.narrative.split()) >= 60),
                ("survey spans more than a few sentences",
                 lambda r: r.narrative.count(".") >= 4),
                ("no location change on a survey",
                 lambda r: r.state_changes.location is None),
                ("no combat triggered",
                 lambda r: not r.state_changes.combat_triggered),
            ],
        ),

        # ── item pickup ───────────────────────────────────────────────────────
        TestCase(
            name="item_pickup/weapon_goes_to_inventory",
            player_input="I pick up the rusty dagger on the ground.",
            state=_make_state(),
            hot_context=[
                "[Turn 1] Player: I searched the area | A rusty dagger lay in the dirt."
            ],
            checks=[
                ("weapon added to inventory",
                 lambda r: len(r.state_changes.inventory.weapons_add) > 0),
                ("weapon has valid damage_range",
                 lambda r: all(
                     w.damage_range > 0
                     for w in r.state_changes.inventory.weapons_add
                 )),
                ("no combat triggered on pickup",
                 lambda r: not r.state_changes.combat_triggered),
            ],
        ),

        # ── no phantom state changes ──────────────────────────────────────────
        TestCase(
            name="state/no_phantom_location_on_mundane_action",
            player_input="I sit down and rest for a moment.",
            state=_make_state(),
            hot_context=[],
            checks=[
                ("small action stays brief — under 90 words",
                 lambda r: len(r.narrative.split()) < 90),
                ("location not changed on rest",
                 lambda r: r.state_changes.location is None),
                ("no combat triggered on rest",
                 lambda r: not r.state_changes.combat_triggered),
                ("no items invented on rest",
                 lambda r: len(r.state_changes.inventory.weapons_add) == 0
                           and len(r.state_changes.inventory.trinkets_add) == 0),
            ],
        ),

        # ── new location ──────────────────────────────────────────────────────
        TestCase(
            name="state/new_location_flagged_on_travel",
            player_input="I follow the road north toward the village I can see in the distance.",
            state=_make_state(),
            hot_context=[
                "[Turn 1] Player: I looked north | A village was visible on the horizon."
            ],
            checks=[
                ("action_type is medium or long for travel",
                 lambda r: r.state_changes.action_type in ("medium", "long")),
                ("narrative describes movement",
                 lambda r: any(
                     word in r.narrative.lower()
                     for word in ["north", "road", "village", "walk", "follow", "head"]
                 )),
            ],
        ),

        # ── dialogue stays in dialogue ────────────────────────────────────────
        TestCase(
            name="dialogue/npc_responds_in_character",
            player_input="I ask her what happened to the missing grain shipment.",
            state=_make_state(has_npc="the innkeeper"),
            hot_context=[
                "[Turn 1] Player: I entered the inn | A tired woman stood behind the bar.",
                "[Turn 2] Player: I approached the innkeeper | She looked up warily.",
            ],
            checks=[
                ("npc_encountered is set during dialogue",
                 lambda r: r.state_changes.npc_encountered is not None),
                ("narrative contains dialogue — has quotation marks",
                 lambda r: '"' in r.narrative or "\u201c" in r.narrative),
                ("no combat triggered during conversation",
                 lambda r: not r.state_changes.combat_triggered),
            ],
        ),

        # ── combat trigger has valid stats ────────────────────────────────────
        TestCase(
            name="combat/encounter_has_valid_stats",
            player_input="I charge at the bandit and attack him.",
            state=_make_state(),
            hot_context=[
                "[Turn 1] Player: I rounded the corner | A bandit stepped out of the shadows, blade drawn.",
            ],
            checks=[
                ("combat triggered",
                 lambda r: r.state_changes.combat_triggered),
                ("encounter is populated",
                 lambda r: r.state_changes.encounter is not None),
                ("enemy has positive hp",
                 lambda r: r.state_changes.encounter is not None
                           and r.state_changes.encounter.hp > 0),
                ("enemy has non-negative armor",
                 lambda r: r.state_changes.encounter is not None
                           and r.state_changes.encounter.armor >= 0),
                ("enemy damage_range is positive",
                 lambda r: r.state_changes.encounter is not None
                           and r.state_changes.encounter.damage_range > 0),
                ("difficulty is valid value",
                 lambda r: r.state_changes.encounter is not None
                           and r.state_changes.encounter.difficulty
                           in ("trivial", "easy", "medium", "hard", "deadly")),
            ],
        ),

        # ── orientation query is brief ────────────────────────────────────────
        TestCase(
            name="orientation/brief_on_known_location",
            player_input="Where am I right now?",
            state=_make_state(location_is_new=False),
            hot_context=_hot_context_for([
                "I arrived at the gatehouse",
                "I looked around",
                "I searched the yard",
            ]),
            checks=[
                ("orientation response is brief — under 120 words",
                 lambda r: len(r.narrative.split()) < 120),
                ("no location change on orientation query",
                 lambda r: r.state_changes.location is None),
                ("action_type is none",
                 lambda r: r.state_changes.action_type == "none"),
            ],
        ),

        # ── endings rule ──────────────────────────────────────────────────────
        TestCase(
            name="prose/last_sentence_not_player_focused",
            player_input="I walk slowly through the market, taking it all in.",
            state=_make_state(location="the market square"),
            hot_context=[],
            checks=[
                ("last sentence does not start with 'You'",
                 lambda r: (
                     not r.narrative.strip().split(".")[-2].strip().startswith("You")
                     if len(r.narrative.strip().split(".")) > 1
                     else True
                 )),
            ],
        ),

        # ── no emotional narration ────────────────────────────────────────────
        TestCase(
            name="prose/no_emotional_narration",
            player_input="I open the door and step inside.",
            state=_make_state(),
            hot_context=[],
            checks=[
                ("no 'heart' references",
                 lambda r: "heart" not in r.narrative.lower()),
                ("no 'spine' references",
                 lambda r: "spine" not in r.narrative.lower()),
                ("no 'surge' references",
                 lambda r: "surge" not in r.narrative.lower()),
                ("no 'dread' references",
                 lambda r: "dread" not in r.narrative.lower()),
            ],
        ),

        # ── quest creation on commitment ─────────────────────────────────────
        TestCase(
            name="quest/created_on_commitment",
            player_input="I agree to help the innkeeper find her missing brother.",
            state=_make_state(has_npc="the innkeeper"),
            hot_context=[
                "[Turn 1] Player: I entered the inn | A tired woman stood behind the bar.",
                "[Turn 2] Player: I asked what was troubling her | She explained her brother went into the northern woods a week ago and hasn't returned. She begged for help finding him.",
            ],
            checks=[
                ("quest_added is populated",
                 lambda r: r.state_changes.quest_added is not None),
                ("quest has non-empty title",
                 lambda r: r.state_changes.quest_added is not None
                           and len(r.state_changes.quest_added.title) > 0),
                ("quest has non-empty description",
                 lambda r: r.state_changes.quest_added is not None
                           and len(r.state_changes.quest_added.description) > 0),
                ("quest status is active",
                 lambda r: r.state_changes.quest_added is not None
                           and r.state_changes.quest_added.status == "active"),
            ],
        ),

        # ── no quest on mundane action ───────────────────────────────────────
        TestCase(
            name="quest/not_created_on_mundane_action",
            player_input="I pick up a rock.",
            state=_make_state(),
            hot_context=[],
            checks=[
                ("quest_added is null for mundane action",
                 lambda r: r.state_changes.quest_added is None),
            ],
        ),

        # ── world authoring: pushback on impossible grabs ─────────────────────
        TestCase(
            name="agency/no_freebie_legendary_weapon",
            player_input="I reach down and pick up the godly sword of infinite power lying at my feet.",
            state=_make_state(),
            hot_context=[],
            checks=[
                ("no legendary weapon conjured into inventory",
                 lambda r: len(r.state_changes.inventory.weapons_add) == 0),
                ("if any weapon was added, it is not absurdly powerful",
                 lambda r: all(w.damage_range <= 20 for w in r.state_changes.inventory.weapons_add)),
                ("no combat triggered from the grab",
                 lambda r: not r.state_changes.combat_triggered),
            ],
        ),

        # ── item effect: created consumables use a resolvable effect ──────────
        TestCase(
            name="items/consumable_effect_is_usable",
            player_input="I search the alchemist's shelf for something to drink that would heal me.",
            state=_make_state(),
            hot_context=[
                "[Turn 1] Player: I entered the abandoned alchemy shop | Dusty shelves lined the walls, a few stoppered vials still intact.",
            ],
            checks=[
                ("any consumable added has a non-empty effect string",
                 lambda r: all(c.effect.strip() != "" for c in r.state_changes.inventory.consumables_add)),
            ],
        ),

    ]


# ── runner ────────────────────────────────────────────────────────────────────

def run_eval():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    system_prompt = load_system_prompt()

    import game_ui
    original_stats = game_ui.session_stats
    game_ui.session_stats = SessionStats()

    test_cases = _build_test_cases()
    total_checks = 0
    passed_checks = 0
    failed_tests = []

    print(f"\nRunning {len(test_cases)} test cases...\n")

    for tc in test_cases:
        try:
            response = call_llm(
                client, system_prompt, tc.state, tc.hot_context, tc.player_input
            )
        except Exception as e:
            print(f"  CRASH  {tc.name}: {e}")
            failed_tests.append((tc.name, f"call_llm raised: {e}", None))
            continue

        case_passed = True
        for check_desc, check_fn in tc.checks:
            total_checks += 1
            try:
                result = check_fn(response)
            except Exception as e:
                result = False
                check_desc = f"{check_desc} [check raised: {e}]"

            if result:
                passed_checks += 1
            else:
                case_passed = False
                failed_tests.append((tc.name, check_desc, response.narrative[:200]))

        status = "  PASS  " if case_passed else "  FAIL  "
        print(f"{status}{tc.name}")

    game_ui.session_stats = original_stats

    print(f"\n{'='*50}")
    print(f"Checks passed: {passed_checks}/{total_checks}")
    print(
        f"Pass rate: {(passed_checks/total_checks)*100:.1f}%"
        if total_checks > 0
        else ""
    )

    if failed_tests:
        print(f"\nFailed checks:")
        for test_name, check_desc, narrative_snippet in failed_tests:
            print(f"\n  [{test_name}]")
            print(f"  Check: {check_desc}")
            if narrative_snippet:
                print(f"  Narrative: {narrative_snippet!r}")

    print()

    with open("system_prompt.md", "rb") as f:
        prompt_hash = hashlib.md5(f.read()).hexdigest()[:8]

    results = {
    "timestamp": datetime.now().isoformat(),
    "prompt_hash": prompt_hash,
    "total_checks": total_checks,
    "passed_checks": passed_checks,
    "pass_rate": (
        round((passed_checks / total_checks) * 100, 1) if total_checks > 0 else 0
    ),
    "failed": [{"test": t, "check": c} for t, c, _ in failed_tests],
    "passed": [
        {"test": tc.name, "checks": [desc for desc, _ in tc.checks]}
        for tc in test_cases
        if not any(t == tc.name for t, _, _ in failed_tests)
    ],
}
    os.makedirs("logs", exist_ok=True)
    with open("logs/eval_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to logs/eval_results.json")

    return len(failed_tests) == 0


if __name__ == "__main__":
    success = run_eval()
    sys.exit(0 if success else 1)