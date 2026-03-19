from app.core.model_loader import model

def create_embeddings(chunks):

    texts = []

    for chunk in chunks:

        text = f"""
Function/Class: {chunk.get("name")}
Type: {chunk.get("type")}
File: {chunk.get("file")}

Code:
{chunk.get("code")}
"""

        texts.append(text)

    embeddings = model.encode(texts)

    return embeddings, texts