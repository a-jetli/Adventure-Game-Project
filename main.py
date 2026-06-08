import os
import threading
from dotenv import load_dotenv
from openai import OpenAI
from schema import LLMResponse
from engine import EngineState, PlayerCharacter
from combat import run_combat
from logs import (
    init_logs,
    write_world_seed,
    process_response,
    save_session,
    save_game,
    load_game,
    load_region,
    load_npc,
)
from game_logic import handle_local_command, call_llm, summarize_context, load_system_prompt, generate_recap

load_dotenv()
MODEL_NARRATIVE = "gpt-5.4-nano"
MODEL_SUMMARY = "gpt-4o-mini"

def process_response_async(response: LLMResponse, state_snapshot: dict):
    thread = threading.Thread(target=process_response, args=(response, state_snapshot))
    thread.daemon = True
    thread.start()


def bootstrap_player() -> PlayerCharacter:
    print("Welcome.\n")
    name = input("Name: ").strip() or "Wanderer"
    background = (
        input("Background (leave blank to randomize): ").strip()
        or "unknown wanderer, generate something fitting the world"
    )
    tone = input("Preferred tone - grim / whimsical / neutral: ").strip() or "neutral"
    return PlayerCharacter(name=name, background=background, tone=tone)


def main():
    init_logs()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    system_prompt = load_system_prompt()

    existing_save = load_game()
    if existing_save:
        resume = input("Save file found. Resume? (y/n): ").strip().lower()
        if resume == "y":
            state, hot_context = existing_save
            print(f"\nWelcome back, {state.player.name}. Turn {state.session_turn}.\n")
            print(f"Location: {state.location}")
            print(f"HP: {state.hp}/{state.max_hp}")
            print(f"Inventory: {state._inventory_string()}\n")
            recap = generate_recap(client, state, hot_context, MODEL_SUMMARY)
            if recap:
                print(f"Previously...\n{recap}\n")
        else:
            state, hot_context = _new_game(client, system_prompt)
    else:
        state, hot_context = _new_game(client, system_prompt)

    while True:
        player_input = input("\n> ").strip()

        if player_input.lower() in ("quit", "exit"):
            import time
            time.sleep(0.5)
            save_session(hot_context, state)
            save_game(state, hot_context)
            print("Session saved. Goodbye.")
            break

        local = handle_local_command(player_input, state)
        if local:
            print(f"\n{local}")
            continue

        if len(hot_context) > 8:
            summary = summarize_context(client, hot_context, MODEL_SUMMARY)
            hot_context = [summary] + hot_context[3:]

        response = call_llm(
            client, system_prompt, state, hot_context[-5:], player_input, MODEL_NARRATIVE
        )
        state.apply_state_changes(response.state_changes)
        snapshot = {
            "session_turn": state.session_turn,
            "location": state.location,
            "time_label": state._time_label(),
        }
        process_response_async(response, snapshot)

        print(f"\n{response.narrative}")

        if response.state_changes.combat_triggered:
            combat_result = run_combat(state, response.state_changes.encounter)

            if combat_result["result"] == "defeat":
                print("Game over.")
                save_session(hot_context, state)
                break

            # log the combat outcome for narrative context
            hot_context.append(
                f"[Combat] {', '.join(combat_result['log'])}"
            )

        hot_context.append(
            f"[Turn {state.session_turn}] Player: {player_input} | {response.narrative}"
        )
        
def _new_game(client: OpenAI, system_prompt: str) -> tuple[EngineState, list[str]]:
    player = bootstrap_player()
    state = EngineState(player=player)
    hot_context: list[str] = []

    print("\nGenerating world...\n")

    seed_response = call_llm(
        client,
        system_prompt,
        state,
        [],
        "Begin. Generate the opening scene following THE OPENING SCENE guidance: "
        "four to six paragraphs that establish where the player physically stands, "
        "the time of day, the weather, the sounds and smells, and the life around "
        "them. Do not reference the player's past — this is the very first moment. "
        "Ground them in a specific, named place and set location with location_is_new "
        "true. Plant exactly one concrete hook they could choose to pursue — a rumor, "
        "a visible landmark with implied history, a distant event they can see or hear, "
        "or a clear sign something happened here recently — without telling them to "
        "pursue it and without creating a quest. End on a detail, not a question.",
        MODEL_NARRATIVE,
    )
    state.apply_state_changes(seed_response.state_changes)
    write_world_seed(seed_response.narrative, state)
    snapshot = {
        "session_turn": state.session_turn,
        "location": state.location,
        "time_label": state._time_label(),
    }
    process_response_async(seed_response, snapshot)
    print(seed_response.narrative)
    hot_context.append(f"[Scene]: {seed_response.narrative}")

    return state, hot_context


if __name__ == "__main__":
    main()