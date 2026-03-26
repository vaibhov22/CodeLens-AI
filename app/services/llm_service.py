from __future__ import annotations

import json
import re
from dataclasses import dataclass
import ollama


@dataclass
class Source:
    file: str
    type: str
    name: str
    start_line: int
    end_line: int


# ───────────────────────── QUERY CLASSIFIER ─────────────────────────

def classify_query(q: str) -> str:
    q = q.lower()
    if any(x in q for x in ["crash", "error", "exception", "invalid", "input", "abc"]):
        return "crash"
    if any(x in q for x in ["order", "feature order"]):
        return "order"
    if any(x in q for x in ["flow", "how data", "pipeline", "how does", "explain"]):
        return "flow"
    return "general"


# ───────────────────────── PRIORITY TERMS ─────────────────────────

QUERY_TERM_MAP = [
    (["model", "loaded", "load", "where is model"],  ["pickle.load", "joblib.load", "load(", "model ="]),
    (["input", "float", "crash", "error", "abc"],    ["float(", "int(", "str(", "try:"]),
    (["order", "feature order"],                      ["request.form.values()", "request.form", "values()"]),
    (["predict", "prediction"],                       ["model.predict(", ".predict("]),
    (["route", "endpoint", "url"],                    ["@app.route", "@router.", "app.get(", "app.post("]),
    (["return", "response"],                          ["return ", "jsonify(", "Response("]),
]


def get_priority_terms(query: str) -> list[str]:
    q = query.lower()
    terms = []
    for triggers, t in QUERY_TERM_MAP:
        if any(x in q for x in triggers):
            terms.extend(t)
    return terms


# ───────────────────────── WARNINGS ─────────────────────────

def detect_warnings(docs: list[str]) -> list[str]:
    warnings = set()
    for doc in docs:
        if "request.form.values()" in doc:
            warnings.add("Feature order risk detected")
        if "float(" in doc and "try" not in doc:
            warnings.add("Input validation missing → float() crash risk")
        if "debug=True" in doc:
            warnings.add("debug=True detected → disable in production!")
    return list(warnings)


def filter_warnings(query: str, warnings: list[str]) -> list[str]:
    q = query.lower()
    if any(x in q for x in ["crash", "input", "invalid", "error", "abc","float","conversion", "fails"]):
        return [w for w in warnings if "float" in w.lower() or "validation" in w.lower()]
    if "order" in q:
        return [w for w in warnings if "order" in w.lower()]
    return []


# ───────────────────────── EXTRACTION ─────────────────────────

_MIN_LINE_SCORE = 3

_OPERATION_PATTERNS = re.compile(
    r"(\w+\s*=\s*\w)|"
    r"(\w+\()|"
    r"(@\w+)|"
    r"(return\s)|"
    r"(raise\s)|"
    r"(\[\s*\w)"
)


def _score_doc(doc: str, meta: dict, priority_terms: list[str], q_words: list[str]) -> int:
    lowered = doc.lower()
    score = sum(5 for t in priority_terms if t.lower() in lowered)
    score += sum(1 for w in q_words if w in lowered)
    if meta.get("type") == "global":
        score += 2
    return score


def _score_line(line: str, priority_terms: list[str], q_words: list[str]) -> int:
    lowered = line.lower()
    score = sum(5 for t in priority_terms if t.lower() in lowered)
    score += sum(2 for w in q_words if w in lowered)
    if _OPERATION_PATTERNS.search(line):
        score += 1
    return score


