"""Retired entry point.

The terminal version of the game has been retired to avoid maintaining two UIs.
Play the game with the Pygame client instead:

    python game_ui.py

The reusable engine still lives in the `game/` package; only this terminal loop
is gone.
"""

import sys


def main():
    print(__doc__.strip())
    sys.exit(0)


if __name__ == "__main__":
    main()
