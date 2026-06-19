import os
import time
import re
import math
from .schema import LLMResponse, WorldTick
from .engine import EngineState, NPCRecord, WorldFact
from .logs import load_region, load_npc
from .stats import CallRecord
from .config import MODEL_NARRATIVE, MODEL_SUMMARY, reasoning_kwargs


TEMPLATES_DIR = "templates"
PLAYBOOK_PATH = "playbook.md"

# Sent on the first turn to generate the opening scene. Lean on purpose: the
# craft guidance now rides in the injected "opening" director's note, so this
# just kicks it off and points at the structural fields to set.
SEED_INSTRUCTION = (
    "Begin the game — write the opening scene per the director's note. Set "
    "location, location_is_new, location_type, and location_summary, and give the "
    "player any starting gear their background implies."
)


def load_system_prompt() -> str:
    with open("system_prompt.md", "r") as f:
        return f.read()


def load_situation(situation: str) -> str | None:
    """Return the director's note for a beat from playbook.md. The file is a set
    of `## <id>` sections; we return the body from a matching header up to the
    next `## ` (or EOF). Read live each call so the file can be edited mid-play."""
    if not situation or not os.path.exists(PLAYBOOK_PATH):
        return None
    target = situation.strip().lower()
    body, capturing = [], False
    with open(PLAYBOOK_PATH, "r") as f:
        for line in f:
            if line.startswith("## "):
                if capturing:
                    break
                capturing = line[3:].strip().lower() == target
                continue
            if capturing:
                body.append(line.rstrip("\n"))
    text = "\n".join(body).strip()
    return text or None


# Whole-word cues for classifying the player's beat, checked in priority order.
# The engine guesses the situation so the matching note can be injected before the
# call; the model still adapts if the guess is off. Matched on word boundaries so
# "move" doesn't fire on "remove" or "up" on "pick up".
_BEAT_CUES = [
    ("orientation", ("where am i", "where are we", "which way", "exits",
                     "how do i get there", "where can i go")),
    ("survey", ("look around", "looks around", "look about", "what do i see",
                "what can i see", "describe", "surroundings", "survey",
                "what is here", "whats here", "what's here")),
    ("trade", ("buy", "sell", "purchase", "haggle", "barter", "how much",
               "trade for", "what will you give", "browse the wares", "for sale")),
    ("stealth", ("sneak", "hide", "steal", "pickpocket", "pick the lock", "lockpick",
                 "slip past", "creep", "stay hidden", "tiptoe", "snatch", "swipe",
                 "tail", "keep to the shadows", "in the shadows", "unseen",
                 "without being seen", "out of sight", "slink")),
    ("search", ("search", "examine", "inspect", "investigate", "look at", "look in",
                "look inside", "loot", "rummage", "read", "study", "check")),
    ("dialogue", ("talk", "speak", "ask", "tell", "say", "says", "greet", "shout",
                  "whisper", "answer", "reply", "call out")),
    ("rest", ("rest", "sleep", "camp", "make camp", "nap", "bed down", "take watch",
              "wait", "pass the time", "doze")),
    ("action", ("attack", "fight", "hit", "swing", "strike", "stab", "slash",
                "shoot", "kill", "punch", "kick", "charge", "lunge", "shove",
                "tackle", "throw", "chase", "flee", "dodge", "parry", "ambush",
                "block", "confront", "square up", "rush")),
    ("travel", ("journey", "set out", "set off", "travel to", "ride to",
                "make my way to", "march to", "head for")),
    ("movement", ("go", "walk", "head", "travel", "enter", "leave", "climb",
                  "cross", "follow", "approach", "north", "south", "east", "west",
                  "upstairs", "downstairs", "toward", "return", "make for",
                  "make my way", "head out", "head over", "press on", "move to",
                  "move toward", "step out", "step into", "wander")),
]


def classify_situation(player_input: str, state: EngineState, is_opening: bool = False) -> str:
    """Pick the director's-note beat for this turn from the player's input."""
    if is_opening:
        return "opening"
    text = player_input.lower().strip()
    # "go in search of X" / "in search of X" is travel intent, not searching the
    # room — neutralize the idiom so the bare "search" cue can't hijack the turn
    # into a "lead with the find" beat when the player is actually leaving.
    text = text.replace("in search of", "toward")
    if '"' in player_input:  # quoted speech is a strong dialogue signal
        return "dialogue"
    for situation, cues in _BEAT_CUES:
        for cue in cues:
            if re.search(rf"\b{re.escape(cue)}\b", text):
                return situation
    return "small"


