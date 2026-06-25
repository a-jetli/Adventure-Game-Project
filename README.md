# Text based adventure game project

I wrote this as a simple text based RPG in Python. It uses an OpenAI model to generate the world, scenes, and decide when to enter combat, and it saves progress under `logs/`. The initial idea was to make a playable book adventure where you pick the kind of world you want — grounded low fantasy, a cyberpunk dystopia, an age-of-sail frontier, or whatever you describe at the start — with an LLM serving as a sort of "dungeon master", where you can do pretty much anything you want afterwards. The way I thought to implement this was building a system where the LLM doesn't own the entire game state directly, but still manages narrative freedom.

## What I used

- Python
- OpenAI API
- `pygame` for the UI version

## How to run it

1. You'll need your own API key (I used OpenAI, but any OpenAI-compatible provider works — see Notes).
2. Install the Python dependencies `Pygame`, `Pydantic` and `python-dotenv`, as well as `openai` (or the dependencies for your model of choice):
```bash 
pip install pygame pydantic python-dotenv openai
```
3. Run the game from the project root (may differ slightly by platform / Python version):

```bash
python game_ui.py
```

4. On first run, the game walks you through a quick setup — pick a provider and paste your key, and it writes a local `.env` for you. (You can still copy `.env.example` to `.env` and edit it by hand if you prefer; see Notes. Re-run setup anytime from the Settings menu.)


## How it works

The core lives in a `game/` package, with the single entry point (`game_ui.py`) and the prompts kept at the root. I split it up so the model never gets to own the whole game by itself. `game/engine.py` keeps the current master state for the player, inventory, time, location, NPCs, and the world. After each turn, the game only applies changes that come back through the Pydantic schema in `game/schema.py`, so the LLM has to stay inside a typed contract instead of inventing state directly. That contract is enforced at the API level with OpenAI Structured Outputs — the response is constrained to the schema as it's generated, so it can't come back malformed and there's no parse-and-retry dance. Offloading "is the JSON shaped right" to the API also frees a small model's limited attention for the prose itself.

`game_ui.py` is the Pygame client and where the LLM request gets built. It sends the current engine state, the running story synopsis, recent hot context, and relevant cold context. It also handles the local commands before the request ever reaches the model — every one starts with a slash, so ordinary prose ("I check the inventory") can never trip a read-out by accident. The read-outs: `/inventory`, `/hp`, `/time`, `/location`, `/map`, `/quests`, `/people` (who you've met and how they regard you), `/chronicle` (what you've changed in the world), and `/recap` (the story so far). There's also `/equip [item]`, `/use [item]`, `/journal`, `/export` (writes your story out as a Markdown book), `/tutorial`, `/settings`, `/theme`, and `/help`. They run instantly and locally, no API call. (`/use` on a one-off narrative item is the exception — it falls through to a real turn so the model can narrate what happens.)

The game uses a layered memory setup. The hot context is the recent turn history; as it grows, the oldest turns are folded into a durable, evolving "story so far" synopsis (kept in state and persisted) rather than discarded. The cold storage lives under `logs/`, where markdown files for the world, regions, NPCs, and events are kept. `game/logs.py` writes those and loads them back on demand. Each turn the engine assembles only what's relevant — the current region, the people present, cards for anyone named, the world facts, the connections out of the current place, and the synopsis. On top of that, a quick lookup (plain Python, no extra model call) finds the handful of past notes — journal entries, world facts, things people told you — most relevant to whatever you just mentioned, so a detail from forty turns ago can come back instead of being quietly contradicted. All of it keeps the model consistent without stuffing everything into the prompt.

The story loop lives in `game_ui.py`: load a save, take input, send it to the model, apply the returned state changes, write logs, autosave, and keep going. (The old terminal entry, `main.py`, has been retired to a stub — the Pygame client is the way to play.)

Combat is attack, use item, or flee. The model can trigger a fight by returning an encounter, but the damage rolls and HP changes happen locally; item effects and buffs work mid-fight. When the fight ends — won, lost, or fled — the model writes a short aftermath beat: what you took off the body, what running cost you, where you came to, so a fight never just hands back a dice log. Losing isn't a game over — you come to wounded, robbed, or dragged somewhere worse, and the story carries on from the setback. The round-by-round combat words don't assume swords, so a gunfight or a bare-knuckle brawl reads right too. The world has a consistent geography: when you travel a direction, the engine records the path so places stay where you left them (see `/map`).

You pick the world at the start: when you make a character you describe the setting in your own words ("rain-soaked cyberpunk dystopia", "age of sail", or leave it blank for low fantasy), the voice you want it told in, and a background, and the model commits to that genre for the whole book. The engine underneath is genre-agnostic — a stimpack and a healing draught are the same `heal` to it, a flak vest and plate armor the same damage reduction — so the setting mostly steers the prose and which place/character blueprints apply. The built-in blueprints are fantasy (under `templates/fantasy/`); a non-fantasy world leans on the model directly, and a fantasy blueprint never bleeds into your cyberpunk run.

A few things keep the world feeling alive, and none of them block your turn. The narration **streams** onto the screen as the model writes it, instead of appearing all at once after a wait. A background **chronicler** keeps a running journal in your character's own voice, written continuously as you play — read it from `/journal`, or `/export` the whole thing as a keepable book. And a quiet **world director** advances things offscreen between scenes: an NPC you crossed acts on the grudge, a tension you left behind escalates, someone moves on — all within the engine's typed contract (it only ever advances people, places, and quests that already exist), so coming back somewhere actually means something. These run on background threads and fold their results back into the same world state the model reads from.

