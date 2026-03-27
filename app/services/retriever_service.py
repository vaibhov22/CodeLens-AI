from app.db.vector_store import collection
from app.core.model_loader import model

VALID_TYPES = ["function", "method", "global", "class"]

def rerank(results, query):

    docs = results["documents"][0]
    metas = results["metadatas"][0]

    query_words = query.lower().split()
    q = query.lower()

    scored = []

    for doc, meta in zip(docs, metas):

        if meta.get("type") == "file":
            continue

        score = 0
        lowered = doc.lower()

        # ✅ keep globals but slight penalty if weak
        if meta.get("type") == "global" and not any(k in lowered for k in ["load", "pickle", "joblib", "model ="]):
            score -= 1

        # 🔥 strong boost for model loading queries
        if any(x in q for x in ["load", "model"]):
            if any(k in lowered for k in ["pickle.load", "joblib.load", "model =", "load("]):
                score += 6

        # 🔥 type conversion risk
        if any(x in lowered for x in ["float(", "int(", "str("]):
            score += 3

        if "request.form" in lowered:
            score += 3

        # ✅ keyword relevance
        if any(word in lowered for word in query_words):
            score += 2

        # ✅ structure boost
        if meta.get("type") in VALID_TYPES:
            score += 1

        # ✅ reduce predict dominance
        if "predict" in meta.get("name", "").lower():
            score += 1

        # ✅ NEW: boost for empty/guard clause queries
        if any(x in q for x in ["empty", "no data", "nothing", "if len", "null", "none", "missing"]):
            if any(k in lowered for k in ["len(", "== 0", "if not", "return", "is none", "is empty"]):
                score += 5

        # ✅ NEW: boost for analytics/helper file queries
        if any(x in q for x in ["distraction", "attention", "blink", "fatigue", "session", "report", "duration"]):
            if any(k in lowered for k in ["df[", "mean()", "plt.", "logger", "session_duration", "distraction_percentage"]):
                score += 4

        scored.append((score, doc, meta))

    if not scored:
        return results

    scored.sort(reverse=True, key=lambda x: x[0])

    # ✅ slightly larger context
    top_k = 5
    selected = scored[:top_k]

    # ✅ ensure at least one global chunk (important for loading)
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

    text = " ".join(docs)
    q = query.lower()

    warnings = []

    # ✅ only show if relevant to query
    if "order" in q and "request.form.values()" in text:
        warnings.append("Feature order risk detected")

    if any(x in q for x in ["input", "float", "error", "crash"]) and "float(" in text and "try" not in text:
        warnings.append("No input validation detected")

    return warnings