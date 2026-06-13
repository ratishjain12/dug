from __future__ import annotations


class LocalEmbedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


class OpenAIEmbedder:
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding


def get_embedder(config: dict) -> LocalEmbedder | OpenAIEmbedder:
    if config.get("embedding_mode") == "openai":
        return OpenAIEmbedder(api_key=config["api_key"])
    return LocalEmbedder()
