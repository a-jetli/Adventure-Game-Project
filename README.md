# Text based adventure game project

I wrote this as a simple text based RPG in Python. It uses an OpenAI model to generate the world, scenes, and decide when to enter combat, and it saves progress under `logs/`. The initial idea was to make a playable book adventure where you can start in a fantasy world with an LLM serving as a sort of "dungeon master", where you can do pretty much anything you want afterwards. The way I thought to implement this was building a system where the LLM doesn't own the entire game state directly, but still manages narrative freedom.

## What I used

- Python
- OpenAI API
- `pygame` for the UI version

## How to run it

1. You'll need to provide your own API key (I used openAI) and define it under the model variable fields.
2. Install the Python dependencies `Pygame`, `Pydantic` and `python-dotenv`, as well as `openai` (or the dependencies for your model of choice):
```bash 
pip install pygame pydantic python-dotenv openai
```
3. Add your API key to a `.env` file in the project root
4. Run the following command (May be slightly different depending on platforms and Python version):

```bash
python game_ui.py
```


## How it works

I split the project up so the model never gets to own the whole game by itself. `engine.py` keeps the current master state for the player, inventory, time, location, and relationships. After each turn, the game only applies changes that come back through the Pydantic schema in `schema.py`, so the LLM has to stay inside a typed contract instead of inventing state directly.

`game_ui.py` is where the LLM request gets built. It sends the current engine state, recent hot context, and relevant cold context. It also handles the simple local commands like inventory, health, time, location, equip, use, quests, and help before the request ever reaches the model. You can type `inventory` or `health` at any point to get the information instantly and locally, or `quests` to pull up your journal.

The game uses a two layer memory setup. The hot context is the recent turn history sitting in memory, and it gets trimmed with a short summary once it gets too long. The cold storage lives under `logs/`, where markdown files for the world, regions, NPCs, and individual events are kept. `logs.py` writes those files and loads them back on demand so the game can remember old places and people without stuffing everything into the prompt every turn.

The "story" loop lives in `main.py` for the terminal version and `game_ui.py` for the Pygame version. Both of them do the same basic thing: load the save, ask for player input, send that input into the model, apply the returned state changes, write logs, and keep the session moving forward.

Combat is simple: attack, use item, or flee. The model can trigger a fight by returning a combat encounter, but the damage rolls and HP changes happen locally. Buffs from items carry into the fight and wear off after a few rounds.

The model can also start quests when you commit to something, like agreeing to find a missing brother, and you can pull them up anytime with the quest log. Items do things now too: healing and combat buffs get applied by the engine, while stranger one off items get narrated by the model when you use them. When you load a save it gives you a quick recap of where you left off so you are not stuck trying to remember everything. The Pygame side also highlights names, places, and items as they come up, tints the descriptions of new areas, and keeps a collapsible list of commands tucked in the corner.

 The file `eval.py` serves as a regression harness for the LLM contract. If you change the system prompt, you can run those checks against a set of sample inputs and make sure the model still returns valid JSON, respects the schema, and follows the basic game rules.

The master system prompt in `system_prompt.md` gives strict restrictions on what the LLM can and cannot do. It also shapes how the model responds, keeping small actions short and saving the longer, descriptive writing for when you actually explore or take a place in, and it pushes back when you try to wish something into existence instead of just handing it to you. Given more powerful, creative models, this could be altered to go in many new directions and allow more freedom for the LLM to generate a more interesting, fleshed out game. 

- `main.py` runs the terminal version of the game loop.
- `game_ui.py` runs the Pygame version and keeps the UI flow together.
- `engine.py` owns the real game state and applies validated changes.
- `combat.py` resolves the actual combat turns.
- `logs.py` writes and loads the markdown logs, save file, and world records.
- `schema.py` defines the Pydantic models the LLM response has to match.
- `stats.py` tracks session stats and API usage for the UI version.
- `ui.py` renders the CLI-style Pygame interface.
- `eval.py` checks the model contract after prompt changes.
- `system_prompt.md` is the prompt that steers the model.
- `logs/` stores saves, world notes, NPC history, and session logs.

## Notes

The default models are gpt-5.4-nano for narrative and gpt-4o-mini for summarization. 
However, you can swap the `MODEL_NARRATIVE` and `MODEL_SUMMARY` fields in `game_ui.py` to use any OpenAI compatible model. 