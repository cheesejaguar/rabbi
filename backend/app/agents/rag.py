"""
RAG (Retrieval Augmented Generation) module for rebbe.dev.

Indexes the Jewish texts library and provides semantic search for the agent pipeline.
Uses TF-IDF vectorization for lightweight, dependency-free text retrieval.
"""

import logging
import os
import re
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default library path relative to project root
DEFAULT_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "library"
)


@dataclass
class TextChunk:
    """A chunk of text from the library with metadata."""
    text: str
    title: str
    he_title: str = ""
    category: str = ""
    subcategory: str = ""
    section: str = ""  # Chapter/Daf/Section header
    language: str = "he"
    source_file: str = ""

    @property
    def context_label(self) -> str:
        """Human-readable label for this chunk's source."""
        parts = [self.title]
        if self.section:
            parts.append(self.section)
        return " > ".join(parts)


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
    """

    def __init__(self, library_path: Optional[str] = None):
        self.library_path = library_path or DEFAULT_LIBRARY_PATH
        self.chunks: list[TextChunk] = []
        self._idf: dict[str, float] = {}
        self._chunk_vectors: list[dict[str, float]] = []
        self._indexed = False

    @property
    def is_indexed(self) -> bool:
        return self._indexed

    def index(self) -> int:
        """
        Index all markdown files in the library.
        Returns the number of chunks indexed.
        """
        if not os.path.isdir(self.library_path):
            logger.warning(f"Library path not found: {self.library_path}")
            return 0

        logger.info(f"Indexing library at {self.library_path}...")
        self.chunks = []

        for dirpath, _, filenames in os.walk(self.library_path):
            for filename in sorted(filenames):
                if not filename.endswith(".md") or filename == "README.md":
                    continue
                filepath = os.path.join(dirpath, filename)
                try:
                    chunks = self._parse_file(filepath)
                    self.chunks.extend(chunks)
                except Exception as e:
                    logger.warning(f"Error parsing {filepath}: {e}")

        if self.chunks:
            self._build_index()
            self._indexed = True

        logger.info(f"Indexed {len(self.chunks)} chunks from library")
        return len(self.chunks)

    def search(self, query: str, top_k: int = 5, category: Optional[str] = None) -> list[SearchResult]:
        """
        Search for chunks relevant to the query.

        Args:
            query: Search query text
            top_k: Number of results to return
            category: Optional category filter (e.g., "Tanakh", "Talmud", "Mishnah")

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if not self._indexed:
            return []

        query_vec = self._vectorize_text(query)
        if not query_vec:
            return []

        results = []
        for i, chunk_vec in enumerate(self._chunk_vectors):
            # Apply category filter
            if category and self.chunks[i].category.lower() != category.lower():
                continue

            score = self._cosine_similarity(query_vec, chunk_vec)
            if score > 0:
                results.append(SearchResult(chunk=self.chunks[i], score=score))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def search_formatted(self, query: str, top_k: int = 5, category: Optional[str] = None) -> str:
        """
        Search and return results formatted for injection into an LLM prompt.
        """
        results = self.search(query, top_k=top_k, category=category)
        if not results:
            return ""

        lines = []
        for i, result in enumerate(results, 1):
            chunk = result.chunk
            lines.append(f"[Source {i}: {chunk.context_label} ({chunk.category})]")
            # Truncate very long chunks
            text = chunk.text
            if len(text) > 1500:
                text = text[:1500] + "..."
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    # --- Internal methods ---

    def _parse_file(self, filepath: str) -> list[TextChunk]:
        """Parse a markdown file into chunks split by section headers."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse YAML frontmatter
        metadata = self._parse_frontmatter(content)
        title = metadata.get("title", Path(filepath).stem.replace("_", " "))
        he_title = metadata.get("he_title", "")
        category = metadata.get("category", "")
        subcategory = metadata.get("subcategory", "")
        language = metadata.get("language", "he")

        # Remove frontmatter from content
        content = re.sub(r'^---\n.*?---\n', '', content, flags=re.DOTALL)

        # Remove the top-level title headers (# Title, ## Hebrew Title)
        content = re.sub(r'^#[^#].*\n', '', content)
        content = re.sub(r'^##\s+[^\n]*[\u0590-\u05FF][^\n]*\n', '', content)

        # Split by ## headers (chapters, daf pages, sections)
        sections = re.split(r'^(## .+)$', content, flags=re.MULTILINE)

        chunks = []
        current_section = ""

        for part in sections:
            part = part.strip()
            if not part:
                continue
            if part.startswith("## "):
                current_section = part[3:].strip()
            else:
                # This is section content - chunk it
                text = part.strip()
                if len(text) < 20:
                    continue

                # For very long sections, split into sub-chunks
                sub_chunks = self._split_long_text(text, max_chars=3000)
                for j, sub_text in enumerate(sub_chunks):
                    section_label = current_section
                    if len(sub_chunks) > 1:
                        section_label = f"{current_section} (part {j + 1})"

                    chunks.append(TextChunk(
                        text=sub_text,
                        title=title,
                        he_title=he_title,
                        category=category,
                        subcategory=subcategory,
                        section=section_label,
                        language=language,
                        source_file=filepath,
                    ))

        return chunks

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter from markdown content."""
        match = re.match(r'^---\n(.*?)---\n', content, re.DOTALL)
        if not match:
            return {}

        metadata = {}
        for line in match.group(1).strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                metadata[key] = value
        return metadata

    def _split_long_text(self, text: str, max_chars: int = 3000) -> list[str]:
        """Split long text into chunks, preferring paragraph boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) > max_chars and current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(para)
            current_len += len(para) + 2

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into words, handling both English and Hebrew."""
        # Lowercase English, keep Hebrew as-is
        text = text.lower()
        # Split on non-alphanumeric, keeping Hebrew chars
        tokens = re.findall(r'[\w\u0590-\u05FF]+', text)
        # Filter very short tokens and stop words
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'shall', 'can', 'to', 'of',
            'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
            'that', 'which', 'who', 'whom', 'this', 'these', 'those',
            'it', 'its', 'he', 'she', 'they', 'them', 'his', 'her',
            'their', 'and', 'but', 'or', 'nor', 'not', 'so', 'if',
        }
        return [t for t in tokens if len(t) > 1 and t not in stop_words]

    def _build_index(self):
        """Build TF-IDF index over all chunks."""
        n_docs = len(self.chunks)

        # Count document frequency for each term
        df = Counter()
        chunk_token_lists = []

        for chunk in self.chunks:
            tokens = self._tokenize(chunk.text)
            chunk_token_lists.append(tokens)
            unique_tokens = set(tokens)
            for token in unique_tokens:
                df[token] += 1

        # Compute IDF
        self._idf = {}
        for term, freq in df.items():
            self._idf[term] = math.log(n_docs / (1 + freq))

        # Compute TF-IDF vectors for each chunk
        self._chunk_vectors = []
        for tokens in chunk_token_lists:
            tf = Counter(tokens)
            total = len(tokens) if tokens else 1
            vec = {}
            for term, count in tf.items():
                if term in self._idf:
                    vec[term] = (count / total) * self._idf[term]
            self._chunk_vectors.append(vec)

    def _vectorize_text(self, text: str) -> dict[str, float]:
        """Convert query text to TF-IDF vector."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = len(tokens)
        vec = {}
        for term, count in tf.items():
            if term in self._idf:
                vec[term] = (count / total) * self._idf[term]
        return vec

    def _cosine_similarity(self, vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """Compute cosine similarity between two sparse vectors."""
        if not vec_a or not vec_b:
            return 0.0

        # Dot product (only over shared keys)
        shared_keys = set(vec_a.keys()) & set(vec_b.keys())
        if not shared_keys:
            return 0.0

        dot_product = sum(vec_a[k] * vec_b[k] for k in shared_keys)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)
