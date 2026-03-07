"""
Knowledge Bank: RAG for uploaded documents.

- Chunking: 500–800 tokens with overlap
- Embedding: Chutes (OpenAI-compatible) using Qwen/Qwen3-Embedding-8B
- Storage: PostgreSQL + pgvector
- Tables: knowledge_files, knowledge_chunks
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)

# Supported extensions for upload (matches document_tools)
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".pptx", ".docx", ".md"}

# Chunking: 500–800 tokens, overlap ~100
CHUNK_SIZE_TOKENS = int(os.environ.get("KNOWLEDGE_CHUNK_SIZE", "600"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("KNOWLEDGE_CHUNK_OVERLAP", "100"))

# Qwen3-Embedding-8B dimension
EMBEDDING_DIM = 4096


def _get_connection():
    """Get psycopg connection for knowledge DB."""
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    if not url:
        raise ValueError(
            "KNOWLEDGE_DATABASE_URL is not set. Add it to .env for the Knowledge Bank."
        )
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(url)
    register_vector(conn)
    return conn


def _ensure_schema(conn):
    """Create tables if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_files (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                uploaded_at TIMESTAMPTZ DEFAULT NOW(),
                size_bytes BIGINT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                search_count INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT,
                tags TEXT[]
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id SERIAL PRIMARY KEY,
                file_id INTEGER NOT NULL REFERENCES knowledge_files(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector(4096)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_file_id
            ON knowledge_chunks(file_id)
        """)
    conn.commit()
    # HNSW index in separate transaction — if it fails, tables are already committed
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
                ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
            """)
        conn.commit()
    except Exception:
        conn.rollback()
        pass  # Sequential scan works for small datasets


def _get_embedding_model():
    """Get OpenAI-compatible embedding model (Chutes + Qwen3-Embedding-8B)."""
    from langchain_openai import OpenAIEmbeddings

    base_url = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None
    api_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("KNOWLEDGE_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")

    return OpenAIEmbeddings(
        model=model,
        openai_api_key=api_key,
        openai_api_base=base_url,
    )


def _chunk_text(text: str) -> list[str]:
    """Split text into chunks of ~CHUNK_SIZE_TOKENS with overlap."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = None

    def _token_count(s: str) -> int:
        if enc:
            return len(enc.encode(s))
        return len(s) // 4  # fallback

    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = _token_count(line + "\n")
        if current_tokens + line_tokens > CHUNK_SIZE_TOKENS and current_chunk:
            chunks.append("\n".join(current_chunk))
            # Overlap: keep last N tokens worth of content
            overlap_tokens = 0
            overlap_lines: list[str] = []
            for i in range(len(current_chunk) - 1, -1, -1):
                t = _token_count(current_chunk[i] + "\n")
                if overlap_tokens + t > CHUNK_OVERLAP_TOKENS:
                    break
                overlap_lines.insert(0, current_chunk[i])
                overlap_tokens += t
            current_chunk = overlap_lines
            current_tokens = overlap_tokens
        current_chunk.append(line)
        current_tokens += line_tokens

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upload_file(data: bytes, filename: str, tags: list[str] | None = None) -> dict:
    """
    Extract text, chunk, embed, and store. Returns file metadata.
    """
    from .document_tools import extract_text_from_document_bytes

    if not data:
        return {"success": False, "error": "File is empty"}

    ext = "." + (filename or "").split(".")[-1].lower() if "." in (filename or "") else ""
    if ext not in DOCUMENT_EXTENSIONS:
        return {"success": False, "error": f"Unsupported format: {filename}"}

    text = extract_text_from_document_bytes(data, filename or "")
    if text.startswith("Error:") or text.startswith("Unsupported"):
        return {"success": False, "error": text}

    content_hash = _content_hash(data)
    chunks = _chunk_text(text)
    tags_arr = [t.strip() for t in (tags or []) if t and t.strip()]
    if not chunks:
        return {"success": False, "error": "No content extracted"}

    conn = _get_connection()
    try:
        _ensure_schema(conn)
        embeddings = _get_embedding_model()
        vectors = embeddings.embed_documents(chunks)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_files (filename, size_bytes, chunk_count, content_hash, tags)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, filename, uploaded_at, size_bytes, chunk_count, search_count
                """,
                (filename, len(data), len(chunks), content_hash, tags_arr or None),
            )
            row = cur.fetchone()
            file_id = row[0]

            for i, (content, vec) in enumerate(zip(chunks, vectors)):
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks (file_id, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (file_id, i, content, vec),
                )

        conn.commit()
        return {
            "success": True,
            "file": {
                "id": file_id,
                "filename": row[1],
                "uploaded_at": row[2].isoformat() if row[2] else None,
                "size_bytes": row[3],
                "chunk_count": row[4],
                "search_count": row[5],
                "tags": tags_arr,
            },
        }
    except Exception as e:
        conn.rollback()
        logger.exception("Upload failed: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def search(
    query: str,
    max_chunks: int = 5,
    filename_filter: str | None = None,
    tags: list[str] | None = None,
) -> list[dict]:
    """
    Semantic search over knowledge chunks. Returns chunks with file_id, filename, content.

    Optional filters applied BEFORE semantic ranking:
      filename_filter: case-insensitive substring match on filename
      tags: list of tag strings — file must have ALL tags (AND logic)

    Increments search_count for each file that had a match.
    """
    conn = _get_connection()
    try:
        _ensure_schema(conn)
        embeddings = _get_embedding_model()
        qvec = embeddings.embed_query(query)

        # Build optional file_id filter
        file_id_filter = None
        if filename_filter or tags:
            with conn.cursor() as cur:
                conditions = []
                params: list = []
                if filename_filter:
                    conditions.append("filename ILIKE %s")
                    params.append(f"%{filename_filter}%")
                if tags:
                    for tag in tags:
                        conditions.append("%s = ANY(COALESCE(tags, '{}'))")
                        params.append(tag)
                where = " AND ".join(conditions)
                cur.execute(f"SELECT id FROM knowledge_files WHERE {where}", params)
                rows_f = cur.fetchall()
            file_id_filter = [r[0] for r in rows_f]
            if not file_id_filter:
                return []  # Filter matched no files

        with conn.cursor() as cur:
            if file_id_filter:
                cur.execute(
                    """
                    SELECT c.id, c.file_id, c.chunk_index, c.content, f.filename
                    FROM knowledge_chunks c
                    JOIN knowledge_files f ON f.id = c.file_id
                    WHERE c.file_id = ANY(%s)
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (file_id_filter, qvec, max_chunks),
                )
            else:
                cur.execute(
                    """
                    SELECT c.id, c.file_id, c.chunk_index, c.content, f.filename
                    FROM knowledge_chunks c
                    JOIN knowledge_files f ON f.id = c.file_id
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (qvec, max_chunks),
                )
            rows = cur.fetchall()

        if not rows:
            return []

        # Increment search_count for each file that had a match
        file_ids = list({r[1] for r in rows})
        with conn.cursor() as cur:
            for fid in file_ids:
                cur.execute(
                    "UPDATE knowledge_files SET search_count = search_count + 1 WHERE id = %s",
                    (fid,),
                )
        conn.commit()

        return [
            {
                "id": r[0],
                "file_id": r[1],
                "chunk_index": r[2],
                "content": r[3],
                "filename": r[4],
            }
            for r in rows
        ]
    except Exception as e:
        conn.rollback()
        logger.exception("Search failed: %s", e)
        return []
    finally:
        conn.close()


