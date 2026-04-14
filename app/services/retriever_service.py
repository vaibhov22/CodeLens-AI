from app.db.vector_store import collection
from app.core.model_loader import model

VALID_TYPES = ["function", "method", "global", "class"]

# Words that carry no retrieval signal — skip them in keyword matching
_STOPWORDS = {
    "the", "a", "an", "is", "in", "on", "at", "to", "of", "and",
    "or", "for", "what", "how", "does", "do", "where", "which",
    "this", "that", "with", "from", "are", "be", "it", "its",
}

# Query intent buckets — each maps to (query_keywords, code_keywords, boost)
_INTENT_RULES = [
    {
        "label": "model_loading",
        "query_triggers": ["load", "model", "import model", "pickle", "joblib"],
        "code_signals":   ["pickle.load", "joblib.load", "model =", "load(", "open("],
        "boost": 6,
    },
    {
        "label": "empty_guard",
        "query_triggers": ["empty", "no data", "nothing", "null", "none", "missing", "if len"],
        "code_signals":   ["len(", "== 0", "if not ", "return", "is none", "is empty"],
        "boost": 5,
    },
    {
        "label": "analytics",
        "query_triggers": [
            "distraction", "attention", "blink", "fatigue",
            "session", "report", "duration", "analytics",
        ],
        "code_signals": [
            "df[", "mean()", "plt.", "logger",
            "session_duration", "distraction_percentage",
        ],
        "boost": 4,
    },
    {
        "label": "input_validation",
        "query_triggers": ["input", "validate", "validation", "form", "user input"],
        "code_signals":   ["request.form", "try", "except", "validate", "raise"],
        "boost": 4,
    },
    {
        "label": "type_conversion",
        "query_triggers": ["float", "int", "convert", "cast", "type error", "value error"],
        "code_signals":   ["float(", "int(", "str("],
        "boost": 3,
    },
    {
        "label": "prediction",
        "query_triggers": ["predict", "inference", "output", "result", "classify"],
        "code_signals":   ["predict(", "model.predict", "return prediction", "output"],
        "boost": 4,
    },
]


def _query_intent(q: str) -> list[dict]:
    """Return which intent rules are active for this query."""
    active = []
    for rule in _INTENT_RULES:
        if any(trigger in q for trigger in rule["query_triggers"]):
            active.append(rule)
    return active


def _meaningful_words(query: str) -> list[str]:
    """Extract non-stopword tokens from a query for keyword matching."""
    return [w for w in query.lower().split() if w not in _STOPWORDS and len(w) > 2]


def rerank(results, query):
    docs  = results["documents"][0]
    metas = results["metadatas"][0]

    q             = query.lower()
    active_rules  = _query_intent(q)
    keywords      = _meaningful_words(query)

    scored = []

    for doc, meta in zip(docs, metas):
        # Skip file-level stubs — they carry no code signal
        if meta.get("type") == "file":
            continue

        score   = 0
        lowered = doc.lower()

        # ── 1. Structural validity boost (always safe, small) ──────────────
        if meta.get("type") in VALID_TYPES:
            score += 1

        # ── 2. Query-aware intent boosts (ONLY fires when query matches) ───
        for rule in active_rules:
            if any(sig in lowered for sig in rule["code_signals"]):
                score += rule["boost"]

        # ── 3. Keyword relevance (meaningful words only) ───────────────────
        matched_keywords = sum(1 for kw in keywords if kw in lowered)
        # Reward multiple distinct keyword hits, not just any single hit
        if matched_keywords >= 2:
            score += 3
        elif matched_keywords == 1:
            score += 1

        # ── 4. Named entity match (function/class name in query) ───────────
        chunk_name = meta.get("name", "").lower()
        if chunk_name and chunk_name in q:
            score += 4

        # ── 5. Mild penalty for generic global chunks unrelated to query ───
        if meta.get("type") == "global":
            has_loading = any(
                k in lowered for k in ["load", "pickle", "joblib", "model ="]
            )
            is_loading_query = any(
                r["label"] == "model_loading" for r in active_rules
            )
            if not has_loading and not is_loading_query:
                score -= 1

        scored.append((score, doc, meta))

    if not scored:
        return results

    scored.sort(reverse=True, key=lambda x: x[0])

    # ── Diversity filter: cap contributions per file ───────────────────────
    top_k        = 5
    file_counts  = {}
    selected     = []

    for score, doc, meta in scored:
        file_key = meta.get("file", "unknown")
        if file_counts.get(file_key, 0) >= 2:          # max 2 chunks per file
            continue
        selected.append((score, doc, meta))
        file_counts[file_key] = file_counts.get(file_key, 0) + 1
        if len(selected) >= top_k:
            break

    # Fill remaining slots if diversity filter left gaps
    if len(selected) < top_k:
        for item in scored:
            if item not in selected:
                selected.append(item)
            if len(selected) >= top_k:
                break

    # ── Conditional global injection (only for model-loading queries) ──────
    is_loading_query = any(r["label"] == "model_loading" for r in active_rules)
    if is_loading_query:
        has_global = any(m.get("type") == "global" for _, _, m in selected)
        if not has_global:
            for item in scored:
                if item[2].get("type") == "global":
                    selected[-1] = item
                    break

    results["documents"][0] = [x[1] for x in selected]
    results["metadatas"][0] = [x[2] for x in selected]

    return results


def search_code(query, repo_path):
    # Unchanged — same signature and return shape as before
    repo_path = repo_path.replace("\\", "/")

    query_embedding = model.encode([query])[0].tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=15,
        where={"repo": repo_path}
    )

    results = rerank(results, query)

    warnings = detect_patterns(results["documents"][0], query)

    return {
        "results": results,
        "warnings": warnings
    }


def detect_patterns(docs, query):
    # Unchanged — same signature and return shape as before
    text = " ".join(docs)
    q    = query.lower()

    warnings = []

    if "order" in q and "request.form.values()" in text:
        warnings.append("Feature order risk detected")

    if any(x in q for x in ["input", "float", "error", "crash"]) \
            and "float(" in text and "try" not in text:
        warnings.append("No input validation detected")

    return warnings