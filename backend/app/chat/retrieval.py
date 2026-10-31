"""Source retrieval for v2: multi-query search over the pre-built library index.

Reuses the v1 ``TextRetriever`` index (no new infrastructure). The
classifier supplies a few search keywords (Hebrew/English/transliterated),
which are searched alongside the raw message; results are de-duplicated and
capped. The search is CPU-bound, so it runs in a worker thread and never
blocks the event loop.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from ..agents.rag import TextRetriever

MAX_PASSAGES = 5
MAX_PASSAGE_CHARS = 1400
MIN_SCORE = 0.08

_retriever: Optional[TextRetriever] = None


def get_retriever() -> TextRetriever:
    global _retriever
    if _retriever is None:
        _retriever = TextRetriever()
    return _retriever


def set_retriever(r) -> None:
    global _retriever
    _retriever = r


@dataclass
class Passage:
    n: int
    title: str
    ref: str
    text: str
    category: str
    url: str

    def search_result_block(self) -> dict:
        return {
            "type": "search_result",
            "source": self.url,
            "title": f"{self.title}, {self.ref}" if self.ref else self.title,
            "content": [{"type": "text", "text": self.text}],
            "citations": {"enabled": True},
        }

    def to_source(self) -> dict:
        return {
            "n": self.n, "title": self.title, "ref": self.ref, "url": self.url,
            "excerpt": self.text[:400], "category": self.category, "kind": "library", "verified": True,
        }


_DAF = re.compile(r"Daf (\d+[ab])", re.I)
_PART = re.compile(r"\(part \d+\)")


def sefaria_url(title: str, section: str) -> str:
    m = _DAF.search(section or "")
    if title.startswith("Talmud ") and m:
        tractate = title.removeprefix("Talmud ").strip().replace(" ", "_")
        return f"https://www.sefaria.org/{quote(tractate)}.{m.group(1)}"
    section_clean = _PART.sub("", section or "")
    q = f"{title} {section_clean}".strip()
    return f"https://www.sefaria.org/search?q={quote(q)}"


def _search_sync(queries: list[str], top_k: int) -> list:
    retriever = get_retriever()
    retriever.ensure_loaded()
    seen: dict[tuple, object] = {}
    for q in queries:
        if not q.strip():
            continue
        for res in retriever.search(q, top_k=top_k):
            key = (res.chunk.title, res.chunk.section)
            if res.score < MIN_SCORE:
                continue
            if key not in seen or seen[key].score < res.score:
                seen[key] = res
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)[:MAX_PASSAGES]


async def retrieve(message: str, keywords: Optional[list[str]] = None) -> list[Passage]:
    queries = [message[:500]] + [k for k in (keywords or []) if k]
    results = await asyncio.to_thread(_search_sync, queries, 4)
    passages = []
    for i, res in enumerate(results, 1):
        c = res.chunk
        text = c.text if len(c.text) <= MAX_PASSAGE_CHARS else c.text[:MAX_PASSAGE_CHARS].rsplit(" ", 1)[0] + " …"
        passages.append(Passage(n=i, title=c.title, ref=c.section, text=text, category=c.category,
                                url=sefaria_url(c.title, c.section)))
    return passages
