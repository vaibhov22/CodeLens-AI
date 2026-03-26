import os
import time
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.core.model_loader import model
import chardet
from pathspec import PathSpec

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".java",
    ".html", ".css", ".json"
]
IGNORED_DIRS = ["node_modules", ".git", "__pycache__", "venv", ".idea", "dist", "build","flask_env", "env", ".venv"]
MAX_FILE_SIZE_BYTES = 1_000_000
MAX_WORKERS = 8

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".html": "html",
    ".css": "css"
}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scan.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# LOAD .gitignore
# ─────────────────────────────────────────────

def load_gitignore(repo_path):
    gitignore_path = os.path.join(repo_path, ".gitignore")

    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        log.info(".gitignore loaded")
        return PathSpec.from_lines("gitwildmatch", lines)

    return None

# ─────────────────────────────────────────────
# READ FILE
# ─────────────────────────────────────────────

def read_file(full_path, file, repo_path, gitignore_spec):

    relative_path = os.path.relpath(full_path, repo_path)

    if gitignore_spec and gitignore_spec.match_file(relative_path):
        return None

    try:
        size = os.path.getsize(full_path)
    except:
        return None

    if size > MAX_FILE_SIZE_BYTES:
        return None

    try:
        with open(full_path, "rb") as f:
            raw = f.read()

        # skip binary files
        if b'\x00' in raw:
            return None
 
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"

        content = raw.decode(encoding, errors="replace")

    except:
        return None

    extension = os.path.splitext(file)[1]
    language = LANGUAGE_MAP.get(extension, "unknown")

    lines_of_code = content.count("\n") + 1
    last_modified = time.ctime(os.path.getmtime(full_path))

    return {
        "file_name": file,
        "path": relative_path,
        "extension": extension,
        "language": language,
        "size_bytes": size,
        "lines_of_code": lines_of_code,
        "last_modified": last_modified,
        "encoding": encoding,
        "content": content,
        "lines": content.split("\n")
    }

# ─────────────────────────────────────────────
# COLLECT FILE PATHS
# ─────────────────────────────────────────────

def collect_file_paths(repo_path):
    file_paths = []

    for root, dirs, files in os.walk(repo_path):

        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            if any(file.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                full_path = os.path.join(root, file)
                file_paths.append((full_path, file))

    return file_paths

# ─────────────────────────────────────────────
# SCAN REPOSITORY
# ─────────────────────────────────────────────

def scan_repository(repo_path):
    log.info(f"Scanning repository: {repo_path}")

    gitignore_spec = load_gitignore(repo_path)
    file_paths = collect_file_paths(repo_path)

    code_files = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(read_file, full_path, file, repo_path, gitignore_spec): full_path
            for full_path, file in file_paths
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                code_files.append(result)

    log.info(f"Scanned {len(code_files)} valid files")
    return code_files

# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────

def search_in_files(code_files, keyword):
    return [f for f in code_files if keyword.lower() in f["content"].lower()]

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────

def print_summary(code_files):
    total_files = len(code_files)
    total_lines = sum(f["lines_of_code"] for f in code_files)
    total_size = sum(f["size_bytes"] for f in code_files)
    ext_counts = Counter(f["extension"] for f in code_files)

    print("\n" + "=" * 40)
    print("SCAN SUMMARY")
    print("=" * 40)
    print(f"Files: {total_files}")
    print(f"Lines: {total_lines}")
    print(f"Size: {total_size / 1024:.2f} KB")

    print("\nBy Extension:")
    for ext, count in ext_counts.items():
        print(f"{ext}: {count}")

    print("=" * 40 + "\n")

# ─────────────────────────────────────────────
# EXPORT JSON
# ─────────────────────────────────────────────

def export_to_json(code_files, output_path="scan_result.json"):

    lightweight = [
        {k: v for k, v in f.items() if k != "content"}
        for f in code_files
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(lightweight, f, indent=2)

    log.info(f"Exported to {output_path}")

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    repo = sys.argv[1] if len(sys.argv) > 1 else "."

    files = scan_repository(repo)

    print_summary(files)

    export_to_json(files)

    matches = search_in_files(files, "TODO")

    if matches:
        print("\nFound TODO in:")
        for m in matches:
            print(m["path"])