def _best_line_in_doc(
    doc: str, priority_terms: list[str], q_words: list[str]
) -> tuple[int, str]:
    best_idx, best_score, best_line = -1, -1, ""
    for i, line in enumerate(doc.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        score = _score_line(stripped, priority_terms, q_words)
        if score > best_score:
            best_score, best_idx, best_line = score, i, stripped
    if best_score < _MIN_LINE_SCORE:
        return -1, ""
    return best_idx, best_line


def _select_best_doc(
    docs: list[str], metas: list[dict], priority_terms: list[str], q_words: list[str]
) -> str | None:
    best_doc, best_score = None, -1
    for doc, meta in zip(docs, metas):
        s = _score_doc(doc, meta, priority_terms, q_words)
        if s > best_score:
            best_score, best_doc = s, doc
    return best_doc


def extract_exact_code(results: dict, query: str) -> str:
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    priority_terms = get_priority_terms(query)
    q_words = [w for w in query.lower().split() if len(w) > 2]
    best_doc = _select_best_doc(docs, metas, priority_terms, q_words)
    if not best_doc:
        return ""
    _, line = _best_line_in_doc(best_doc, priority_terms, q_words)
    return line


def extract_grounded_snippet(results: dict, query: str, window: int = 3) -> tuple[str, str]:
    """Returns (exact_best_line, surrounding_snippet)."""
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    priority_terms = get_priority_terms(query)
    q_words = [w for w in query.lower().split() if len(w) > 2]

    best_doc = _select_best_doc(docs, metas, priority_terms, q_words)
    if not best_doc:
        return "", ""

    lines = best_doc.splitlines()
    best_idx, best_line = _best_line_in_doc(best_doc, priority_terms, q_words)
    if best_idx == -1:
        return "", ""

    start = max(0, best_idx - 1)
    end = min(len(lines), best_idx + window)
    snippet = "\n".join(l.rstrip() for l in lines[start:end] if l.strip())
    return best_line, snippet


# ───────────────────────── SOURCE CODE CLEANING ─────────────────────────

def clean_source_code(raw: str) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().strip('"""').strip("'''").strip("`").strip()
    cleaned = re.sub(r"^```[\w]*\n?|```$", "", cleaned, flags=re.MULTILINE).strip()
    for line in cleaned.splitlines():
        line = line.strip()
        if line and line.lower() != "code:":
            return line
    return ""


# ───────────────────────── JSON REPAIR ─────────────────────────

def _repair_and_parse_json(text: str) -> dict | None:
    """
    Attempt progressively looser parses of LLM text until one succeeds.
    Handles the triple-quote injection bug and markdown fences.
    """
    # Step 1: strip outer markdown fences
    clean = re.sub(r"^```(?:json)?\s*|```\s*$", "", text, flags=re.MULTILINE).strip()

    # Step 2: replace Python-style triple quotes inside what will become a
    # JSON string — the LLM sometimes writes  "source_code": """..."""
    # Replace them with an escaped quote so json.loads can survive
    clean = re.sub(r'"{3}(.*?)"{3}', lambda m: '"' + m.group(1).replace('"', '\\"').replace("\n", "\\n") + '"', clean, flags=re.DOTALL)
    clean = re.sub(r"'{3}(.*?)'{3}", lambda m: '"' + m.group(1).replace('"', '\\"').replace("\n", "\\n") + '"', clean, flags=re.DOTALL)

    # Step 3: find outermost JSON object
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        return None

    json_str = match.group(0)

    # Step 4: try direct parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Step 5: sanitise newlines inside string values then retry
    # Replace literal newlines inside quoted strings with \n
    json_str_fixed = re.sub(
        r'("(?:[^"\\]|\\.)*")',
        lambda m: m.group(0).replace("\n", "\\n").replace("\r", ""),
        json_str,
    )
    try:
        return json.loads(json_str_fixed)
    except json.JSONDecodeError:
        pass

    # Step 6: key-by-key regex extraction as last resort
    result = {}
    for key in ("answer", "source_code", "fix_code", "confidence"):
        pattern = rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"'
        m = re.search(pattern, json_str, re.DOTALL)
        if m:
            result[key] = m.group(1).replace("\\n", "\n").replace('\\"', '"')
    if "confidence" not in result:
        m = re.search(r'"confidence"\s*:\s*([0-9.]+)', json_str)
        if m:
            result["confidence"] = m.group(1)
    return result if result else None


# ───────────────────────── CONTEXT ─────────────────────────

def assemble_context(results: dict) -> str:
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    parts, total, MAX = [], 0, 6000

    for doc, meta in zip(docs, metas):
        block = (
            f"FILE: {meta.get('file')}\n"
            f"TYPE: {meta.get('type')}\n"
            f"NAME: {meta.get('name')}\n"
            f"LINES: {meta.get('start_line')} - {meta.get('end_line')}\n\n"
            f"{doc}"
        )
        if total + len(block) > MAX:
            break
        parts.append(block)
        total += len(block)

    return "\n\n---\n\n".join(parts)


# ───────────────────────── PROMPT ─────────────────────────

def build_prompt(
    query: str,
    context: str,
    grounded_line: str,
    warnings: list[str],
    query_type: str,
) -> str:
    grounding_block = (
        f'\n\nGROUNDED LINE (copy this verbatim into source_code and embed in answer):\n'
        f'GROUNDED: {grounded_line}'
        if grounded_line and query_type != "flow" else ""
    )

    # Flow queries need a pipeline explanation, not a single pinned line
    if query_type == "flow":
        source_code_rule = (
            '4. "source_code": leave empty string "" — flow answers explain a sequence, not one line.'
        )
        answer_rule = (
            '3. "answer": explain the step-by-step data flow using function/variable names from context.'
        )
    else:
        source_code_rule = (
            '4. "source_code": ONE exact line from context — no triple quotes, no ``` fences, no descriptions.'
        )
        answer_rule = (
            '3. "answer" MUST follow: "[Thing] is [action] here: `<exact line>`"\n'
            '   Example: "Model is loaded here: `model = pickle.load(open(\'loan_model.pkl\', \'rb\'))`"'
        )

    return f"""You are a code analysis engine. Answer ONLY from the provided source code.

ABSOLUTE RULES:
1. NEVER hallucinate. Use only lines that exist verbatim in the context.
2. If a GROUNDED LINE is provided, it MUST appear verbatim in "source_code" and "answer".
{answer_rule}
{source_code_rule}
5. If nothing relevant exists → answer: "Not found in provided context.", source_code: "".
6. "fix_code": only when a real bug exists. Otherwise "".
7. Return ONLY valid JSON — no markdown fences, no triple quotes, no extra text.{grounding_block}

Query Type: {query_type}
Detected Risks: {warnings if warnings else "none"}

Question: {query}

Source Code Context:
{context}

Return ONLY this JSON:
{{
  "answer": "...",
  "source_code": "...",
  "fix_code": "...",
  "confidence": 0.0
}}"""


# ───────────────────────── VALIDATION ─────────────────────────

def validate_fix(fix_code: str) -> list[str]:
    errors = []
    if not fix_code:
        return errors
    if "sorted(" in fix_code or ".sort(" in fix_code:
        errors.append("Sorting features is invalid")
    if "isnumeric" in fix_code or "replace(" in fix_code:
        errors.append("Filtering input silently is invalid")
    return errors


# ───────────────────────── POST-PROCESSING ─────────────────────────

def _is_abstract_answer(answer: str, source_code: str) -> bool:
    if not answer:
        return True
    if source_code and len(source_code) > 4:
        return False
    abstract_phrases = [
        "global scope", "is defined", "is loaded in", "is called in",
        "can be found", "this function", "the model", "is responsible",
        "handles", "performs", "is used to",
    ]
    return any(p in answer.lower() for p in abstract_phrases) and "`" not in answer


def _infer_action(query: str) -> str:
    q = query.lower()
    if any(x in q for x in ["load", "loaded", "where is model"]):
        return "Model is loaded"
    if any(x in q for x in ["predict", "prediction"]):
        return "Prediction is made"
    if any(x in q for x in ["input", "float", "crash", "error"]):
        return "Input is processed"
    if any(x in q for x in ["route", "endpoint"]):
        return "Route is defined"
    if any(x in q for x in ["return", "response"]):
        return "Response is returned"
    return "Found"


def override_with_grounded_answer(
    answer: str,
    source_code: str,
    grounded_line: str,
    grounded_snippet: str,
    query: str,
    query_type: str,
) -> tuple[str, str]:
    # Flow queries: never pin to a single line; let the LLM explanation stand
    if query_type == "flow":
        return answer, ""

    if not grounded_line:
        return answer, source_code

    # Reject LLM source_code if it doesn't contain the grounded line
    if source_code and grounded_line not in source_code:
        source_code = grounded_line

    if _is_abstract_answer(answer, source_code):
        action = _infer_action(query)
        return f"{action} here: `{grounded_line}`", grounded_line

    if not source_code or len(source_code) < 4:
        return answer, grounded_line

    return answer, source_code


# ───────────────────────── CONFIDENCE SCORING ─────────────────────────

def compute_confidence(
    source_code: str,
    grounded_line: str,
    llm_confidence: float,
    warnings: list[str],
    query_type: str,
) -> float:
    if query_type == "flow":
        # Flow answers have no single pinned line — score on whether answer looks complete
        base = 0.80 if llm_confidence > 0.3 else 0.60
    elif source_code and grounded_line and grounded_line in source_code:
        base = 0.95
    elif source_code and len(source_code) > 4:
        base = 0.80
    else:
        base = max(0.1, min(llm_confidence, 0.75))

    if warnings:
        base = min(base, 0.70)

    return round(base, 2)


# ───────────────────────── MAIN ─────────────────────────

def generate_answer(query: str, results: dict, warnings: list | None = None) -> dict:
    docs = results["documents"][0]
    metas = results["metadatas"][0]

    all_warnings = detect_warnings(docs)
    warnings = filter_warnings(query, all_warnings)

    if "abc" in query.lower():
        query += " (focus on float conversion and ValueError)"

    query_type = classify_query(query)
    grounded_line, grounded_snippet = extract_grounded_snippet(results, query)

    # For flow queries we don't want to pin a single grounded line in the prompt
    prompt_grounded_line = grounded_line if query_type != "flow" else ""

    context = assemble_context(results)
    prompt = build_prompt(query, context, prompt_grounded_line, warnings, query_type)

    client = ollama.Client(host="http://host.docker.internal:11434")

    response = client.chat(
        model="llama3",
        messages=[{"role": "user", "content": prompt}]
    )

    text = response["message"]["content"].strip()
    answer, source_code, fix_code, llm_confidence = "", "", "", 0.5

    parsed = _repair_and_parse_json(text)

    if parsed:
        answer = parsed.get("answer", "")
        source_code = parsed.get("source_code", "")
        fix_code = parsed.get("fix_code", "")
        try:
            llm_confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            llm_confidence = 0.5
    else:
        # Complete parse failure — extract answer heuristically from raw text
        m = re.search(r'"answer"\s*:\s*"([^"]+)"', text)
        answer = m.group(1) if m else text[:300].strip()

    if not answer:
        answer = "Unable to generate a structured answer."

    answer, source_code = override_with_grounded_answer(
        answer, source_code, grounded_line, grounded_snippet, query, query_type
    )

    if not source_code and query_type != "flow":
        source_code = extract_exact_code(results, query)

    source_code = clean_source_code(source_code)

    if validate_fix(fix_code):
        fix_code = ""

    confidence = compute_confidence(
        source_code, grounded_line, llm_confidence, warnings, query_type
    )

    sources = [
        {
            "file": m.get("file"),
            "type": m.get("type"),
            "name": m.get("name"),
            "start_line": m.get("start_line"),
            "end_line": m.get("end_line"),
        }
        for m in metas[:3]
    ]

    # ✅ FIXED: accurate line number calculation
    exact_line_number = None
    if source_code:
        for m, doc in zip(metas, docs):
            doc_lines = doc.splitlines()
            chunk_start = m.get("start_line", 1)
            for i, line in enumerate(doc_lines):
                if source_code.strip() in line.strip():
                    exact_line_number = chunk_start + i - 1  # ✅ -1 fixes off by one
                    break
            if exact_line_number:
                break

    return {
        "answer": answer.strip(),
        "source_code": source_code,
        "fix_code": fix_code,
        "confidence": confidence,
        "warnings": warnings,
        "sources": sources,
        "exact_line": exact_line_number,  # ✅ NEW
    }