from fastapi import APIRouter
from pydantic import BaseModel

from app.services.repo_services import clone_repository
from app.services.ast_parser_service import parse_repository
from app.services.parser_services import scan_repository
from app.services.embedding_service import create_embeddings
from app.db.vector_store import store_embeddings, collection
from app.services.retriever_service import search_code
from app.services.llm_service import generate_answer
from app.services.history_service import save_query

router = APIRouter()


# -------- Request Models --------
class RepoRequest(BaseModel):
    repo_path: str

class AskRequest(BaseModel):
    query: str
    repo_path: str | None = None   # ✅ optional
    repo_url: str | None = None    # ✅ new (optional)


# -------- Clone Repo --------
@router.post("/clone_repo")
def clone_repo(repo_url: str):
    path = clone_repository(repo_url)
    return {
        "message": "Repository cloned",
        "path": path
    }


# -------- Scan Repo --------
@router.post("/scan_repo")
def scan_repo(req: RepoRequest):
    files = scan_repository(req.repo_path)
    return {
        "total_files": len(files),
        "files": files[:5]
    }


# -------- Parse Repo --------
@router.post("/parse_repo")
def parse_repo(req: RepoRequest):
    files = scan_repository(req.repo_path)
    chunks = parse_repository(files)
    return {
        "total_chunks": len(chunks),
        "chunks": chunks[:5]
    }


# -------- Embed Repo --------
@router.post("/embed_repo")
def embed_repo(req: RepoRequest):

    repo_path = req.repo_path.replace("\\", "/")

    files = scan_repository(repo_path)
    chunks = parse_repository(files)

    embeddings, texts = create_embeddings(chunks)
    store_embeddings(embeddings, texts, chunks, repo_path)

    return {
        "message": "Embeddings stored successfully",
        "total_chunks": len(chunks)
    }


# -------- Ask Question (UPDATED 🔥) --------
@router.post("/ask_repo")
def ask_repo(req: AskRequest):

    # ✅ Decide source (NEW LOGIC)
    if req.repo_url:
        repo_path = clone_repository(req.repo_url)
    else:
        repo_path = req.repo_path
    if not repo_path:
        return {"error": "Invalid repo path or clone failed"}

    repo_path = repo_path.replace("\\", "/")

    # 🔥 CHECK IF ALREADY EMBEDDED
    existing = collection.get(where={"repo": repo_path})

    if not existing["ids"]:
        files = scan_repository(repo_path)
        chunks = parse_repository(files)

        embeddings, texts = create_embeddings(chunks)
        store_embeddings(embeddings, texts, chunks, repo_path)

    # 🔥 normal flow
    data = search_code(req.query, repo_path)

    results = data["results"]
    warnings = data["warnings"]

    response = generate_answer(req.query, results, warnings)
    try:
        save_query("guest", req.query, response["answer"])
    except Exception as e:
        print(f"History save failed: {e}")  # ✅ now you can see the error

    return response