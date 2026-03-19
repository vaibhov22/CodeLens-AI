import chromadb

client = chromadb.Client()
collection = client.get_or_create_collection(name="code_chunks")


def clean_metadata(meta):
    cleaned = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        cleaned[k] = v
    return cleaned


def store_embeddings(embeddings, texts, chunks, repo_path):

    # normalize repo path
    repo_path = repo_path.replace("\\", "/")

    for i in range(len(embeddings)):

        meta = clean_metadata(chunks[i])

        # ⭐ store SAME repo_path everywhere
        meta["repo"] = repo_path

        file_path = chunks[i].get("file", "").replace("\\", "/")

        collection.add(
            embeddings=[embeddings[i].tolist()],
            documents=[texts[i]],
            metadatas=[meta],
            ids=[f"{i}_{file_path}"]
        )