# A dash used as a clause break (em dash, en dash, or a double hyphen) gets a
# space on each side so it never renders glued to its neighbours ("Row—halfway").
# Single hyphens in compound words (watch-house, work-worn) are left untouched.
_DASH_BREAK = re.compile(r"\s*(?:—|–|--)\s*")


def normalize_prose(text: str) -> str:
    """Tidy up the model's text for display: put spaces around dashes used as
    clause breaks, and squeeze any double spaces that creates back down to one.
    Running it twice on the same text changes nothing the second time."""
    if not text:
        return text
    text = _DASH_BREAK.sub(" — ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def load_template(category: str, key: str) -> str | None:
    """Read an editable blueprint at templates/<category>/<key>.md. Returns None
    when there's no matching template, so injection is always optional."""
    if not key:
        return None
    filename = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_") + ".md"
    filepath = os.path.join(TEMPLATES_DIR, category, filename)
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return f.read().strip()
    return None


def _named_npc_ids(player_input: str, npcs: dict[str, NPCRecord]) -> list[str]:
    """Ids of known NPCs the player named this turn, so we can pull their card
    even if they aren't the active NPC. Matches on the full display name or any
    distinctive (3+ char) word of it."""
    text = player_input.lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    matched = []
    for npc_id, rec in npcs.items():
        name = rec.name.lower()
        if name and name in text:
            matched.append(npc_id)
            continue
        name_words = [w for w in re.findall(r"[a-z0-9]+", name) if len(w) >= 3]
        if name_words and any(w in tokens for w in name_words):
            matched.append(npc_id)
    return matched


def _npc_card(rec: NPCRecord) -> str:
    lines = [f"{rec.name} (id: {rec.id}) [{rec.role or 'unknown role'}] — disposition {rec.disposition}, last seen turn {rec.last_seen_turn}"]
    if rec.location:
        lines.append(f"  whereabouts: {rec.location}")
    if rec.description:
        lines.append(f"  appearance: {rec.description}")
    if rec.voice:
        lines.append(f"  voice: {rec.voice}")
    if rec.facts:
        lines.append(f"  known: {'; '.join(rec.facts)}")
    return "\n".join(lines)


# Common words that carry no recall signal — dropped before scoring.
_RECALL_STOPWORDS = frozenset("""
the a an and or but of to in on at by for with from into onto off up down out over under
is are was were be been being am do does did doing have has had having will would shall
should can could may might must not no nor so than then that this these those there here
i you he she it we they me him her us them my your his its our their mine yours
who whom whose which what when where why how all any both each few more most other some such
as if about against between through during before after above below again further once
i'm you're it's don't didn't can't won't get got go goes going went come came take took
say said says look looks looked see saw seen want wants make made just like now still even
""".split())


def _content_tokens(text: str) -> list[str]:
    """Break text into lowercase words of 3+ letters, dropping common filler words
    (the, and, you, ...). What's left are the words worth matching on."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) >= 3 and t not in _RECALL_STOPWORDS]


def recall_memories(state: EngineState, player_input: str,
                    exclude_texts: set[str] | None = None, k: int = 4) -> list[str]:
    """Look up the few past notes most relevant to what the player just mentioned,
    so a detail from many turns ago comes back into the prompt instead of being
    quietly contradicted. Plain Python, no extra model call.

    It only searches what's already in memory (no reading files off disk): journal
    chapters, world facts, and the facts on each NPC. It scores each note by how
    many distinctive words it shares with the player's input, and returns the top
    few as ready-to-show lines, newest first among ties. This catches a detail the
    player names, not a detail they only hint at in different words."""
    exclude_texts = exclude_texts or set()
    query = set(_content_tokens(player_input))
    if not query:
        return []

    # Build a (label, text, word-set) entry for every past note we could recall.
    notes: list[tuple[str, str, set[str]]] = []
    for ch in state.journal:
        body = f"{ch.get('title', '')}. {ch.get('text', '')}".strip()
        notes.append((f"journal, turn {ch.get('turn', '?')}", body, set(_content_tokens(body))))
    for f in state.world_facts:
        if f.text in exclude_texts:
            continue  # already shown word-for-word in the WORLD FACTS block
        label = "fact" + (f" ({f.location})" if f.location else "")
        notes.append((label, f.text, set(_content_tokens(f.text))))
    for rec in state.npcs.values():
        for fact in rec.facts:
            body = f"{rec.name}: {fact}"
            notes.append((f"about {rec.name}", body, set(_content_tokens(body))))

    if not notes:
        return []

    # Count how many notes each word shows up in. A shared word only helps a match
    # if it's distinctive (in no more than ~60% of notes), so a word that's
    # everywhere can't pad the results; rarer shared words count for more (that's
    # what the log below does — fewer notes containing a word means a bigger number).
    total = len(notes)
    word_counts: dict[str, int] = {}
    for _, _, words in notes:
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
    common_word_cutoff = max(1, int(0.6 * total))

    scored = []
    for idx, (label, body, words) in enumerate(notes):
        shared = query & words
        score = sum(math.log((total + 1) / word_counts[w]) for w in shared
                    if word_counts[w] <= common_word_cutoff)
        if score > 0:
            scored.append((score, idx, label, body))
    if not scored:
        return []

    # Best match first; if two tie, the newer note wins (it was added later).
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    out = []
    for _, _, label, body in scored[:k]:
        snippet = body if len(body) <= 240 else body[:237].rstrip() + "…"
        out.append(f"- [{label}] {snippet}")
    return out


def build_retrieval_context(state: EngineState, player_input: str) -> str:
    """Assemble everything relevant for this turn: the current region log, the
    roster of NPCs present here, deep cards for any NPC in focus or named,
    world facts in scope, and the matching location/dialogue blueprints."""
    blocks = []

    if state.location and state.location != "unknown":
        region_log = load_region(state.location)
        if region_log:
            blocks.append(f"REGION LOG — {state.location}:\n{region_log}")

    # Established geography out of here — keep layout consistent on return.
    conns = state.connections_from(state.location)
    if conns:
        lines = [f"- {d} → {place}" for d, place in conns.items()]
        blocks.append("CONNECTIONS FROM HERE (established layout — stay consistent):\n" + "\n".join(lines))

    # PEOPLE HERE — everyone the engine thinks is at this location right now, so the
    # model knows who's around even if the player hasn't named them.
    roster = state.npcs_at(state.location)
    if roster:
        lines = []
        for rec in roster:
            latest = f"; {rec.facts[-1]}" if rec.facts else ""
            lines.append(f"- {rec.name} (id: {rec.id}) [{rec.role or 'unknown role'}] (disposition {rec.disposition}{latest})")
        blocks.append("PEOPLE HERE (present at this location):\n" + "\n".join(lines))

    # NPC CARD(S) — deep recall for whoever is in focus or named this turn.
    deep_ids = []
    if state.active_npc:
        deep_ids.append(state.active_npc)
    for npc_id in _named_npc_ids(player_input, state.npcs):
        if npc_id not in deep_ids:
            deep_ids.append(npc_id)
    roles = []
    for npc_id in deep_ids:
        rec = state.npcs.get(npc_id)
        if not rec:
            continue
        if rec.role and rec.role not in roles:
            roles.append(rec.role)
        card = _npc_card(rec)
        prose = load_npc(npc_id)
        if prose:
            card += f"\n  history:\n{prose}"
        blocks.append(f"NPC CARD — {rec.name}:\n{card}")

    facts = state.relevant_world_facts(state.location)
    if facts:
        lines = [f"- {f.text}" + (f" ({f.location})" if f.location else "") for f in facts]
        blocks.append("WORLD FACTS (true here / globally — never contradict):\n" + "\n".join(lines))

    # Pull the handful of past notes most relevant to what the player just
    # mentioned, so old details come back into the prompt. Skip any world fact
    # already shown in the block above so it isn't listed twice.
    recalled = recall_memories(state, player_input, exclude_texts={f.text for f in facts})
    if recalled:
        blocks.append("RELEVANT MEMORIES (recalled by reference — ground truth, may be old):\n"
                      + "\n".join(recalled))

    # Editable blueprints, injected by tag. The engine only knows a location's
    # type and an NPC's role from a previous turn, so first arrivals/meetings
    # fall back to the prompt's baseline guidance.
    loc_type = state.location_types.get(state.location)
    loc_tmpl = load_template("locations", loc_type) if loc_type else None
    if loc_tmpl:
        blocks.append(f"LOCATION BLUEPRINT ({loc_type}) — follow this when describing the place:\n{loc_tmpl}")
    for role in roles:
        dlg_tmpl = load_template("dialogue", role)
        if dlg_tmpl:
            blocks.append(f"DIALOGUE BLUEPRINT ({role}) — follow this in their dialogue:\n{dlg_tmpl}")

    return "\n\n".join(blocks) if blocks else "No prior logs retrieved."


# Special marker value handed back for a /use of a story-only item: the main loop
# should play it as a normal turn so the model can narrate it. (This is different
# from returning None, which means "I didn't recognize that command".)
PLAY_AS_ACTION = object()


def handle_local_command(cmd: str, state: EngineState):
    """Resolve a slash command (leading '/' already stripped) to a read-out string.
    Commands are matched EXACTLY on their first word — there's no fuzzy intent
    detection, because the slash makes intent explicit and avoids false positives
    where ordinary prose ('I check the inventory') would trip a read-out.

    Returns: a string to show, PLAY_AS_ACTION for a /use of a narrative item
    (the loop plays it as an LLM turn), or None for an unrecognized command."""
    low = cmd.lower().strip()
    word = low.split()[0] if low else ""

    if word in ("inventory", "inv", "i"):
        return format_inventory_display(state)
    if word in ("hp", "health", "status"):
        return f"{state.player.name}: {state.hp}/{state.max_hp} HP"
    if word in ("time", "clock"):
        return f"Time: {state._time_label()}"
    if word in ("location", "where"):
        return f"Location: {state.location}"
    if word in ("map", "paths"):
        return format_world_map(state)
    if word in ("quests", "quest", "questlog"):
        return format_quest_log(state)
    if word in ("people", "who", "npcs"):
        return format_npc_directory(state)
    if word in ("chronicle", "world", "facts", "history"):
        return format_world_chronicle(state)
    if word in ("recap", "story", "synopsis"):
        return "Story so far\n" + (state.synopsis.strip() or
                                   "It's early yet — not much has happened to recount.")

    if word == "equip":
        item_name = cmd[len("equip"):].strip().lower()
        for w in state.weapons:
            if w.name.lower() == item_name:
                state.equipped_weapon = w
                return f"Equipped: {w.name} (1-{w.damage_range} dmg)"
        for a in state.armor:
            if a.name.lower() == item_name:
                state.equipped_armor = a
                return f"Equipped: {a.name} ({a.armor_value} armor)"
        return f"'{item_name}' not found in inventory."

    if word == "use":
        item_name = cmd[len("use"):].strip()
        match = next((c for c in state.consumables if c.name.lower() == item_name.lower()), None)
        if match is None:
            return f"'{item_name}' isn't something you can use."
        # Mechanical effects (heal/harm/maxhp/buff) resolve locally, no API call.
        result = state.apply_consumable_effect(match)
        if result is not None:
            state.consumables.remove(match)
            return result
        # Narrative-only item: let the loop play it as a real turn so the LLM
        # narrates the effect (and decides whether it's consumed).
        return PLAY_AS_ACTION

    return None


def _spare_names(items, equipped_name: str) -> list[str]:
    """Names of owned items minus the one that's currently equipped. The equipped
    weapon/armor also lives in the owned list (it's auto-equipped on pickup), so
    the Bag should show only the spares — otherwise one sword reads as two."""
    out, skipped = [], False
    for it in items:
        if not skipped and it.name == equipped_name:
            skipped = True
            continue
        out.append(it.name)
    return out


def format_inventory_display(state: EngineState) -> str:
    def names(parts):
        return ", ".join(parts) if parts else "none"

    lines = [
        "Inventory",
        "Equipment:",
        f"- Weapon: {state.equipped_weapon.name} (1-{state.equipped_weapon.damage_range} dmg)",
        f"- Armor:  {state.equipped_armor.name} ({state.equipped_armor.armor_value} armor)",
        "Bag (spares):",
        f"- Weapons: {names(_spare_names(state.weapons, state.equipped_weapon.name))}",
        f"- Armor: {names(_spare_names(state.armor, state.equipped_armor.name))}",
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
            if q.stages:
                lines.append(f"      progress: {q.stages[-1]}")
    if completed:
        lines.append("Completed:")
        for q in completed:
            lines.append(f"  [{q.title}] {q.description}")
    if failed:
        lines.append("Failed:")
        for q in failed:
            lines.append(f"  [{q.title}] {q.description}")
    return "\n".join(lines)


def _disposition_word(score: int) -> str:
    """A readable label for an NPC's standing toward the player."""
    if score <= -6:
        return "hostile"
    if score <= -2:
        return "wary"
    if score <= 1:
        return "neutral"
    if score <= 5:
        return "friendly"
    return "loyal"


def format_npc_directory(state: EngineState) -> str:
    """The people the player has met: who, where, how they stand, what's known."""
    if not state.npcs:
        return "People\nYou haven't met anyone worth remembering yet."
    lines = ["People you've met"]
    for rec in sorted(state.npcs.values(), key=lambda r: -r.last_seen_turn):
        role = f", {rec.role}" if rec.role else ""
        where = f" — at {rec.location}" if rec.location else ""
        lines.append(f"  {rec.name} ({_disposition_word(rec.disposition)}{role}){where}")
        if rec.facts:
            lines.append(f"      {rec.facts[-1]}")
    return "\n".join(lines)


def format_world_map(state: EngineState) -> str:
    """The paths the player has walked, as a directional map."""
    if not state.location_graph:
        return "Map\nNo paths charted yet — explore and the way between places will be remembered."
    lines = ["Map — paths you've walked"]
    for place in sorted(state.location_graph):
        here = "  (you are here)" if place == state.location else ""
        lines.append(f"{place}{here}")
        for direction, dest in state.location_graph[place].items():
            lines.append(f"    {direction} → {dest}")
    return "\n".join(lines)


def format_world_chronicle(state: EngineState) -> str:
    """The durable consequences the player has left on the world."""
    if not state.world_facts:
        return "Chronicle\nThe world is much as you found it. Nothing of note has changed by your hand."
    by_place: dict[str, list[str]] = {}
    global_facts: list[str] = []
    for f in state.world_facts:
        if f.location:
            by_place.setdefault(f.location, []).append(f.text)
        else:
            global_facts.append(f.text)
    lines = ["Chronicle — what's changed"]
    if global_facts:
        lines.append("Across the world:")
        for t in global_facts:
            lines.append(f"  - {t}")
    for place, facts in by_place.items():
        lines.append(f"{place}:")
        for t in facts:
            lines.append(f"  - {t}")
    return "\n".join(lines)


def _stream_completion(client, request_kwargs, on_delta):
    """Run a Structured-Outputs request in streaming mode, pushing the growing
    `narrative` field to on_delta as it generates, and return the final parsed
    completion (same object .parse would return). `event.parsed` is the partial
    parsed object; narrative is field #1 so it fills in first."""
    emitted = 0
    # include_usage makes the API emit a final usage chunk, so get_final_completion
    # carries token counts (otherwise streamed turns would record 0 and gut stats).
    with client.chat.completions.stream(**request_kwargs, stream_options={"include_usage": True}) as stream:
        for event in stream:
            if event.type != "content.delta":
                continue
            parsed = event.parsed
            narrative = None
            if isinstance(parsed, dict):
                narrative = parsed.get("narrative")
            elif parsed is not None:
                narrative = getattr(parsed, "narrative", None)
            if isinstance(narrative, str) and len(narrative) > emitted:
                on_delta(narrative[emitted:])
                emitted = len(narrative)
        return stream.get_final_completion()


def call_llm(client, system_prompt, state, hot_context, player_input, model=MODEL_NARRATIVE,
             session_stats=None, force_situation: str | None = None, on_delta=None) -> LLMResponse:
    context_block = "\n".join(hot_context) if hot_context else "No prior context."
    retrieved_block = build_retrieval_context(state, player_input)
    synopsis_block = state.synopsis.strip() if state.synopsis else "Nothing yet — this is early in the story."

    # Put the director's note for this beat right before the player's input. The
    # model pays most attention to the last thing it reads, so the guidance lands
    # better here than buried up in a long system prompt. force_situation lets the
    # engine set the beat directly (e.g. a defeat aftermath) instead of guessing it
    # from the player's words.
    situation = force_situation or classify_situation(
        player_input, state, is_opening=(player_input == SEED_INSTRUCTION))
    note = load_situation(situation)
    note_block = f"\nDIRECTOR'S NOTE ({situation} beat):\n{note}\n" if note else ""
    # The beat is classified before the response, so we can't yet know whether a
    # move lands somewhere new. Attach the arrival note to movement/travel beats so
    # the model has the depth to paint a first arrival when the move opens onto one.
    if situation in ("movement", "travel"):
        arrival_note = load_situation("arrival")
        if arrival_note:
            note_block += ("\nIF THIS MOVE OPENS ONTO SOMEWHERE NEW, run it as an arrival "
                           f"instead of a quick move:\n{arrival_note}\n")
    tone = state.player.tone.strip() if state.player.tone else "the character's own plain, honest voice"

    # This closing line is the very last thing the model reads before it writes, so
    # it gets the most attention. We use it to remind the model of the two things a
    # small model most often slips on — the beat and the voice. The shape of the
    # reply is handled by Structured Outputs, so it doesn't need restating here.
    user_message = f"""ENGINE STATE:
{state.to_prompt_string()}

STORY SO FAR:
{synopsis_block}

RETRIEVED LOGS:
{retrieved_block}

RECENT CONTEXT:
{context_block}
{note_block}
PLAYER INPUT:
{player_input}

Now write your reply as a {situation} beat, in this exact voice: {tone}. Keep it
tight; don't reach for a clever line, and don't reuse an image or phrase you've
already leaned on this scene."""

    t_start = time.time()
    failure_type = None
    input_tokens = 0
    output_tokens = 0
    result = None

    request_kwargs = dict(
        model=model,
        max_completion_tokens=4000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        response_format=LLMResponse,
        **reasoning_kwargs(),
    )

    try:
        # Structured Outputs: the API constrains generation to the LLMResponse
        # schema, so the result is guaranteed valid — no prose JSON-policing and no
        # parse/retry. A small model spends its budget on the narrative, not braces.
        # When on_delta is given, stream: `narrative` is field #1 of the schema, so
        # it generates first and we push it to the UI live while the (invisible)
        # state JSON streams after it. The final object is read the same either way.
        if on_delta is not None:
            completion = _stream_completion(client, request_kwargs, on_delta)
        else:
            completion = client.chat.completions.parse(**request_kwargs)
        usage = getattr(completion, "usage", None)  # may be absent on a stream
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        msg = completion.choices[0].message
        result = msg.parsed
        if result is None:
            failure_type = "refusal" if getattr(msg, "refusal", None) else "incomplete"
    except Exception:
        latency_ms = (time.time() - t_start) * 1000
        if session_stats is not None:
            session_stats.record(CallRecord(
                turn=state.session_turn, player_input=player_input[:120],
                success=False, failure_type=failure_type or "exception",
                retry_succeeded=False, input_tokens=input_tokens,
                output_tokens=output_tokens, latency_ms=latency_ms, model=model,
            ))
        raise

    latency_ms = (time.time() - t_start) * 1000
    if session_stats is not None:
        session_stats.record(CallRecord(
            turn=state.session_turn, player_input=player_input[:120],
            success=result is not None, failure_type=failure_type,
            retry_succeeded=False, input_tokens=input_tokens,
            output_tokens=output_tokens, latency_ms=latency_ms, model=model,
        ))
    if result is None:
        raise RuntimeError(f"structured output failed: {failure_type}")
    result.narrative = normalize_prose(result.narrative)
    return result


SYNOPSIS_SYSTEM_PROMPT = (
    "You maintain a running 'story so far' for an ongoing text RPG — the durable "
    "memory of the whole playthrough. You are given the prior synopsis and the "
    "most recent turns being aged out of the live transcript. Fold the new events "
    "into the synopsis and return the COMPLETE updated synopsis (not just the new "
    "part). Plain prose, a few short paragraphs at most. Preserve what matters for "
    "continuity: named people and places, promises, debts, threats, and bargains, "
    "consequences of what the player did, unresolved threads, and how key "
    "relationships stand. Compress old detail rather than deleting it — keep the "
    "through-line intact. Drop only moment-to-moment scenery that carries no future "
    "weight. Write it so a narrator could read it and continue the story without "
    "contradicting anything."
)


def update_synopsis(client, prior_synopsis: str, evicted_turns: list[str],
                    model=MODEL_SUMMARY, session_stats=None) -> str:
    """Fold the oldest turns (the ones being dropped from recent history) into the
    running "story so far" summary and return the whole updated summary. It keeps
    what matters — people, places, promises, consequences, open threads — and only
    drops passing scenery. On any failure it returns the old summary unchanged, so
    memory is never lost."""
    prior = prior_synopsis.strip() or "(none yet)"
    block = "\n".join(evicted_turns) if evicted_turns else "(no new turns)"
    user_message = (
        f"PRIOR SYNOPSIS:\n{prior}\n\n"
        f"NEW TURNS TO FOLD IN (oldest first):\n{block}\n\n"
        "Return the complete updated synopsis."
    )
    t_start = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=600,
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYNOPSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception:
        return prior_synopsis
    latency_ms = (time.time() - t_start) * 1000
    if session_stats is not None:
        session_stats.record(CallRecord(
            turn=-1,
            player_input="[synopsis]",
            success=True,
            failure_type=None,
            retry_succeeded=False,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            latency_ms=latency_ms,
            model=model,
        ))
    updated = response.choices[0].message.content.strip()
    return updated or prior_synopsis


CHRONICLER_SYSTEM_PROMPT = (
    "You are the player character keeping a personal travel journal during an "
    "ongoing text RPG. Given the story so far and the most recent events, write "
    "the NEXT short journal entry — three to six sentences, first person, past "
    "tense, as if jotting down what just happened and how it sat with them. "
    "Cover the recent stretch, not the whole history, and don't repeat earlier "
    "entries. Name the people and places that mattered. Write it entirely in this "
    "voice and tone: {tone}. Output exactly two parts: a short evocative TITLE on "
    "the first line, then the entry. No preamble, no quotation marks, no markdown."
)


def write_journal_chapter(client, synopsis: str, recent_events: list[str], tone: str,
                          turn: int, model=MODEL_SUMMARY, session_stats=None) -> dict | None:
    """Compose one player-facing journal chapter from snapshots of game state.
    Pure read of its string inputs — safe to run on a background thread. Returns
    {turn, title, text} or None on failure (a missed chapter is harmless)."""
    spine = synopsis.strip() or "(the story has barely begun)"
    recent = "\n".join(recent_events[-12:]) if recent_events else "(nothing notable yet)"
    system = CHRONICLER_SYSTEM_PROMPT.format(tone=tone or "the character's own plain, honest voice")
    user_message = (
        f"STORY SO FAR:\n{spine}\n\nMOST RECENT EVENTS (oldest first):\n{recent}\n\n"
        "Write the next journal entry."
    )
    t_start = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=320,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception:
        return None
    latency_ms = (time.time() - t_start) * 1000
    if session_stats is not None:
        session_stats.record(CallRecord(
            turn=-1, player_input="[chronicle]", success=True, failure_type=None,
            retry_succeeded=False, input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens, latency_ms=latency_ms, model=model,
        ))
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        return None
    title, _, body = raw.partition("\n")
    title = title.strip().lstrip("#").strip(" *\"'") or "Journal entry"
    body = normalize_prose(body.strip()) or title
    return {"turn": turn, "title": title, "text": body}


WORLD_DIRECTOR_SYSTEM_PROMPT = (
    "You are the unseen director of a living world in a solo text RPG. Between the "
    "player's scenes the world keeps turning on its own. Given the story so far, the "
    "established world facts, the people known, and the open quests, propose ONE or "
    "TWO small developments that advance threads ALREADY in motion while the player "
    "is elsewhere: an NPC acts on a known grudge or goal, travels somewhere, a planted "
    "tension escalates or cools, word spreads. STRICT RULES — only use people, places, "
    "and quests that already exist (reuse the exact NPC ids and quest ids given); never "
    "invent new named characters or locations; never change the player's health, "
    "inventory, or position; never contradict an established fact. Keep developments "
    "quiet and plausible — the world breathing, not a plot twist. If nothing should "
    "change yet, return an empty developments list."
)


def run_world_tick(client, synopsis: str, facts_block: str, npcs_block: str,
                   quests_block: str, recent_block: str = "", model=MODEL_SUMMARY,
                   session_stats=None) -> WorldTick | None:
    """Ask the world-director for 1–2 offscreen developments on EXISTING entities.
    Pure read of its string inputs — safe on a background thread. Returns a WorldTick
    (possibly empty) or None on failure (a missed tick is harmless)."""
    spine = synopsis.strip() or "(the story has barely begun)"
    user_message = (
        f"STORY SO FAR:\n{spine}\n\n"
        f"ESTABLISHED WORLD FACTS:\n{facts_block or '(none)'}\n\n"
        f"PEOPLE KNOWN (use these exact ids):\n{npcs_block or '(none)'}\n\n"
        f"OPEN QUESTS (use these exact ids):\n{quests_block or '(none)'}\n\n"
        f"RECENT EVENTS (what the player just did — react to this, don't repeat it):\n"
        f"{recent_block or '(nothing notable yet)'}\n\n"
        "Propose the next developments (or an empty list)."
    )
    t_start = time.time()
    try:
        completion = client.chat.completions.parse(
            model=model,
            max_completion_tokens=500,
            messages=[
                {"role": "system", "content": WORLD_DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=WorldTick,
        )
    except Exception:
        return None
    latency_ms = (time.time() - t_start) * 1000
    if session_stats is not None:
        usage = getattr(completion, "usage", None)
        session_stats.record(CallRecord(
            turn=-1, player_input="[world-tick]", success=True, failure_type=None,
            retry_succeeded=False,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms, model=model,
        ))
    return completion.choices[0].message.parsed


def apply_world_tick(state: EngineState, tick: WorldTick) -> list[str]:
    """Fold offscreen developments into EXISTING state only — never creates a new
    named NPC or place, never touches the player's hp/inventory/position. Returns
    the summaries actually applied (for logging). Caller must be the sole state
    writer (the game thread)."""
    applied = []
    for d in tick.developments[:2]:  # defensive cap
        did = False
        if d.world_fact and d.world_fact.strip():
            text = d.world_fact.strip()
            loc = (d.world_fact_location or "").strip() or None
            if not any(f.text == text and f.location == loc for f in state.world_facts):
                state.world_facts.append(WorldFact(text=text, location=loc, turn=state.session_turn))
                did = True
        if d.npc_id and d.npc_id in state.npcs:  # EXISTING npc only — no spawning
            rec = state.npcs[d.npc_id]
            if d.npc_new_location and d.npc_new_location.strip():
                rec.location = d.npc_new_location.strip()
                did = True
            if d.npc_note and d.npc_note.strip() and d.npc_note.strip() not in rec.facts:
                rec.facts.append(d.npc_note.strip())
                did = True
        if d.quest_id and d.quest_stage and d.quest_stage.strip():
            for q in state.quests:
                if q.id == d.quest_id and q.status == "active":
                    q.stages.append(d.quest_stage.strip())
                    did = True
                    break
        if did:
            applied.append(d.summary.strip())
    return applied


def generate_recap(client, state, hot_context: list[str], model=MODEL_SUMMARY, session_stats=None) -> str | None:
    """A short 'previously...' recap shown when a save is resumed. Returns None
    on failure so a recap is never allowed to block loading the game."""
    recent = "\n".join(hot_context[-6:]) if hot_context else "No prior events recorded."
    active_quests = ", ".join(q.title for q in state.quests if q.status == "active") or "none"
    story_so_far = state.synopsis.strip() or "(nothing recorded yet)"
    user_message = (
        f"Returning player: {state.player.name}\n"
        f"Current location: {state.location}\n"
        f"Open objectives: {active_quests}\n"
        f"Story so far:\n{story_so_far}\n\n"
        f"Most recent events (oldest to newest):\n{recent}\n\n"
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
            session_stats.record(CallRecord(
                turn=-1,
                player_input="[recap]",
                success=True,
                failure_type=None,
                retry_succeeded=False,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                latency_ms=latency_ms,
                model=model,
            ))
        return normalize_prose(response.choices[0].message.content.strip())
    except Exception:
        return None