def list_files(search_query: str | None = None) -> list[dict]:
    """List all knowledge files with metadata. Optionally filter by search_query (filename or tags)."""
    conn = _get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            if search_query and search_query.strip():
                q = f"%{search_query.strip()}%"
                cur.execute(
                    """
                    SELECT id, filename, uploaded_at, size_bytes, chunk_count, search_count, content_hash, tags
                    FROM knowledge_files
                    WHERE filename ILIKE %s
                       OR EXISTS (SELECT 1 FROM unnest(COALESCE(tags, '{}')) tag WHERE tag ILIKE %s)
                    ORDER BY uploaded_at DESC
                    """,
                    (q, q),
                )
            else:
                cur.execute(
                    """
                    SELECT id, filename, uploaded_at, size_bytes, chunk_count, search_count, content_hash, tags
                    FROM knowledge_files
                    ORDER BY uploaded_at DESC
                    """
                )
            rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "filename": r[1],
                "uploaded_at": r[2].isoformat() if r[2] else None,
                "size_bytes": r[3],
                "chunk_count": r[4],
                "search_count": r[5],
                "content_hash": r[6],
                "tags": r[7] or [],
            }
            for r in rows
        ]
    except Exception as e:
        logger.exception("List files failed: %s", e)
        return []
    finally:
        conn.close()


def get_file_chunks(file_id: int) -> list[dict]:
    """Get all chunks for a file."""
    conn = _get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.chunk_index, c.content
                FROM knowledge_chunks c
                WHERE c.file_id = %s
                ORDER BY c.chunk_index
                """,
                (file_id,),
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "chunk_index": r[1], "content": r[2]}
            for r in rows
        ]
    except Exception as e:
        logger.exception("Get chunks failed: %s", e)
        return []
    finally:
        conn.close()


def get_file_content(file_id: int) -> str | None:
    """Reconstruct full file content from chunks."""
    chunks = get_file_chunks(file_id)
    if not chunks:
        return None
    return "\n\n".join(c["content"] for c in sorted(chunks, key=lambda x: x["chunk_index"]))


def update_file_tags(file_id: int, tags: list[str]) -> bool:
    """Update tags for a file."""
    tags_arr = [t.strip() for t in tags if t and t.strip()]
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_files SET tags = %s WHERE id = %s",
                (tags_arr or [], file_id),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception as e:
        conn.rollback()
        logger.exception("Update tags failed: %s", e)
        return False
    finally:
        conn.close()


def upload_from_url(url: str, filename: str | None = None) -> dict:
    """
    Fetch content from URL and add to Knowledge Bank. Supports HTML (extracts text) and plain text.
    """
    import re

    import httpx

    if not url or not url.strip():
        return {"success": False, "error": "URL is empty"}
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "URL must start with http:// or https://"}

    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "Agent-KnowledgeBank/1.0"},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if "text/html" in ct or "application/xhtml+xml" in ct:
        html = resp.text
        text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.I)
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return {"success": False, "error": "No extractable text from HTML"}
        data = text.encode("utf-8")
        fn = filename or "page.html"
        if not fn.endswith(".txt"):
            fn = (fn.rsplit(".", 1)[0] if "." in fn else fn) + ".txt"
    elif "text/plain" in ct or "application/json" in ct:
        data = resp.content
        fn = filename or "document.txt"
    else:
        return {"success": False, "error": f"Unsupported content type: {ct}. Use HTML or plain text URLs."}

    return upload_file(data, fn)


def delete_file(file_id: int) -> bool:
    """Delete a file and its chunks (CASCADE)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_files WHERE id = %s", (file_id,))
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0
    except Exception as e:
        conn.rollback()
        logger.exception("Delete failed: %s", e)
        return False
    finally:
        conn.close()


def is_configured() -> bool:
    """Check if Knowledge Bank is configured."""
    return bool(os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip())
