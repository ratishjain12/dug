"""LanceDB vector store — file-based, no server required."""

from __future__ import annotations

from pathlib import Path

import lancedb
import pyarrow as pa

# Dimension for all-MiniLM-L6-v2 (local). OpenAI text-embedding-3-small = 1536.
_DIM_LOCAL = 384
_DIM_OPENAI = 1536

TABLE_NAME = "functions"


def _schema(dim: int) -> pa.Schema:
    return pa.schema([
        pa.field("chunk_id",      pa.string()),
        pa.field("file_path",     pa.string()),
        pa.field("function_name", pa.string()),
        pa.field("start_line",    pa.int32()),
        pa.field("end_line",      pa.int32()),
        pa.field("language",      pa.string()),
        pa.field("vector",        pa.list_(pa.float32(), dim)),
    ])


def get_or_create_table(db_path: Path, embedding_mode: str = "local") -> lancedb.table.Table:
    db_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_path))
    dim = _DIM_OPENAI if embedding_mode == "openai" else _DIM_LOCAL
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=_schema(dim))


def delete_file_chunks(table: lancedb.table.Table, rel_path: str) -> None:
    """Remove all chunk rows belonging to a specific file."""
    try:
        # LanceDB uses SQL-style string for delete predicate
        table.delete(f"file_path = '{rel_path.replace(chr(39), chr(39)*2)}'")
    except Exception:
        pass


def upsert_chunks(table: lancedb.table.Table, rows: list[dict]) -> None:
    if not rows:
        return
    # LanceDB merge_insert: overwrite rows with matching chunk_id
    table.merge_insert("chunk_id") \
        .when_matched_update_all() \
        .when_not_matched_insert_all() \
        .execute(rows)


def search(
    table: lancedb.table.Table,
    query_vector: list[float],
    top_k: int = 10,
) -> list[dict]:
    results = (
        table.search(query_vector)
        .metric("cosine")
        .limit(top_k)
        .to_list()
    )
    hits = []
    for row in results:
        hits.append({
            "chunk_id":      row["chunk_id"],
            "file_path":     row["file_path"],
            "function_name": row["function_name"],
            "start_line":    row["start_line"],
            "end_line":      row["end_line"],
            "language":      row["language"],
            "score":         1.0 - row.get("_distance", 0.0),  # cosine: distance→similarity
        })
    return hits
