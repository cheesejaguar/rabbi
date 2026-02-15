"""Tests for rag.py - RAG retrieval system unit and integration tests.

Tests cover:
  - TextChunk data model
  - SearchResult data model
  - Helper functions (tokenize, frontmatter, splitting, cosine similarity)
  - TextRetriever indexing from markdown files
  - TF-IDF vectorization and search accuracy
  - Save/load round-trip with gzip compact format
  - ensure_loaded() fallback chain
  - Category filtering
  - Search result formatting for LLM injection
  - Malformed / error-path file handling
  - Multi-part chunk splitting during indexing
  - build_index_cli() command-line interface
  - _vectorize_query() internal method
  - Integration with the real library (when available)
  - Halachic agent RAG integration
"""

import gzip
import json
import math
import os
import tempfile
import textwrap

import pytest
from unittest.mock import patch, MagicMock

from app.agents.rag import (
    TextChunk,
    SearchResult,
    TextRetriever,
    _tokenize,
    _parse_frontmatter,
    _split_long_text,
    _cosine_similarity,
    build_index_cli,
    DEFAULT_INDEX_PATH,
    DEFAULT_LIBRARY_PATH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TORAH_MD = textwrap.dedent("""\
    ---
    title: "Genesis"
    he_title: "בראשית"
    category: "Tanakh"
    subcategory: "Torah"
    source: "Sefaria.org"
    license: "CC-BY-NC"
    ---

    # Genesis
    ## בראשית

    ## Chapter 1

    **1:1** In the beginning God created the heavens and the earth.

    **1:2** And the earth was without form and void and darkness was upon the face of the deep.

    **1:3** And God said Let there be light and there was light.

    ## Chapter 2

    **2:1** Thus the heavens and the earth were finished and all the host of them.

    **2:2** And on the seventh day God ended his work which he had made and he rested on the seventh day.

    **2:3** And God blessed the seventh day and sanctified it because in it he had rested from all his work.
""")

SAMPLE_TALMUD_MD = textwrap.dedent("""\
    ---
    title: "Talmud Shabbat"
    he_title: "שבת"
    category: "Talmud"
    subcategory: "Seder Moed"
    source: "Sefaria.org"
    license: "CC-BY-NC"
    ---

    # Talmud Shabbat
    ## שבת

    ## Daf 73a

    The primary categories of labor prohibited on Shabbat are forty minus one.
    These correspond to the types of labor performed in building the Tabernacle.
    Sowing, plowing, reaping, binding sheaves, threshing, winnowing, selecting.

    ## Daf 73b

    One who performs two labors in one act of unawareness is liable for each one.
    Rabbi Eliezer says one is only liable once. The Sages disagree and hold each
    labor is a separate transgression requiring its own offering.
""")

SAMPLE_MISHNAH_MD = textwrap.dedent("""\
    ---
    title: "Pirkei Avot"
    he_title: "פרקי אבות"
    category: "Mishnah"
    subcategory: "Seder Nezikin"
    source: "Sefaria.org"
    license: "CC-BY-NC"
    ---

    # Pirkei Avot

    ## Chapter 1

    Moses received the Torah from Sinai and transmitted it to Joshua and Joshua
    to the Elders and the Elders to the Prophets and the Prophets transmitted it
    to the Men of the Great Assembly. They said three things: Be deliberate in
    judgment, raise many disciples, and make a fence around the Torah.
""")


@pytest.fixture
def mini_library(tmp_path):
    """Create a minimal library directory with test markdown files."""
    torah_dir = tmp_path / "torah"
    torah_dir.mkdir()
    (torah_dir / "Genesis.md").write_text(SAMPLE_TORAH_MD, encoding="utf-8")

    talmud_dir = tmp_path / "talmud"
    talmud_dir.mkdir()
    (talmud_dir / "Shabbat.md").write_text(SAMPLE_TALMUD_MD, encoding="utf-8")

    mishnah_dir = tmp_path / "mishnah"
    mishnah_dir.mkdir()
    (mishnah_dir / "Pirkei_Avot.md").write_text(SAMPLE_MISHNAH_MD, encoding="utf-8")

    # README.md should be skipped
    (tmp_path / "README.md").write_text("# Library\nThis is the README.", encoding="utf-8")

    return str(tmp_path)


@pytest.fixture
def indexed_retriever(mini_library):
    """Return a TextRetriever already indexed on the mini library."""
    r = TextRetriever()
    count = r.index(mini_library)
    assert count > 0
    return r


# ---------------------------------------------------------------------------
# TextChunk model tests
# ---------------------------------------------------------------------------

class TestTextChunk:
    """Test the TextChunk data model."""

    def test_context_label_with_section(self):
        chunk = TextChunk(text="hello", title="Genesis", section="Chapter 1")
        assert chunk.context_label == "Genesis > Chapter 1"

    def test_context_label_without_section(self):
        chunk = TextChunk(text="hello", title="Genesis")
        assert chunk.context_label == "Genesis"

    def test_to_dict_round_trip(self):
        original = TextChunk(
            text="some text",
            title="Title",
            he_title="כותרת",
            category="Tanakh",
            subcategory="Torah",
            section="Ch 1",
            language="he",
        )
        d = original.to_dict()
        restored = TextChunk.from_dict(d)
        assert restored.text == original.text
        assert restored.title == original.title
        assert restored.he_title == original.he_title
        assert restored.category == original.category
        assert restored.subcategory == original.subcategory
        assert restored.section == original.section
        assert restored.language == original.language

    def test_default_language_is_hebrew(self):
        chunk = TextChunk(text="text", title="t")
        assert chunk.language == "he"

    def test_default_fields(self):
        chunk = TextChunk(text="hello", title="T")
        assert chunk.he_title == ""
        assert chunk.category == ""
        assert chunk.subcategory == ""
        assert chunk.section == ""

    def test_to_dict_contains_all_keys(self):
        chunk = TextChunk(text="t", title="T")
        d = chunk.to_dict()
        assert set(d.keys()) == {"text", "title", "he_title", "category",
                                  "subcategory", "section", "language"}


class TestSearchResult:
    """Test the SearchResult data model."""

    def test_search_result_fields(self):
        chunk = TextChunk(text="hello", title="T", category="C")
        sr = SearchResult(chunk=chunk, score=0.75)
        assert sr.chunk is chunk
        assert sr.score == 0.75

    def test_search_result_score_zero(self):
        chunk = TextChunk(text="hello", title="T")
        sr = SearchResult(chunk=chunk, score=0.0)
        assert sr.score == 0.0


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestTokenize:
    """Test the _tokenize helper."""

    def test_basic_english(self):
        tokens = _tokenize("Hello world from the Torah")
        assert "hello" in tokens
        assert "world" in tokens
        assert "torah" in tokens
        # Stop words removed
        assert "the" not in tokens
        assert "from" not in tokens

    def test_hebrew_tokens(self):
        tokens = _tokenize("בראשית ברא אלהים")
        assert "בראשית" in tokens
        assert "ברא" in tokens
        assert "אלהים" in tokens

    def test_mixed_language(self):
        tokens = _tokenize("The Torah says בראשית ברא")
        assert "torah" in tokens
        assert "בראשית" in tokens
        # "the" and "says" are stop words or short
        assert "the" not in tokens

    def test_single_char_tokens_removed(self):
        tokens = _tokenize("I am a person")
        assert "i" not in tokens
        assert "a" not in tokens

    def test_empty_input(self):
        assert _tokenize("") == []

    def test_only_stop_words(self):
        assert _tokenize("the is a an") == []

    def test_numbers_preserved(self):
        tokens = _tokenize("Chapter 39 melachot prohibited")
        assert "39" in tokens
        assert "melachot" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! This is: a test.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens
        # Punctuation should not be in any token
        for t in tokens:
            assert "," not in t
            assert "!" not in t

    def test_case_insensitive(self):
        tokens = _tokenize("TORAH Torah torah")
        assert all(t == "torah" for t in tokens)


class TestParseFrontmatter:
    """Test YAML frontmatter parsing."""

    def test_valid_frontmatter(self):
        content = '---\ntitle: "Genesis"\ncategory: Tanakh\n---\nBody text'
        meta = _parse_frontmatter(content)
        assert meta["title"] == "Genesis"
        assert meta["category"] == "Tanakh"

    def test_no_frontmatter(self):
        assert _parse_frontmatter("Just plain text") == {}

    def test_quoted_values_stripped(self):
        content = "---\ntitle: 'Exodus'\nhe_title: \"שמות\"\n---\n"
        meta = _parse_frontmatter(content)
        assert meta["title"] == "Exodus"
        assert meta["he_title"] == "שמות"

    def test_colon_in_value(self):
        content = '---\ntitle: "Note: Important"\n---\n'
        meta = _parse_frontmatter(content)
        assert meta["title"] == "Note: Important"

    def test_empty_value(self):
        content = "---\ntitle:\n---\n"
        meta = _parse_frontmatter(content)
        assert meta["title"] == ""

    def test_multiple_fields(self):
        content = '---\ntitle: "A"\nhe_title: "B"\ncategory: C\nsubcategory: D\n---\n'
        meta = _parse_frontmatter(content)
        assert len(meta) == 4

    def test_line_without_colon_skipped(self):
        content = "---\ntitle: A\nmalformed line\ncategory: B\n---\n"
        meta = _parse_frontmatter(content)
        assert meta.get("title") == "A"
        assert meta.get("category") == "B"
        assert "malformed line" not in meta


class TestSplitLongText:
    """Test paragraph-based text splitting."""

    def test_short_text_not_split(self):
        text = "Short paragraph."
        result = _split_long_text(text, max_chars=100)
        assert result == [text]

    def test_long_text_splits_at_paragraph(self):
        para1 = "A" * 200
        para2 = "B" * 200
        para3 = "C" * 200
        text = f"{para1}\n\n{para2}\n\n{para3}"
        result = _split_long_text(text, max_chars=450)
        assert len(result) >= 2
        # Each chunk should contain complete paragraphs
        assert "A" * 200 in result[0]

    def test_single_giant_paragraph(self):
        text = "word " * 1000  # ~5000 chars
        result = _split_long_text(text, max_chars=3000)
        # Can't split within paragraph, so it stays as one chunk
        assert len(result) == 1

    def test_empty_text(self):
        result = _split_long_text("")
        assert result == [""]

    def test_exactly_at_limit(self):
        text = "x" * 3000
        result = _split_long_text(text, max_chars=3000)
        assert result == [text]

    def test_multiple_paragraphs_distribute_evenly(self):
        paras = [f"paragraph{i} " * 20 for i in range(6)]
        text = "\n\n".join(paras)
        result = _split_long_text(text, max_chars=500)
        assert len(result) >= 2
        # Each chunk should be a valid join of paragraphs
        for chunk in result:
            assert len(chunk) > 0


class TestCosineSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors(self):
        vec = {"a": 1.0, "b": 2.0, "c": 3.0}
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 1e-9

    def test_orthogonal_vectors(self):
        a = {"x": 1.0}
        b = {"y": 1.0}
        assert _cosine_similarity(a, b) == 0.0

    def test_known_value(self):
        a = {"x": 1.0, "y": 0.0}
        b = {"x": 1.0, "y": 1.0}
        expected = 1.0 / math.sqrt(2)
        assert abs(_cosine_similarity(a, b) - expected) < 1e-9

    def test_empty_vectors(self):
        assert _cosine_similarity({}, {"a": 1.0}) == 0.0
        assert _cosine_similarity({}, {}) == 0.0

    def test_zero_magnitude(self):
        assert _cosine_similarity({"a": 0.0}, {"a": 1.0}) == 0.0


# ---------------------------------------------------------------------------
# TextRetriever: indexing
# ---------------------------------------------------------------------------

class TestTextRetrieverIndexing:
    """Test markdown parsing and indexing."""

    def test_initial_state(self):
        r = TextRetriever()
        assert r.is_indexed is False
        assert r.chunks == []

    def test_index_mini_library(self, mini_library):
        r = TextRetriever()
        count = r.index(mini_library)
        assert count > 0
        assert r.is_indexed is True
        assert len(r.chunks) == count

    def test_index_nonexistent_path(self):
        r = TextRetriever()
        count = r.index("/nonexistent/path")
        assert count == 0
        assert r.is_indexed is False

    def test_readme_skipped(self, mini_library):
        r = TextRetriever()
        r.index(mini_library)
        titles = {c.title for c in r.chunks}
        assert "README" not in titles

    def test_frontmatter_extracted(self, mini_library):
        r = TextRetriever()
        r.index(mini_library)

        categories = {c.category for c in r.chunks}
        assert "Tanakh" in categories
        assert "Talmud" in categories
        assert "Mishnah" in categories

        # Check specific metadata
        genesis_chunks = [c for c in r.chunks if c.title == "Genesis"]
        assert len(genesis_chunks) > 0
        assert genesis_chunks[0].he_title == "בראשית"
        assert genesis_chunks[0].subcategory == "Torah"

    def test_sections_parsed(self, mini_library):
        r = TextRetriever()
        r.index(mini_library)

        sections = {c.section for c in r.chunks if c.title == "Genesis"}
        assert "Chapter 1" in sections
        assert "Chapter 2" in sections

    def test_short_sections_skipped(self, tmp_path):
        """Sections shorter than 20 chars are filtered out."""
        md = "---\ntitle: Test\ncategory: Test\n---\n\n## Short\n\nTiny.\n\n## Long\n\n" + "x" * 50
        (tmp_path / "test.md").write_text(md, encoding="utf-8")

        r = TextRetriever()
        r.index(str(tmp_path))

        sections = [c.section for c in r.chunks]
        assert "Long" in sections
        # "Short" section has <20 chars, should be skipped
        assert "Short" not in sections

    def test_tfidf_vectors_built(self, indexed_retriever):
        r = indexed_retriever
        assert len(r._idf) > 0
        assert len(r._chunk_vectors) == len(r.chunks)
        # Each vector should have at least one non-zero term
        for vec in r._chunk_vectors:
            assert len(vec) > 0

    def test_malformed_file_skipped_gracefully(self, tmp_path):
        """Files that raise exceptions during parse are skipped (L127-128)."""
        good_md = "---\ntitle: Good\ncategory: Test\n---\n\n## Section\n\n" + "valid content here " * 5
        (tmp_path / "good.md").write_text(good_md, encoding="utf-8")

        # Create a file that will cause _parse_file to fail:
        # Write binary garbage that looks like .md but isn't valid UTF-8
        bad_path = tmp_path / "bad.md"
        bad_path.write_bytes(b"---\ntitle: Bad\n---\n\x80\x81\x82\xff\xfe")

        r = TextRetriever()
        count = r.index(str(tmp_path))
        # Should index the good file and skip the bad one
        assert count > 0
        titles = {c.title for c in r.chunks}
        assert "Good" in titles

    def test_file_without_frontmatter_uses_filename(self, tmp_path):
        """Files without frontmatter should derive title from filename."""
        md = "## Section\n\n" + "content without frontmatter " * 5
        (tmp_path / "My_Book.md").write_text(md, encoding="utf-8")

        r = TextRetriever()
        r.index(str(tmp_path))
        if r.chunks:
            assert r.chunks[0].title == "My Book"

    def test_long_section_produces_multipart_labels(self, tmp_path):
        """Long sections that split produce '(part N)' labels (L337)."""
        # Create a section with enough text to force splitting
        long_content = "\n\n".join(["paragraph " * 100 for _ in range(10)])
        md = f"---\ntitle: Long\ncategory: Test\n---\n\n## BigSection\n\n{long_content}"
        (tmp_path / "long.md").write_text(md, encoding="utf-8")

        r = TextRetriever()
        r.index(str(tmp_path))

        # Find chunks from the BigSection
        big_chunks = [c for c in r.chunks if "BigSection" in c.section]
        assert len(big_chunks) > 1, "Section should split into multiple parts"
        # Check that parts are labeled correctly
        labels = [c.section for c in big_chunks]
        assert "BigSection (part 1)" in labels
        assert "BigSection (part 2)" in labels

    def test_index_empty_directory(self, tmp_path):
        """Indexing an empty directory returns 0 chunks."""
        r = TextRetriever()
        count = r.index(str(tmp_path))
        assert count == 0
        assert r.is_indexed is False

    def test_index_only_readme(self, tmp_path):
        """Directory with only README.md returns 0 chunks."""
        (tmp_path / "README.md").write_text("# Readme")
        r = TextRetriever()
        count = r.index(str(tmp_path))
        assert count == 0

    def test_non_md_files_skipped(self, tmp_path):
        """Non-.md files are ignored during indexing."""
        (tmp_path / "data.json").write_text('{"key": "value"}')
        (tmp_path / "notes.txt").write_text("Some notes")
        md = "---\ntitle: Real\ncategory: Test\n---\n\n## S\n\n" + "x" * 50
        (tmp_path / "real.md").write_text(md)

        r = TextRetriever()
        r.index(str(tmp_path))
        titles = {c.title for c in r.chunks}
        assert "Real" in titles
        assert len(titles) == 1


# ---------------------------------------------------------------------------
# TextRetriever: _vectorize_query
# ---------------------------------------------------------------------------

class TestVectorizeQuery:
    """Test the internal _vectorize_query method."""

    def test_vectorize_known_terms(self, indexed_retriever):
        """Query terms in the vocabulary produce non-zero vectors."""
        vec = indexed_retriever._vectorize_query("Shabbat labor")
        assert len(vec) > 0
        assert all(isinstance(v, float) for v in vec.values())

    def test_vectorize_unknown_terms(self, indexed_retriever):
        """Query terms not in vocabulary produce empty vector."""
        vec = indexed_retriever._vectorize_query("xylophone quasar")
        assert vec == {}

    def test_vectorize_empty_string(self, indexed_retriever):
        vec = indexed_retriever._vectorize_query("")
        assert vec == {}

    def test_vectorize_stop_words_only(self, indexed_retriever):
        vec = indexed_retriever._vectorize_query("the is a an")
        assert vec == {}


# ---------------------------------------------------------------------------
# TextRetriever: search
# ---------------------------------------------------------------------------

class TestTextRetrieverSearch:
    """Test search functionality."""

    def test_search_returns_results(self, indexed_retriever):
        results = indexed_retriever.search("Shabbat labor prohibited")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_scores_descending(self, indexed_retriever):
        results = indexed_retriever.search("Shabbat", top_k=10)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_search_relevance_shabbat(self, indexed_retriever):
        """Shabbat query should rank Talmud Shabbat chunks higher than Genesis."""
        results = indexed_retriever.search("Shabbat labor prohibited categories", top_k=5)
        assert len(results) > 0
        top = results[0]
        assert top.chunk.title == "Talmud Shabbat"

    def test_search_relevance_creation(self, indexed_retriever):
        """Creation query should rank Genesis higher."""
        results = indexed_retriever.search("God created heavens earth beginning", top_k=5)
        assert len(results) > 0
        top = results[0]
        assert top.chunk.title == "Genesis"

    def test_search_relevance_torah_transmission(self, indexed_retriever):
        """Torah transmission query should match Pirkei Avot."""
        results = indexed_retriever.search("Moses received Torah Sinai transmitted", top_k=5)
        assert len(results) > 0
        top = results[0]
        assert top.chunk.title == "Pirkei Avot"

    def test_search_top_k_limits(self, indexed_retriever):
        results = indexed_retriever.search("God", top_k=2)
        assert len(results) <= 2

    def test_search_empty_query(self, indexed_retriever):
        results = indexed_retriever.search("")
        assert results == []

    def test_search_stopwords_only(self, indexed_retriever):
        results = indexed_retriever.search("the is a an")
        assert results == []

    def test_search_not_indexed(self):
        r = TextRetriever()
        results = r.search("anything")
        assert results == []

    def test_search_category_filter(self, indexed_retriever):
        results = indexed_retriever.search("God", category="Tanakh")
        assert all(r.chunk.category == "Tanakh" for r in results)

    def test_search_category_filter_case_insensitive(self, indexed_retriever):
        results = indexed_retriever.search("God", category="tanakh")
        assert all(r.chunk.category == "Tanakh" for r in results)

    def test_search_category_no_match(self, indexed_retriever):
        results = indexed_retriever.search("God", category="Nonexistent")
        assert results == []


class TestSearchFormatted:
    """Test search_formatted output for LLM injection."""

    def test_formatted_output_structure(self, indexed_retriever):
        output = indexed_retriever.search_formatted("Shabbat", top_k=2)
        assert output != ""
        assert "[Source 1:" in output
        # Should include category
        assert "Talmud" in output or "Tanakh" in output

    def test_formatted_empty_on_no_results(self, indexed_retriever):
        output = indexed_retriever.search_formatted("")
        assert output == ""

    def test_formatted_not_indexed(self):
        r = TextRetriever()
        assert r.search_formatted("anything") == ""

    def test_formatted_respects_top_k(self, indexed_retriever):
        output = indexed_retriever.search_formatted("God", top_k=1)
        assert "[Source 1:" in output
        assert "[Source 2:" not in output

    def test_formatted_includes_context_label(self, indexed_retriever):
        output = indexed_retriever.search_formatted("Shabbat labor prohibited", top_k=1)
        # Should include "Source N: <title> > <section> (<category>)"
        assert "Talmud Shabbat" in output
        assert "Daf 73a" in output or "Daf 73b" in output

    def test_formatted_truncates_long_text(self):
        """Chunks with text >1500 chars are truncated with '...'."""
        r = TextRetriever()
        r.chunks = [
            TextChunk(text="x" * 2000, title="T", category="C", section="S"),
        ]
        r._idf = {"xx": 1.0}
        r._chunk_vectors = [{"xx": 0.5}]
        r._indexed = True

        output = r.search_formatted("xx", top_k=1)
        assert "..." in output

    def test_formatted_category_filter(self, indexed_retriever):
        output = indexed_retriever.search_formatted("Shabbat", top_k=5, category="Talmud")
        assert output != ""
        # All sources should be Talmud
        assert "(Talmud)" in output


# ---------------------------------------------------------------------------
# build_index_cli
# ---------------------------------------------------------------------------

class TestBuildIndexCli:
    """Test the build_index_cli() command-line entry point."""

    def test_cli_success(self, mini_library, tmp_path):
        """CLI builds and saves index successfully."""
        output_path = str(tmp_path / "cli_index.json.gz")
        with patch("sys.argv", ["rag", "--library", mini_library, "--output", output_path]):
            build_index_cli()
        assert os.path.isfile(output_path)

        # Verify the saved index is loadable
        r = TextRetriever()
        count = r.load(output_path)
        assert count > 0

    def test_cli_empty_library_exits(self, tmp_path):
        """CLI exits with error when no chunks are indexed."""
        empty_lib = str(tmp_path / "empty_lib")
        os.makedirs(empty_lib)
        output_path = str(tmp_path / "output.json.gz")

        with patch("sys.argv", ["rag", "--library", empty_lib, "--output", output_path]):
            with pytest.raises(SystemExit) as exc_info:
                build_index_cli()
            assert exc_info.value.code == 1

    def test_cli_nonexistent_library(self, tmp_path):
        """CLI handles nonexistent library path."""
        output_path = str(tmp_path / "output.json.gz")
        with patch("sys.argv", ["rag", "--library", "/nonexistent", "--output", output_path]):
            with pytest.raises(SystemExit) as exc_info:
                build_index_cli()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TextRetriever: save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip:
    """Test that save → load preserves search functionality."""

    def test_save_creates_gzipped_file(self, indexed_retriever, tmp_path):
        path = str(tmp_path / "test_index.json.gz")
        indexed_retriever.save(path)
        assert os.path.isfile(path)
        # Verify it's actually gzip
        with gzip.open(path, "rt") as f:
            data = json.load(f)
        assert data["v"] == 2
        assert "vocab" in data
        assert "chunks" in data
        assert "vectors" in data
        assert "idf" in data

    def test_save_uses_compact_format(self, indexed_retriever, tmp_path):
        path = str(tmp_path / "test_index.json.gz")
        indexed_retriever.save(path)
        with gzip.open(path, "rt") as f:
            data = json.load(f)
        # Vectors should be [[ids], [weights]] not {term: weight}
        for vec in data["vectors"]:
            assert isinstance(vec, list)
            assert len(vec) == 2
            ids, weights = vec
            assert isinstance(ids, list)
            assert isinstance(weights, list)
            assert len(ids) == len(weights)

    def test_save_truncates_text(self, indexed_retriever, tmp_path):
        # Add a chunk with very long text
        long_chunk = TextChunk(
            text="x" * 5000, title="Long", category="Test", section="S1"
        )
        indexed_retriever.chunks.append(long_chunk)
        indexed_retriever._chunk_vectors.append({})

        path = str(tmp_path / "test_index.json.gz")
        indexed_retriever.save(path)
        with gzip.open(path, "rt") as f:
            data = json.load(f)
        # Last chunk should have truncated text
        last = data["chunks"][-1]
        assert len(last["text"]) <= 1500

    def test_load_restores_chunks(self, indexed_retriever, tmp_path):
        path = str(tmp_path / "test_index.json.gz")
        indexed_retriever.save(path)

        loaded = TextRetriever()
        count = loaded.load(path)
        assert count == len(indexed_retriever.chunks)
        assert loaded.is_indexed is True

        # Verify chunk metadata preserved
        for orig, rest in zip(indexed_retriever.chunks, loaded.chunks):
            assert rest.title == orig.title
            assert rest.category == orig.category
            assert rest.he_title == orig.he_title

    def test_load_nonexistent_file(self):
        r = TextRetriever()
        count = r.load("/nonexistent/file.json.gz")
        assert count == 0
        assert r.is_indexed is False

    def test_search_after_load_matches(self, indexed_retriever, tmp_path):
        """Verify search results are equivalent after save/load round-trip."""
        path = str(tmp_path / "test_index.json.gz")
        indexed_retriever.save(path)

        loaded = TextRetriever()
        loaded.load(path)

        queries = [
            "Shabbat labor prohibited",
            "God created heavens earth",
            "Moses Torah Sinai",
        ]
        for query in queries:
            orig_results = indexed_retriever.search(query, top_k=3)
            loaded_results = loaded.search(query, top_k=3)

            # Same number of results
            assert len(orig_results) == len(loaded_results), f"Mismatch for: {query}"

            # Same chunks returned (order and title should match)
            for o, l in zip(orig_results, loaded_results):
                assert o.chunk.title == l.chunk.title
                assert o.chunk.section == l.chunk.section
                # Scores may differ slightly due to float rounding in save
                assert abs(o.score - l.score) < 0.05, (
                    f"Score divergence for {query}: {o.score} vs {l.score}"
                )

    def test_save_returns_path(self, indexed_retriever, tmp_path):
        path = str(tmp_path / "test_index.json.gz")
        returned = indexed_retriever.save(path)
        assert returned == path

    def test_save_default_path(self, indexed_retriever):
        """save() with no arg uses DEFAULT_INDEX_PATH."""
        with patch("gzip.open", MagicMock()):
            with patch("os.path.getsize", return_value=1024):
                result = indexed_retriever.save()
                assert result == DEFAULT_INDEX_PATH

    def test_load_legacy_format(self, tmp_path):
        """Test that load still supports legacy (v1 / dict-based) format."""
        chunks = [
            {"text": "Hello world test text here.", "title": "T1",
             "he_title": "", "category": "Cat", "subcategory": "",
             "section": "S1", "language": "en"}
        ]
        idf = {"hello": 1.0, "world": 0.5, "test": 0.8, "text": 0.7, "here": 0.6}
        vectors = [{"hello": 0.5, "world": 0.3, "test": 0.4}]

        path = str(tmp_path / "legacy.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"chunks": chunks, "idf": idf, "vectors": vectors}, f)

        r = TextRetriever()
        count = r.load(path)
        assert count == 1
        assert r.is_indexed
        assert r._idf == idf
        assert r._chunk_vectors == vectors


# ---------------------------------------------------------------------------
# TextRetriever: ensure_loaded fallback chain
# ---------------------------------------------------------------------------

class TestEnsureLoaded:
    """Test the ensure_loaded fallback chain."""

    def test_already_indexed_is_noop(self, indexed_retriever):
        original_count = len(indexed_retriever.chunks)
        count = indexed_retriever.ensure_loaded()
        assert count == original_count

    def test_loads_from_prebuilt_index(self, indexed_retriever, tmp_path):
        # Save an index
        index_path = str(tmp_path / "index.json.gz")
        indexed_retriever.save(index_path)

        # Fresh retriever should load from file
        r = TextRetriever()
        count = r.ensure_loaded(index_path=index_path)
        assert count > 0
        assert r.is_indexed

    def test_falls_back_to_library(self, mini_library, tmp_path):
        """When no pre-built index, falls back to building from library."""
        index_path = str(tmp_path / "nonexistent_index.json.gz")
        r = TextRetriever()
        count = r.ensure_loaded(index_path=index_path, library_path=mini_library)
        assert count > 0
        assert r.is_indexed
        # Should have saved the index for next time
        assert os.path.isfile(index_path)

    def test_returns_zero_when_nothing_available(self, tmp_path):
        r = TextRetriever()
        count = r.ensure_loaded(
            index_path=str(tmp_path / "nope.json.gz"),
            library_path=str(tmp_path / "no_library"),
        )
        assert count == 0
        assert r.is_indexed is False

    def test_save_failure_on_readonly_fs(self, mini_library, tmp_path):
        """ensure_loaded should still work even if save fails."""
        index_path = "/nonexistent_dir/index.json.gz"
        r = TextRetriever()
        count = r.ensure_loaded(index_path=index_path, library_path=mini_library)
        # Should have indexed from library even though save failed
        assert count > 0
        assert r.is_indexed


# ---------------------------------------------------------------------------
# Integration: real pre-built index
# ---------------------------------------------------------------------------

class TestPrebuiltIndex:
    """Integration tests using the actual pre-built rag_index.json.gz."""

    @pytest.fixture
    def real_retriever(self):
        """Load the actual pre-built index if available."""
        if not os.path.isfile(DEFAULT_INDEX_PATH):
            pytest.skip("Pre-built RAG index not available")
        r = TextRetriever()
        count = r.load(DEFAULT_INDEX_PATH)
        assert count > 0
        return r

    def test_loads_substantial_chunk_count(self, real_retriever):
        assert len(real_retriever.chunks) > 10000

    def test_has_diverse_categories(self, real_retriever):
        categories = {c.category for c in real_retriever.chunks}
        assert "Tanakh" in categories
        assert "Talmud" in categories
        assert "Mishnah" in categories

    def test_search_shabbat_returns_relevant(self, real_retriever):
        results = real_retriever.search("Shabbat observance laws", top_k=5)
        assert len(results) >= 3
        # At least one result should mention Shabbat-related content
        texts = " ".join(r.chunk.text for r in results).lower()
        assert "shabbat" in texts or "שבת" in texts

    def test_search_kashrut(self, real_retriever):
        results = real_retriever.search("kashrut dietary laws kosher", top_k=5)
        assert len(results) > 0

    def test_search_hebrew_query(self, real_retriever):
        results = real_retriever.search("בראשית ברא אלהים", top_k=5)
        assert len(results) > 0

    def test_category_filter_talmud(self, real_retriever):
        results = real_retriever.search("Shabbat", top_k=5, category="Talmud")
        assert len(results) > 0
        assert all(r.chunk.category == "Talmud" for r in results)

    def test_formatted_output_for_llm(self, real_retriever):
        output = real_retriever.search_formatted("prayer Shema", top_k=3)
        assert output != ""
        assert "[Source 1:" in output
        assert "[Source 2:" in output


# ---------------------------------------------------------------------------
# Integration: orchestrator ensure_rag
# ---------------------------------------------------------------------------

class TestOrchestratorRAG:
    """Test orchestrator RAG integration."""

    def test_ensure_rag_loads_index(self):
        """Orchestrator.ensure_rag() should load the pre-built index."""
        if not os.path.isfile(DEFAULT_INDEX_PATH):
            pytest.skip("Pre-built RAG index not available")

        with patch('app.agents.orchestrator.OpenAI'):
            from app.agents.orchestrator import RabbiOrchestrator
            orchestrator = RabbiOrchestrator(api_key="test-key")
            count = orchestrator.ensure_rag()
            assert count > 0
            assert orchestrator.retriever.is_indexed

    def test_halachic_agent_has_retriever(self):
        """Halachic agent should have the retriever reference."""
        with patch('app.agents.orchestrator.OpenAI'):
            from app.agents.orchestrator import RabbiOrchestrator
            orchestrator = RabbiOrchestrator(api_key="test-key")
            assert orchestrator.halachic_agent.retriever is orchestrator.retriever


# ---------------------------------------------------------------------------
# Integration: halachic agent uses RAG
# ---------------------------------------------------------------------------

class TestHalachicRAGIntegration:
    """Test that the halachic agent correctly uses the RAG retriever."""

    @pytest.mark.asyncio
    async def test_halachic_agent_injects_sources(
        self, mock_anthropic_client, mock_claude_response
    ):
        """When retriever is indexed, sources appear in the LLM prompt."""
        from app.agents.halachic import HalachicReasoningAgent
        from app.agents.base import AgentContext

        # Create a small retriever with test data
        retriever = TextRetriever()
        retriever.chunks = [
            TextChunk(
                text="The Talmud in Shabbat 73a lists 39 categories of labor.",
                title="Talmud Shabbat", category="Talmud", section="Daf 73a",
            ),
        ]
        retriever._idf = {"talmud": 1.0, "shabbat": 1.0, "73a": 1.5,
                          "lists": 0.5, "39": 1.2, "categories": 0.8,
                          "labor": 0.9}
        retriever._chunk_vectors = [
            {"talmud": 0.14, "shabbat": 0.14, "73a": 0.21,
             "lists": 0.07, "39": 0.17, "categories": 0.11, "labor": 0.13}
        ]
        retriever._indexed = True

        agent = HalachicReasoningAgent(
            mock_anthropic_client, retriever=retriever
        )

        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "Answer",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": ["Shabbat 73a"],
            })
        )

        context = AgentContext(user_message="What are the 39 melachot of Shabbat?")
        await agent.process(context)

        # Verify the LLM was called with RAG sources in the prompt
        call_args = mock_anthropic_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        # messages[0] is system prompt, messages[1] is user message
        user_msg = messages[1]["content"]
        assert "RELEVANT SOURCE TEXTS FROM LIBRARY" in user_msg
        assert "Talmud Shabbat" in user_msg

    @pytest.mark.asyncio
    async def test_halachic_agent_works_without_retriever(
        self, mock_anthropic_client, mock_claude_response
    ):
        """Agent works fine when no retriever is provided."""
        from app.agents.halachic import HalachicReasoningAgent
        from app.agents.base import AgentContext

        agent = HalachicReasoningAgent(mock_anthropic_client)

        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "Answer without sources",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="Question")
        result = await agent.process(context)
        assert result.halachic_landscape is not None

    @pytest.mark.asyncio
    async def test_halachic_agent_calls_ensure_loaded(
        self, mock_anthropic_client, mock_claude_response
    ):
        """Agent should call ensure_loaded before searching."""
        from app.agents.halachic import HalachicReasoningAgent
        from app.agents.base import AgentContext

        retriever = TextRetriever()
        agent = HalachicReasoningAgent(
            mock_anthropic_client, retriever=retriever
        )

        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "Answer",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        with patch.object(retriever, 'ensure_loaded', return_value=0) as mock_ensure:
            context = AgentContext(user_message="Question about Shabbat?")
            await agent.process(context)
            mock_ensure.assert_called_once()
