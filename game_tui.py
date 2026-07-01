"""Textual entry point for The Game (terminal UI).

The parallel of the retired legacy/game_ui.py (pygame), reusing the same
toolkit-agnostic driver (game/driver.py). The app starts the driver on a worker
thread itself, so this is
just: build the app with the configured theme and run it.

Run:  python3 game_tui.py
"""

import os

from game import config

# High-refresh support: Textual throttles screen repaints to TEXTUAL_FPS (default 60,
# read once at import time in textual.constants → screen.UPDATE_PERIOD = 1/MAX_FPS).
# So we MUST set the env var before importing anything that pulls in Textual. Opt-in
# via UI_MAX_FPS so a capable setup (120Hz panel + fast terminal) gets smoother motion
# while slow terminals / SSH stay at the safe default. `setdefault` lets an explicit
# TEXTUAL_FPS in the environment still win.
if config.UI_MAX_FPS:
    os.environ.setdefault("TEXTUAL_FPS", str(config.UI_MAX_FPS))

from game.tui import GameApp  # noqa: E402  (must follow the TEXTUAL_FPS setup above)


def main():
    GameApp(theme_name=config.UI_THEME).run()


if __name__ == "__main__":
    main()