The model starts quests when you commit to something and you can pull them up with `/quests`. Items do things: healing and combat buffs are applied by the engine, while stranger one-off items get narrated. Saves are per-character slots managed from the menu (New / Load / Manage), with an autosave each turn, and loading gives you a quick recap. On first run, an in-game setup screen walks you through picking a provider and entering your key (written to `.env`), so you don't have to edit files by hand. A first-time tour is available any time under `/tutorial`.

The Pygame side highlights names, places, and items (hover one for a tooltip on who/where/what it is), tints new-area descriptions, streams text in as it's written, keeps a persistent status bar (HP, location, time, equipped gear) along the top, and tucks a collapsible command list in the corner. It ships with three themes — Dark (a low-contrast night palette), Light (warm paper), and Earthy (warm and muted) — switchable from `/theme` or `/settings`. `/journal` opens a "journey so far" — story, quests, people, places, and chronicle — and Esc pauses (Resume / Journal / Settings / Save & quit). Every so often a background thread quietly writes the recent turns up into a journal chapter, so the "story so far" reads like prose rather than a log, without ever blocking your turn.

 The file `tests/eval.py` serves as a regression harness with two suites. A free, no-API engine suite (`python -m tests.eval --engine-only`) checks the deterministic engine contract: time, inventory, item effects, buffs, quests, the NPC registry, the world-fact ledger, save/load, retrieval assembly, the situation classifier, playbook loading, and the journal round-trip. A live LLM suite (`python -m tests.eval`) checks the model contract — that it respects the schema and follows the basic game rules — plus a set of narrative-quality cases grounded in interactive-fiction craft (player agency, show-don't-tell sensory detail, consequence, continuity with established facts, staying in character, and pacing). Run it after changing the prompts to catch regressions.

The master system prompt in `system_prompt.md` gives strict restrictions on what the LLM can and cannot do. Its THE WORLD section commits to whatever setting you chose while holding the invariants that apply to any world (wholly fictional, internally consistent, with whatever gives an edge — magic, cyberware, a relic — always costing something). It also shapes how the model responds, keeping small actions short and saving the longer, descriptive writing for when you actually explore or take a place in, and it pushes back when you try to wish something into existence instead of just handing it to you. To keep that prompt short enough for a small model to actually follow, the per-turn craft guidance lives separately in `playbook.md`: each kind of moment (opening, arrival, a look around, dialogue, a fight, a quick action…) has its own "director's note" with examples, and a lightweight classifier picks the one that fits what you just did and injects only that snippet near the end of the prompt, where it gets the most attention. Given more powerful, creative models, this could be altered to go in many new directions and allow more freedom for the LLM to generate a more interesting, fleshed out game. 

- `game_ui.py` runs the Pygame version and keeps the UI flow together (the entry point).
- `main.py` is a retired stub that points you at `game_ui.py`.
- `system_prompt.md` is the static prompt that steers the model.
- `playbook.md` holds the per-beat "director's notes" injected each turn.
- `templates/<setting>/` has the reusable location and dialogue blueprints, grouped by setting (`fantasy` ships built in; add a folder to give another genre its own pack).
- `game/` is the core package:
  - `engine.py` owns the real game state and applies validated changes.
  - `combat.py` resolves the actual combat turns.
  - `logs.py` writes and loads the markdown logs, save file, and world records.
  - `game_logic.py` builds the LLM request (Structured Outputs), classifies the beat, and handles the local commands.
  - `schema.py` defines the Pydantic models the LLM response has to match.
  - `stats.py` tracks session stats and API usage for the UI version.
  - `config.py` reads the provider/model/theme settings from `.env`.
  - `ui.py` renders the CLI-style Pygame interface (themes, highlighting, tooltips, streaming).
- `tests/eval.py` checks the engine and model contracts after prompt changes.
- `logs/` stores saves, world notes, NPC history, and session logs.

## Notes

All the model and provider settings live in `.env` (copy `.env.example` to start), so you don't have to touch the source. The defaults are gpt-5.4-nano for narrative and gpt-4o-mini for summarization, set with `MODEL_NARRATIVE` and `MODEL_SUMMARY`. The UI theme defaults from `UI_THEME` (`dark` / `light` / `earthy`), and `LLM_REASONING_EFFORT` (default `low`) controls how much the reasoning model thinks before each turn.

To use a provider other than OpenAI, put that provider's key in `LLM_API_KEY` and point `LLM_BASE_URL` at any OpenAI-compatible endpoint. Google Gemini, OpenRouter, Anthropic's compatibility endpoint, and local servers like Ollama all work this way (the example URLs are in `.env.example`). For non-OpenAI models, set `LLM_REASONING_EFFORT` to empty so the OpenAI-only reasoning parameter isn't sent. Two caveats: everything talks to the OpenAI chat-completions API shape, so a provider just needs an OpenAI-compatible endpoint (the native Anthropic or Gemini SDKs aren't used); and Structured Outputs is an OpenAI feature, so a provider that doesn't implement it may reject the schema-constrained request. 