from app.utils.text import best_snippets, normalize_whitespace


def test_normalize_whitespace():
    assert normalize_whitespace("A   B\n C") == "A B C"


def test_best_snippets_prefers_matching_terms():
    chunks = ["fees are listed", "snow season is winter", "camping details"]
    picked = best_snippets("best season", chunks, limit=1)
    assert picked == ["snow season is winter"]
