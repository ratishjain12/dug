from __future__ import annotations

import logging
import os
import warnings

# Suppress HuggingFace noise before any library import
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")

for _noisy in ("sentence_transformers", "huggingface_hub", "transformers",
               "torch", "tokenizers"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)


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
