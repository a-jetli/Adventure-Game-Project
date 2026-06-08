import time
import re
from schema import LLMResponse
from engine import EngineState
from logs import load_region, load_npc
from stats import SessionStats, CallRecord

def load_system_prompt() -> str:
    with open("system_prompt.md", "r") as f:
        return f.read()


def handle_local_command(player_input: str, state: EngineState) -> str | None:
    cmd = player_input.lower().strip()
    normalized = re.sub(r"[^a-z0-9\s]", "", cmd)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    words = set(normalized.split())

    negated_subject_words = {
        "enemy", "enemies", "foe", "foes", "monster", "monsters", "npc", "npcs",
        "their", "theirs", "his", "her", "hers", "its", "boss", "target"
    }
    self_subject_words = {"my", "me", "mine", "i"}
    has_self_subject = bool(words & self_subject_words)
    has_other_subject = bool(words & negated_subject_words)

    inventory_intent = (
        cmd in ("inventory", "inv", "i", "check inventory")
        or normalized in ("inventory", "inv", "check inventory", "my inventory", "whats in my inventory", "what is in my inventory")
        or (("inventory" in words or "backpack" in words) and has_self_subject and not has_other_subject)
    )
    if inventory_intent:
        return format_inventory_display(state)

    hp_intent = (
        cmd in ("hp", "health", "status")
        or normalized in ("my hp", "my health", "my status", "whats my hp", "what is my hp", "whats my health", "what is my health")
        or (("hp" in words or "health" in words or "status" in words or "hit points" in normalized) and has_self_subject and not has_other_subject)
    )
    if hp_intent:
        return f"{state.player.name}: {state.hp}/{state.max_hp} HP"

    time_intent = (
        cmd in ("time", "clock")
        or normalized in ("what time is it", "whats the time", "tell me the time")
        or (("time" in words or "clock" in words) and (not words or has_self_subject or "what" in words))
    )
    if time_intent:
        return f"Time: {state._time_label()}"

    location_intent = (
        cmd in ("location", "where", "where am i")
        or "where am i" in normalized
        or normalized in ("my location", "whats my location", "what is my location", "where are we")
        or ("location" in words and has_self_subject and not has_other_subject)
    )
    if location_intent:
        return f"Location: {state.location}"

    help_intent = (
        cmd in ("help", "commands")
        or normalized in ("help me", "show commands", "show me commands", "what are the commands")
        or (("help" in words or "commands" in words) and not has_other_subject)
    )
    if help_intent:
        return "Commands: inventory, hp, time, location, equip [item], use [item], quests, help, quit"

    quest_intent = (
        cmd in ("quests", "quest", "journal", "quest log", "questlog")
        or normalized in ("my quests", "show quests", "quest log", "show quest log")
    )
    if quest_intent:
        return format_quest_log(state)

    if cmd.startswith("equip "):
        item_name = player_input[6:].strip().lower()
        for w in state.weapons:
            if w.name.lower() == item_name:
                state.equipped_weapon = w
                return f"Equipped: {w.name} (1-{w.damage_range} dmg)"
        for a in state.armor:
            if a.name.lower() == item_name:
                state.equipped_armor = a
                return f"Equipped: {a.name} ({a.armor_value} armor)"
        return f"'{player_input[6:].strip()}' not found in inventory."

    if cmd.startswith("use "):
        item_name = player_input[4:].strip()
        item_lower = item_name.lower()
        match = None
        match_idx = -1
        for idx, c in enumerate(state.consumables):
            if c.name.lower() == item_lower:
                match = c
                match_idx = idx
                break
        if match is None:
            return f"'{item_name}' isn't something you can use."
        # Mechanical effects (heal/harm/maxhp/buff) are deterministic, so the
        # engine resolves them locally with no API call and consumes the item.
        result = state.apply_consumable_effect(match)
        if result is not None:
            state.consumables.pop(match_idx)
            return result
        # Purely narrative effect: return None so the input falls through to the
        # normal LLM turn, which narrates it and decides whether the item is
        # consumed (via inventory.consumables_remove).
        return None

    return None


