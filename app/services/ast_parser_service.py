import ast

MAX_CHUNK_SIZE = 2000


def parse_python_file(file_data):

    content = file_data["content"]

    try:
        tree = ast.parse(content)
    except Exception:
        return []

    # ⭐ add parent reference
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    chunks = []
    covered_lines = set()

    # 🔹 IMPORT CHUNK (VERY IMPORTANT)
    import_lines = []
    import_start = None
    import_end = None

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            code = ast.get_source_segment(content, node)
            if code:
                import_lines.append(code)
                if import_start is None:
                    import_start = node.lineno
                import_end = getattr(node, "end_lineno", node.lineno)

    if import_lines:
        chunks.append({
            "type": "imports",
            "name": "imports_block",
            "file": file_data["path"],
            "language": file_data.get("language", "python"),
            "start_line": import_start,
            "end_line": import_end,
            "code": "\n".join(import_lines)
        })

        for i in range(import_start, import_end + 1):
            covered_lines.add(i)

    # 🔹 FUNCTIONS / METHODS / CLASSES
    for node in ast.walk(tree):

        if isinstance(node, ast.FunctionDef):

            code = ast.get_source_segment(content, node)
            if not code or len(code) > MAX_CHUNK_SIZE:
                continue

            parent = getattr(node, "parent", None)

            if isinstance(parent, ast.ClassDef):
                chunk_type = "method"
                class_name = parent.name
            else:
                chunk_type = "function"
                class_name = None

            chunk = {
                "type": chunk_type,
                "name": node.name,
                "signature": f"{node.name}({', '.join(arg.arg for arg in node.args.args)})",
                "class": class_name,
                "file": file_data["path"],
                "language": file_data.get("language", "python"),
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "docstring": ast.get_docstring(node),
                "code": code
            }

            chunks.append(chunk)

            for i in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                covered_lines.add(i)

        elif isinstance(node, ast.ClassDef):

            class_code = ast.get_source_segment(content, node)

            if class_code and len(class_code) <= MAX_CHUNK_SIZE:

                chunk = {
                    "type": "class",
                    "name": node.name,
                    "file": file_data["path"],
                    "language": file_data.get("language", "python"),
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node),
                    "code": class_code
                }

                chunks.append(chunk)

                for i in range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1):
                    covered_lines.add(i)

    # 🔹 GLOBAL CODE WITH LINE TRACKING ⭐⭐⭐
    lines = content.split("\n")

    current_lines = []
    start_line = None

    for i in range(1, len(lines) + 1):

        if i in covered_lines or not lines[i - 1].strip():
            continue

        if start_line is None:
            start_line = i

        current_lines.append(lines[i - 1])

        joined = "\n".join(current_lines)

        if len(joined) >= MAX_CHUNK_SIZE:
            chunks.append({
                "type": "global",
                "name": "global_scope",
                "file": file_data["path"],
                "language": file_data.get("language", "python"),
                "start_line": start_line,
                "end_line": i,
                "code": joined
            })
            current_lines = []
            start_line = None

    if current_lines:
        chunks.append({
            "type": "global",
            "name": "global_scope",
            "file": file_data["path"],
            "language": file_data.get("language", "python"),
            "start_line": start_line,
            "end_line": start_line + len(current_lines) - 1,
            "code": "\n".join(current_lines)
        })

    return chunks


# ⭐ MAIN PARSER
def parse_repository(code_files):

    all_chunks = []

    for file in code_files:

        if file["extension"] == ".py":
            chunks = parse_python_file(file)
            all_chunks.extend(chunks)

        else:
            code = file["content"]
            lines = code.split("\n")

            start = 1
            buffer = []

            for i, line in enumerate(lines, 1):
                buffer.append(line)

                joined = "\n".join(buffer)

                if len(joined) >= MAX_CHUNK_SIZE:
                    all_chunks.append({
                        "type": "file",
                        "name": file["file_name"],
                        "file": file["path"],
                        "language": file.get("language", "unknown"),
                        "start_line": start,
                        "end_line": i,
                        "code": joined
                    })
                    buffer = []
                    start = i + 1

            if buffer:
                all_chunks.append({
                    "type": "file",
                    "name": file["file_name"],
                    "file": file["path"],
                    "language": file.get("language", "unknown"),
                    "start_line": start,
                    "end_line": start + len(buffer) - 1,
                    "code": "\n".join(buffer)
                })

    return all_chunks