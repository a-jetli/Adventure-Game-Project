# Text based adventure game

A text based RPG where an LLM plays the role of narrator. You decide your characters name, the setting, the genre (Fantasy? Cyberpunk? Pirate ships?) and the model takes over the rest. The model writes the world, the scenes, and the characters, and decides when a fight breaks out. There is no set script, you have complete narrative freedom and the model will build the world around your decisions and remembers places and decisions you make along the way.

> **Work in progress.** This is a personal project I'm still working on. Currently, the default LLM model call is to GPT 5.4-nano to preserve low costs and allow me to test runs quickly. Upgrading the model to 5.4-mini or higher noticeably improved narrative quality but comes at a higher cost and potentially higher latency. Changing the model is an easy swap so you can bring your own model.

## Requirements

- Python 3.9 or newer (developed on 3.12)
- An API key from OpenAI (or another OpenAI compatible provider)
- Four Python packages, all installed by the command below:
  - `textual` runs the terminal UI
  - `pydantic` defines and validates the game state
  - `python-dotenv` reads your `.env` settings
  - `openai` talks to the model (any OpenAI compatible endpoint uses it

## Run it

```bash
git clone https://github.com/a-jetli/Adventure-Game-Project.git
cd Adventure-Game-Project
pip install -r requirements.txt
python3 game_tui.py
```

It runs in your terminal. On the first launch it asks you to pick a provider and paste your API key, then saves that to a local `.env` for next time. You can also configure this in the source code.

## Choosing a model

The key and model live in a `.env` file (the first run creates it, or copy `.env.example`). The default is `gpt-5.4-nano`, which is cheap and fast. For noticeably better writing, set `MODEL_NARRATIVE=gpt-5.4-mini` instead. To use another provider, set `LLM_API_KEY` and point `LLM_BASE_URL` at its endpoint (examples for Gemini, OpenRouter, Anthropic, and Ollama are in `.env.example`).

## How it works

### The game owns the state, the model tells the story

The model never edits the game state directly. Each turn it returns a structured form describing what changed (location, HP, inventory, the people in the scene, world events, quests), and the engine validates and applies those changes itself. The model's API enforces the return format. This keeps the storytelling free while the game stays the authority on what is true, which is what stops the model from teleporting the player or hallucinating background up.

### How the model is steered

The model works from two layers of instruction, both plain text under `prompts/` and free to edit. A master system prompt holds the always-on rules: who the model is, what it may and may not do, how to keep to the player's chosen tone, and how to fill in the state form. Separately the game keeps a set of short directing notes, one per kind of moment (arriving somewhere, looking around, talking, fighting, a quick action). Before each turn it works out which kind of moment the player's input is and slips only the matching note in near the end of the prompt, where the model pays it the most attention. That keeps the standing rules short while still giving pointed guidance for whatever is happening right now. Reusable place and character templates under `templates/` work the same way, added only when they fit the scene.

### Memory

Context is handled in three stages. The most recent turns are kept word for word. As they pile up, the oldest are handed to a cheaper model that folds them into a running "story so far" summary in the background, so nothing important is lost when they drop out of view. Everything beyond that (places, characters, world events) is written out to files and pulled back into the prompt only when it matters to the moment. On top of those three, a lightweight lookup surfaces past notes that match what the player just referenced, so a detail from dozens of turns ago can resurface instead of being quietly contradicted.

### A turn, and the commands

A turn runs through one loop: read input, check for a local command, otherwise send the situation to the model, apply the changes that come back, save, and repeat. Local commands all begin with a slash and are answered instantly with no API call, so ordinary prose like "I check my pack" is never mistaken for one. They cover quick read outs (/inventory, /hp, /map, /quests, /people, /recap, and more) plus actions like /equip and /use.

### Combat

Combat is resolved in code: attack, use an item, or flee, with the dice rolled by the engine and buffs and item effects applied locally. The model only narrates how a fight opens and how it settles. A defeat is not the end of the game; the player comes to wounded or robbed and the story carries on from the setback. It's really simple for now, but its a priority area to expand in the future.

### A world that keeps moving

Several systems run in the background without holding up a turn. Narration streams onto the screen as it is generated. A journal is written in the character's own voice and can be exported as a Markdown book. And an offscreen "world director" nudges existing threads along between scenes, so a wronged character may act on the grudge or a brewing tension may escalate while the player is somewhere else.

### Any setting

The world's genre is chosen at character creation. The engine itself is indifferent to genre (a stimpack and a healing potion resolve to the same effect), so the setting mostly steers the prose and which templates apply.

### The terminal interface

The front end is built with Textual and runs in the terminal or terminal replacement app of your choice. Narration types out as it arrives and any key fast forwards it, names and places and items are picked out in colour, and a status bar across the top tracks HP, location, time of day, and gear. A sidebar of collapsible cards shows the current place and time, a list of people, places, and items to inspect, and the active quests. Menus and the combat screen appear as pop up dialogs driven by the keyboard or mouse, and three colour themes ship (Dark, Light, Earthy), switchable while playing.

## Saves and logs

The game keeps everything under a `logs/` folder it creates, mostly plain Markdown files that can be opened and read. Save slots live in `logs/saves/`, exported books in `logs/books/`, and the world's places, people, and events fill the rest. It autosaves every turn.

## Tests

`python -m tests.eval --engine-only` is free and checks the game logic. `python -m tests.eval` also runs live checks against the model, handy after editing the prompts.