def format_inventory_display(state: EngineState) -> str:
    def names(parts):
        return ", ".join(parts) if parts else "none"

    lines = [
        "Inventory",
        "Equipment:",
        f"- Weapon: {state.equipped_weapon.name} (1-{state.equipped_weapon.damage_range} dmg)",
        f"- Armor:  {state.equipped_armor.name} ({state.equipped_armor.armor_value} armor)",
        "Bag:",
        f"- Weapons: {names([w.name for w in state.weapons])}",
        f"- Armor: {names([a.name for a in state.armor])}",
        f"- Consumables: {names([c.name for c in state.consumables])}",
        f"- Trinkets: {names([t.name for t in state.trinkets])}",
    ]
    return "\n".join(lines)


def format_quest_log(state: EngineState) -> str:
    if not state.quests:
        return "Quest Log\nNo quests."
    active = [q for q in state.quests if q.status == "active"]
    completed = [q for q in state.quests if q.status == "completed"]
    failed = [q for q in state.quests if q.status == "failed"]
    lines = ["Quest Log"]
    if active:
        lines.append("Active:")
        for q in active:
            lines.append(f"  [{q.title}] {q.description}")
    if completed:
        lines.append("Completed:")
        for q in completed:
            lines.append(f"  [{q.title}] {q.description}")
    if failed:
        lines.append("Failed:")
        for q in failed:
            lines.append(f"  [{q.title}] {q.description}")
    return "\n".join(lines)


def call_llm(client, system_prompt, state, hot_context, player_input, model="gpt-5.4-nano", session_stats=None) -> LLMResponse:
    context_block = "\n".join(hot_context) if hot_context else "No prior context."
    retrieved = []
    if state.location and state.location != "unknown":
        region_log = load_region(state.location)
        if region_log:
            retrieved.append(f"REGION LOG — {state.location}:\n{region_log}")
    if state.active_npc:
        npc_log = load_npc(state.active_npc)
        if npc_log:
            retrieved.append(f"NPC LOG — {state.active_npc}:\n{npc_log}")
    retrieved_block = "\n\n".join(retrieved) if retrieved else "No prior logs retrieved."

    user_message = f"""ENGINE STATE:
{state.to_prompt_string()}

RETRIEVED LOGS:
{retrieved_block}

RECENT CONTEXT:
{context_block}

PLAYER INPUT:
{player_input}"""

    t_start = time.time()
    failure_type = None
    retry_succeeded = False
    input_tokens = 0
    output_tokens = 0
    raw = ""

    try:
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=4000,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ]
        )
        input_tokens  = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        raw = response.content[0].message.content if hasattr(response, 'content') else response.choices[0].message.content

        try:
            result = LLMResponse.model_validate_json(raw)
        except Exception as parse_err:
            if not raw.strip():
                failure_type = "empty_response"
            elif raw.strip()[0] != "{":
                failure_type = "not_json"
            else:
                failure_type = "schema_validation"

            # attempt retry
            retry_resp = client.chat.completions.create(
                model=model,
                max_completion_tokens=4000,
                reasoning_effort="low",
                messages=[
                    {"role": "system",    "content": system_prompt},
                    {"role": "user",      "content": user_message},
                    {"role": "assistant", "content": raw},
                    {"role": "user",      "content": "Your response was not valid JSON matching the required schema. Return only the raw JSON object, no other text."}
                ]
            )
            input_tokens  += retry_resp.usage.prompt_tokens
            output_tokens += retry_resp.usage.completion_tokens
            raw = retry_resp.choices[0].message.content

            try:
                result = LLMResponse.model_validate_json(raw)
                retry_succeeded = True
                failure_type = None
            except Exception:
                raise

    except Exception as e:
        latency_ms = (time.time() - t_start) * 1000
        cost = _compute_cost(model, input_tokens, output_tokens)
        if session_stats is not None:
            record = CallRecord(
                turn=state.session_turn,
                player_input=player_input[:120],
                success=False,
                failure_type=failure_type or "exception",
                retry_succeeded=False,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                model=model,
            )
            session_stats.record(record)
        raise

    latency_ms = (time.time() - t_start) * 1000
    cost = _compute_cost(model, input_tokens, output_tokens)
    if session_stats is not None:
        record = CallRecord(
            turn=state.session_turn,
            player_input=player_input[:120],
            success=True,
            failure_type=None,
            retry_succeeded=retry_succeeded,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=model,
        )
        session_stats.record(record)
    return result


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    from stats import (COST_PER_INPUT_TOKEN, COST_PER_OUTPUT_TOKEN,
                       SUMMARY_INPUT_TOKEN, SUMMARY_OUTPUT_TOKEN)
    if "mini" in model.lower():
        return input_tokens * SUMMARY_INPUT_TOKEN + output_tokens * SUMMARY_OUTPUT_TOKEN
    return input_tokens * COST_PER_INPUT_TOKEN + output_tokens * COST_PER_OUTPUT_TOKEN


