"""
RAG (Retrieval Augmented Generation) module for rebbe.dev.

Indexes the Jewish texts library and provides semantic search for the agent pipeline.
Uses TF-IDF vectorization for lightweight, dependency-free text retrieval.

Supports two modes:
  1. Build-time: Parse markdown files and build the TF-IDF index, then serialize
     to a gzipped JSON file (run via `python -m backend.app.agents.rag`).
  2. Runtime: Load the pre-built index from the gzipped JSON for fast cold starts
     on serverless platforms like Vercel.
"""

import gzip
import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root (4 levels up from this file)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DEFAULT_LIBRARY_PATH = os.path.join(_PROJECT_ROOT, "library")
DEFAULT_INDEX_PATH = os.path.join(_PROJECT_ROOT, "backend", "app", "rag_index.json.gz")


@dataclass
class TextChunk:
    """A chunk of text from the library with metadata."""
    text: str
    title: str
    he_title: str = ""
    category: str = ""
    subcategory: str = ""
    section: str = ""
    language: str = "he"

    @property
    def context_label(self) -> str:
        parts = [self.title]
        if self.section:
            parts.append(self.section)
        return " > ".join(parts)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "title": self.title,
            "he_title": self.he_title,
            "category": self.category,
            "subcategory": self.subcategory,
            "section": self.section,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextChunk":
        return cls(**d)


@dataclass
class SearchResult:
    """A search result with score and chunk."""
    chunk: TextChunk
    score: float


