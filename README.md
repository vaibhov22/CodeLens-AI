# 🤖 AI Repo Explainer

An AI-powered system that analyzes code repositories and answers developer questions.

## 🚀 Features
- Repo parsing (AST-based)
- Semantic search using embeddings (BGE + ChromaDB)
- Bug detection (feature order, float crash, etc.)
- LLM-powered explanations (Ollama - Llama3)
- Grounded answers with source code references

## 🧠 Example
Question:
> Why does it crash on "abc"?

Answer:
> ValueError occurs at float(x) due to invalid input

## 🐳 Run with Docker
```bash
docker build -t ai_repo_explainer .
docker run -p 8000:8000 ai_repo_explainer