def summarize_context(client, hot_context: list[str], model="gpt-4o-mini", session_stats=None) -> str:
    oldest = hot_context[:3]
    block = "\n".join(oldest)
    t_start = time.time()
    response = client.chat.completions.create(
        model=model,
        max_tokens=200,
        temperature=0.3,
        messages=[
            {"role": "system", "content": "You summarize game session events into a single concise paragraph. Plain prose only. No bullet points. Preserve named entities, locations, items found, and decisions made. Discard atmosphere and description."},
            {"role": "user",   "content": f"Summarize these game turns into one short paragraph:\n\n{block}"}
        ]
    )
    latency_ms = (time.time() - t_start) * 1000
    if session_stats is not None:
        from stats import SUMMARY_INPUT_TOKEN, SUMMARY_OUTPUT_TOKEN
        cost = response.usage.prompt_tokens * SUMMARY_INPUT_TOKEN + response.usage.completion_tokens * SUMMARY_OUTPUT_TOKEN
        record = CallRecord(
            turn=-1,
            player_input="[summarization]",
            success=True,
            failure_type=None,
            retry_succeeded=False,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=model,
        )
        session_stats.record(record)
    return f"[Summary of earlier events]: {response.choices[0].message.content.strip()}"


def generate_recap(client, state, hot_context: list[str], model="gpt-4o-mini", session_stats=None) -> str | None:
    """A short 'previously...' recap shown when a save is resumed. Returns None
    on failure so a recap is never allowed to block loading the game."""
    recent = "\n".join(hot_context[-6:]) if hot_context else "No prior events recorded."
    active_quests = ", ".join(q.title for q in state.quests if q.status == "active") or "none"
    user_message = (
        f"Returning player: {state.player.name}\n"
        f"Current location: {state.location}\n"
        f"Open objectives: {active_quests}\n"
        f"Recent events (oldest to newest):\n{recent}\n\n"
        "Write the recap."
    )
    try:
        t_start = time.time()
        response = client.chat.completions.create(
            model=model,
            max_tokens=180,
            temperature=0.4,
            messages=[
                {"role": "system", "content": "You write a brief 'previously...' recap for a player returning to a text RPG. Two to four sentences, second person, present tense. Remind them where they are, what just happened, and any thread left open. Plain prose, no preamble, no bullet points, no quotation marks around the whole thing."},
                {"role": "user", "content": user_message},
            ],
        )
        latency_ms = (time.time() - t_start) * 1000
        if session_stats is not None:
            from stats import SUMMARY_INPUT_TOKEN, SUMMARY_OUTPUT_TOKEN
            cost = response.usage.prompt_tokens * SUMMARY_INPUT_TOKEN + response.usage.completion_tokens * SUMMARY_OUTPUT_TOKEN
            session_stats.record(CallRecord(
                turn=-1,
                player_input="[recap]",
                success=True,
                failure_type=None,
                retry_succeeded=False,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                model=model,
            ))
        return response.choices[0].message.content.strip()
    except Exception:
        return None
