"""
Quote management for StudyCompanion add-on.
Handles loading quotes from local file and selecting unique quotes.
"""

import os
import random


_quotes_cache: list[str] | None = None


def _load_quotes_from_local() -> list[str]:
    """Load quotes from quotes.txt in the add-on folder (one per line)."""
    try:
        base = os.path.dirname(__file__)
        path = os.path.join(base, "quotes.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw_lines = [l.rstrip("\n") for l in f.readlines()]

            quotes: list[str] = []
            for raw in raw_lines:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue

                # Accept either plain text lines or legacy python-list style
                # entries like: "Quote text",
                if line.endswith(","):
                    line = line[:-1].rstrip()
                if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
                    line = line[1:-1]

                # User requested removal of parentheses.
                line = line.replace("(", "").replace(")", "")
                line = line.strip()
                if line:
                    quotes.append(line)

            return quotes
    except Exception:
        pass
    return []


def _save_quotes_to_local(quotes: list[str]) -> None:
    """Save quotes to quotes.txt (one per line)."""
    try:
        base = os.path.dirname(__file__)
        path = os.path.join(base, "quotes.txt")
        with open(path, "w", encoding="utf-8") as f:
            for q in quotes:
                if q is not None:
                    f.write(str(q).strip() + "\n")
    except Exception:
        pass


def get_random_quote() -> str:
    """Return one random motivational quote, using the local file."""
    global _quotes_cache
    if _quotes_cache is None:
        _quotes_cache = _load_quotes_from_local()

    if not _quotes_cache:
        return "Keep going — you've got this!"
    return random.choice(_quotes_cache)


def get_unique_random_quotes(count: int) -> list[str]:
    """Return a list of unique random quotes. If count exceeds available quotes, recycle with shuffle."""
    global _quotes_cache
    if _quotes_cache is None:
        get_random_quote()  # Initialize cache (and ensure file is populated)

    if not _quotes_cache:
        return ["Keep going — you've got this!"] * count

    if count <= len(_quotes_cache):
        return random.sample(_quotes_cache, count)
    else:
        # If we need more quotes than available, repeat with shuffle
        result = _quotes_cache[:]
        while len(result) < count:
            remaining = count - len(result)
            additional = random.sample(_quotes_cache, min(remaining, len(_quotes_cache)))
            result.extend(additional)
        return result


def get_all_quotes() -> list[str]:
    """Return all quotes from the quotes.txt file."""
    return _load_quotes_from_local()


def save_quotes(quotes: list[str]) -> None:
    """Persist the provided list of quotes into quotes.txt and update cache."""
    global _quotes_cache
    try:
        _save_quotes_to_local(quotes)
        _quotes_cache = list(quotes)
    except Exception:
        pass


 