class TextRetriever:
    """
    Retrieves relevant text chunks from the Jewish texts library.

    Uses TF-IDF vectorization for fast, lightweight search without
    external embedding dependencies.

    Preferred usage for serverless:
        retriever = TextRetriever()
        retriever.load(index_path)  # fast: loads pre-built JSON index

    For build-time index creation:
        retriever = TextRetriever()
        retriever.index(library_path)
        retriever.save(index_path)
    """

    def __init__(self):
        self.chunks: list[TextChunk] = []
        self._idf: dict[str, float] = {}
        self._chunk_vectors: list[dict[str, float]] = []
        self._indexed = False

    @property
    def is_indexed(self) -> bool:
        return self._indexed

    # ------------------------------------------------------------------
    # Build-time: parse markdown files and build TF-IDF index
    # ------------------------------------------------------------------

    def index(self, library_path: Optional[str] = None) -> int:
        """
        Index all markdown files in the library directory.
        Returns the number of chunks indexed.
        """
        library_path = library_path or DEFAULT_LIBRARY_PATH
        if not os.path.isdir(library_path):
            logger.warning(f"Library path not found: {library_path}")
            return 0

        logger.info(f"Indexing library at {library_path}...")
        self.chunks = []

        for dirpath, _, filenames in os.walk(library_path):
            for filename in sorted(filenames):
                if not filename.endswith(".md") or filename == "README.md":
                    continue
                filepath = os.path.join(dirpath, filename)
                try:
                    self.chunks.extend(self._parse_file(filepath))
                except Exception as e:
                    logger.warning(f"Error parsing {filepath}: {e}")

        if self.chunks:
            self._build_tfidf()
            self._indexed = True

        logger.info(f"Indexed {len(self.chunks)} chunks from library")
        return len(self.chunks)

    def save(self, index_path: Optional[str] = None) -> str:
        """Serialize the index to a gzipped JSON file with compact format.

        Uses a vocabulary-indexed format to avoid repeating term strings across
        32K+ chunk vectors. Text is truncated to 1500 chars (the display limit).
        """
        index_path = index_path or DEFAULT_INDEX_PATH

        # Build term vocabulary: term → integer ID
        vocab = sorted(self._idf.keys())
        term_to_id = {t: i for i, t in enumerate(vocab)}

        # Compact chunks: truncate text to display limit
        compact_chunks = []
        for c in self.chunks:
            d = c.to_dict()
            d["text"] = d["text"][:1500]
            compact_chunks.append(d)

        # Compact vectors: replace {term: weight} with [[term_id, ...], [weight, ...]]
        compact_vectors = []
        for vec in self._chunk_vectors:
            ids = []
            weights = []
            for term, weight in vec.items():
                if term in term_to_id:
                    ids.append(term_to_id[term])
                    weights.append(round(weight, 4))
            compact_vectors.append([ids, weights])

        # IDF as parallel arrays aligned with vocab
        idf_values = [round(self._idf[t], 4) for t in vocab]

        data = {
            "v": 2,  # format version
            "vocab": vocab,
            "idf": idf_values,
            "chunks": compact_chunks,
            "vectors": compact_vectors,
        }
        with gzip.open(index_path, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        size_mb = os.path.getsize(index_path) / (1024 * 1024)
        logger.info(f"Saved RAG index to {index_path} ({size_mb:.1f} MB, {len(self.chunks)} chunks)")
        return index_path

    # ------------------------------------------------------------------
    # Runtime: load pre-built index (fast cold start)
    # ------------------------------------------------------------------

    def load(self, index_path: Optional[str] = None) -> int:
        """
        Load a pre-built index from gzipped JSON. Much faster than re-indexing.
        Returns the number of chunks loaded.
        """
        index_path = index_path or DEFAULT_INDEX_PATH
        if not os.path.isfile(index_path):
            logger.warning(f"RAG index file not found: {index_path}")
            return 0

        logger.info(f"Loading RAG index from {index_path}...")
        with gzip.open(index_path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        self.chunks = [TextChunk.from_dict(d) for d in data["chunks"]]

        if data.get("v") == 2:
            # Compact vocabulary-indexed format
            vocab = data["vocab"]
            self._idf = {vocab[i]: v for i, v in enumerate(data["idf"])}
            self._chunk_vectors = []
            for ids, weights in data["vectors"]:
                self._chunk_vectors.append(
                    {vocab[tid]: w for tid, w in zip(ids, weights)}
                )
        else:
            # Legacy format (dict-based)
            self._idf = data["idf"]
            self._chunk_vectors = data["vectors"]

        self._indexed = True
        logger.info(f"Loaded {len(self.chunks)} chunks from pre-built index")
        return len(self.chunks)

    def ensure_loaded(self, index_path: Optional[str] = None,
                      library_path: Optional[str] = None) -> int:
        """
        Ensure the index is ready. Tries in order:
          1. Already loaded → no-op
          2. Pre-built index file exists → load it
          3. Library directory exists → build index from scratch
        Returns the number of chunks available.
        """
        if self._indexed:
            return len(self.chunks)

        index_path = index_path or DEFAULT_INDEX_PATH
        if os.path.isfile(index_path):
            return self.load(index_path)

        library_path = library_path or DEFAULT_LIBRARY_PATH
        if os.path.isdir(library_path):
            count = self.index(library_path)
            # Try to save for next time (will silently fail on read-only fs)
            try:
                self.save(index_path)
            except OSError:
                pass
            return count

        logger.warning("No RAG index or library found - text retrieval unavailable")
        return 0

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5,
               category: Optional[str] = None) -> list[SearchResult]:
        """
        Search for chunks relevant to the query.

        Args:
            query: Search query text
            top_k: Number of results to return
            category: Optional category filter (e.g., "Tanakh", "Talmud")
        """
        if not self._indexed:
            return []

        query_vec = self._vectorize_query(query)
        if not query_vec:
            return []

        results = []
        for i, chunk_vec in enumerate(self._chunk_vectors):
            if category and self.chunks[i].category.lower() != category.lower():
                continue
            score = _cosine_similarity(query_vec, chunk_vec)
            if score > 0:
                results.append(SearchResult(chunk=self.chunks[i], score=score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def search_formatted(self, query: str, top_k: int = 5,
                         category: Optional[str] = None) -> str:
        """Search and return results formatted for injection into an LLM prompt."""
        results = self.search(query, top_k=top_k, category=category)
        if not results:
            return ""

        lines = []
        for i, result in enumerate(results, 1):
            chunk = result.chunk
            lines.append(f"[Source {i}: {chunk.context_label} ({chunk.category})]")
            text = chunk.text[:1500] + "..." if len(chunk.text) > 1500 else chunk.text
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _parse_file(self, filepath: str) -> list[TextChunk]:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        metadata = _parse_frontmatter(content)
        title = metadata.get("title", Path(filepath).stem.replace("_", " "))
        he_title = metadata.get("he_title", "")
        category = metadata.get("category", "")
        subcategory = metadata.get("subcategory", "")
        language = metadata.get("language", "he")

        # Strip frontmatter and top-level headers
        content = re.sub(r'^---\n.*?---\n', '', content, flags=re.DOTALL)
        content = re.sub(r'^#[^#].*\n', '', content)
        content = re.sub(r'^##\s+[^\n]*[\u0590-\u05FF][^\n]*\n', '', content)

        sections = re.split(r'^(## .+)$', content, flags=re.MULTILINE)
        chunks: list[TextChunk] = []
        current_section = ""

        for part in sections:
            part = part.strip()
            if not part:
                continue
            if part.startswith("## "):
                current_section = part[3:].strip()
                continue

            if len(part) < 20:
                continue

            sub_chunks = _split_long_text(part)
            for j, sub_text in enumerate(sub_chunks):
                label = current_section
                if len(sub_chunks) > 1:
                    label = f"{current_section} (part {j + 1})"
                chunks.append(TextChunk(
                    text=sub_text, title=title, he_title=he_title,
                    category=category, subcategory=subcategory,
                    section=label, language=language,
                ))
        return chunks

    # ------------------------------------------------------------------
    # Internal: TF-IDF
    # ------------------------------------------------------------------

    def _build_tfidf(self):
        n_docs = len(self.chunks)
        df: Counter = Counter()
        all_tokens: list[list[str]] = []

        for chunk in self.chunks:
            tokens = _tokenize(chunk.text)
            all_tokens.append(tokens)
            for t in set(tokens):
                df[t] += 1

        self._idf = {term: math.log(n_docs / (1 + freq)) for term, freq in df.items()}

        self._chunk_vectors = []
        for tokens in all_tokens:
            tf = Counter(tokens)
            total = len(tokens) or 1
            self._chunk_vectors.append(
                {t: (c / total) * self._idf[t] for t, c in tf.items() if t in self._idf}
            )

    def _vectorize_query(self, text: str) -> dict[str, float]:
        tokens = _tokenize(text)
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = len(tokens)
        return {t: (c / total) * self._idf[t] for t, c in tf.items() if t in self._idf}


# ------------------------------------------------------------------
# Module-level helpers (pure functions, no state)
# ------------------------------------------------------------------

_STOP_WORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'shall', 'can', 'to', 'of',
    'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
    'that', 'which', 'who', 'whom', 'this', 'these', 'those',
    'it', 'its', 'he', 'she', 'they', 'them', 'his', 'her',
    'their', 'and', 'but', 'or', 'nor', 'not', 'so', 'if',
})


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r'[\w\u0590-\u05FF]+', text)
    return [t for t in tokens if len(t) > 1 and t not in _STOP_WORDS]


def _parse_frontmatter(content: str) -> dict:
    match = re.match(r'^---\n(.*?)---\n', content, re.DOTALL)
    if not match:
        return {}
    metadata = {}
    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _split_long_text(text: str, max_chars: int = 3000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    current: list[str] = []
    current_len = 0
    for para in text.split("\n\n"):
        if current_len + len(para) > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[k] * b[k] for k in shared)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ------------------------------------------------------------------
# CLI: build the index (run during CI / Vercel build)
#   python -m backend.app.agents.rag [--library PATH] [--output PATH]
# ------------------------------------------------------------------

def build_index_cli():
    """Build and save the RAG index from the library directory."""
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Build RAG index from Jewish texts library")
    parser.add_argument("--library", default=DEFAULT_LIBRARY_PATH, help="Path to library/")
    parser.add_argument("--output", default=DEFAULT_INDEX_PATH, help="Output index JSON path")
    args = parser.parse_args()

    retriever = TextRetriever()
    count = retriever.index(args.library)
    if count == 0:
        print(f"ERROR: No chunks indexed from {args.library}")
        raise SystemExit(1)

    path = retriever.save(args.output)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Built index: {count} chunks, {size_mb:.1f} MB → {path}")


if __name__ == "__main__":
    build_index_cli()
