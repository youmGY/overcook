"""Leaderboard persistence for singleplay scores."""

import json
import os
import datetime

_LEADERBOARD_PATH = "./overcook_leaderboard.json"
MAX_ENTRIES = 10


def load_leaderboard() -> list:
    """Load leaderboard from disk. Returns list of dicts with name/score/date."""
    try:
        with open(_LEADERBOARD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_score(name: str, score: int) -> list:
    """Add a score entry, keep top MAX_ENTRIES by score. Returns updated leaderboard."""
    board = load_leaderboard()
    board.append({
        "name": name if name else "---",
        "score": score,
        "date": datetime.date.today().isoformat(),
    })
    board.sort(key=lambda x: x.get("score", 0), reverse=True)
    board = board[:MAX_ENTRIES]
    try:
        with open(_LEADERBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump(board, f, ensure_ascii=False)
    except Exception:
        pass
    return board
