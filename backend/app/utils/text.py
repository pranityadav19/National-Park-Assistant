import re


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def best_snippets(question: str, chunks: list[str], limit: int = 3) -> list[str]:
    terms = {t.lower() for t in re.findall(r"[a-zA-Z]{3,}", question)}
    scored: list[tuple[int, str]] = []
    for chunk in chunks:
        lower = chunk.lower()
        score = sum(1 for t in terms if t in lower)
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for s, c in scored if s > 0][:limit] or chunks[:limit]
