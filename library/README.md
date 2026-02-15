# Jewish Texts Library for RAG

This library contains public domain Jewish texts from [Sefaria.org](https://www.sefaria.org), formatted as markdown files optimized for Retrieval Augmented Generation (RAG).

## Contents

| Category | Directory | Files | Description |
|----------|-----------|-------|-------------|
| Torah | `torah/` | 5 books (Hebrew + English) | Five Books of Moses |
| Nevi'im | `neviim/` | 21 books (Hebrew + English) | Prophets |
| Ketuvim | `ketuvim/` | 13 books (Hebrew + English) | Writings |
| Talmud Bavli | `talmud/` | 36 tractates (Hebrew + English for key tractates) | Babylonian Talmud |
| Mishnah | `mishnah/` | 62 tractates | Complete Mishnah |
| Midrash | `midrash/` | 17 collections | Midrash Rabbah, Tanchuma, etc. |
| Siddur | `siddur/` | 3 texts | Siddur Ashkenaz, Sefard, Pesach Haggadah |
| Other | `other/` | 15+ texts | Shulchan Arukh, Rambam, Mussar, Philosophy |

## File Format

Each file follows a consistent structure optimized for chunking and retrieval:

```markdown
---
title: "Book Name"
he_title: "שם הספר"
category: "Category"
subcategory: "Subcategory"
language: "en" (if English translation)
source: "Sefaria.org"
license: "CC-BY-NC"
---

# Book Name

## Chapter N

**N:1** Verse text...

**N:2** Verse text...
```

### YAML Frontmatter
Each file includes metadata in YAML frontmatter for filtering and categorization during retrieval.

### Naming Convention
- Hebrew originals: `BookName.md` (e.g., `Genesis.md`)
- English translations: `BookName_en.md` (e.g., `Genesis_en.md`)
- Talmud: `Talmud_TractName.md` / `Talmud_TractName_en.md`
- Mishnah: `Mishnah_TractName.md`

## RAG Usage

### Chunking Strategy
These files are structured to support multiple chunking approaches:

1. **By chapter/section**: Split on `## Chapter` or `## Daf` headers
2. **By verse**: Split on `**N:N**` patterns
3. **By fixed token count**: The consistent formatting ensures clean splits

### Metadata Extraction
The YAML frontmatter provides structured metadata for each document:
- `title` / `he_title`: For attribution in responses
- `category` / `subcategory`: For filtering relevant sources
- `source`: For citation

### Recommended Embedding Approach
1. Parse each file extracting frontmatter metadata
2. Split into chunks at chapter/section boundaries
3. For each chunk, prepend context: `{title} > {section_header}`
4. Embed with metadata tags for category-based filtering

## Scripts

- `download_texts.py` - Downloads Hebrew originals from Sefaria API
- `download_english.py` - Downloads English translations
- `download_complex.py` - Handles texts with complex schemas (Siddur, etc.)

### Re-downloading
```bash
# Download everything
python3 download_texts.py all

# Download a specific section
python3 download_texts.py torah
python3 download_texts.py talmud

# Download English translations
python3 download_english.py tanakh
python3 download_english.py talmud
```

## License

Texts are sourced from Sefaria.org under CC-BY-NC license.
The William Davidson Talmud translation is available under CC-BY-NC.
