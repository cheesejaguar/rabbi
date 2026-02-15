#!/usr/bin/env python3
"""
Download Jewish texts from Sefaria API and format as markdown for RAG.

Sefaria API docs: https://developers.sefaria.org/
All texts from Sefaria are available under open licenses.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://www.sefaria.org/api/v3/texts/"
LIBRARY_DIR = os.path.dirname(os.path.abspath(__file__))

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between requests
MAX_RETRIES = 4


def sanitize_filename(name):
    """Convert a text name to a safe filename."""
    name = name.replace(" ", "_")
    name = re.sub(r'[^\w\-]', '', name)
    return name


def fetch_text(ref, retries=MAX_RETRIES):
    """Fetch a text from Sefaria API v3."""
    encoded_ref = urllib.parse.quote(ref)
    url = f"{BASE_URL}{encoded_ref}?version=primary&language=en"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'RebbeDev-Library/1.0')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                time.sleep(REQUEST_DELAY)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 404:
                print(f"  Not found: {ref}")
                return None
            else:
                print(f"  HTTP error {e.code} for {ref}, attempt {attempt + 1}")
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error fetching {ref}: {e}, attempt {attempt + 1}")
            time.sleep(2 ** attempt)

    print(f"  Failed to fetch {ref} after {retries} attempts")
    return None


def extract_text_content(data, language='en'):
    """Extract text content from Sefaria API v3 response."""
    versions = data.get('versions', [])

    for version in versions:
        if version.get('language') == language:
            return version.get('text', None)

    # Fallback: try any version
    if versions:
        return versions[0].get('text', None)

    return None


def flatten_text(text, depth=0):
    """Recursively flatten nested text arrays into verse strings with numbering."""
    results = []
    if isinstance(text, str):
        # Strip HTML tags
        clean = re.sub(r'<[^>]+>', '', text)
        return [clean] if clean.strip() else []
    elif isinstance(text, list):
        for item in text:
            results.extend(flatten_text(item, depth + 1))
    return results


def text_to_numbered_verses(text):
    """Convert text array to numbered verses."""
    flat = flatten_text(text)
    return flat


def format_book_as_markdown(title, category, subcategory, chapters_data, he_title=""):
    """Format a book as RAG-optimized markdown."""
    lines = []

    # YAML frontmatter for metadata
    lines.append("---")
    lines.append(f"title: \"{title}\"")
    if he_title:
        lines.append(f"he_title: \"{he_title}\"")
    lines.append(f"category: \"{category}\"")
    lines.append(f"subcategory: \"{subcategory}\"")
    lines.append(f"source: \"Sefaria.org\"")
    lines.append(f"license: \"CC-BY-NC\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    if he_title:
        lines.append(f"## {he_title}")
    lines.append("")

    for chapter_num, chapter_data in chapters_data:
        lines.append(f"## Chapter {chapter_num}")
        lines.append("")

        if isinstance(chapter_data, dict):
            # Has both Hebrew and English
            en_text = chapter_data.get('en', [])
            he_text = chapter_data.get('he', [])

            en_verses = text_to_numbered_verses(en_text) if en_text else []

            for i, verse in enumerate(en_verses, 1):
                if verse.strip():
                    lines.append(f"**{chapter_num}:{i}** {verse}")
                    lines.append("")
        elif isinstance(chapter_data, list):
            verses = text_to_numbered_verses(chapter_data)
            for i, verse in enumerate(verses, 1):
                if verse.strip():
                    lines.append(f"**{chapter_num}:{i}** {verse}")
                    lines.append("")

        lines.append("")

    return "\n".join(lines)


def download_biblical_book(ref, category, subcategory, output_dir):
    """Download a biblical book chapter by chapter."""
    print(f"Downloading {ref}...")

    # First get the book index to find chapter count
    index_url = f"https://www.sefaria.org/api/index/{urllib.parse.quote(ref)}"
    try:
        req = urllib.request.Request(index_url)
        req.add_header('User-Agent', 'RebbeDev-Library/1.0')
        with urllib.request.urlopen(req, timeout=30) as response:
            index_data = json.loads(response.read().decode('utf-8'))
        time.sleep(REQUEST_DELAY)
    except Exception as e:
        print(f"  Error fetching index for {ref}: {e}")
        return False

    # Get Hebrew title
    he_title = index_data.get('heTitle', '')

    # Get chapter structure
    schema = index_data.get('schema', {})
    lengths = schema.get('lengths', [])

    if not lengths:
        # Try alternate structure
        alt = index_data.get('alt_structs', {})
        lengths_key = index_data.get('lengths', [])
        if lengths_key:
            lengths = lengths_key

    num_chapters = lengths[0] if lengths else 50  # Default guess

    chapters_data = []

    for ch in range(1, num_chapters + 1):
        ch_ref = f"{ref} {ch}"
        data = fetch_text(ch_ref)
        if data is None:
            if ch > 1:  # We got at least one chapter
                break
            continue

        en_text = extract_text_content(data, 'en')
        if en_text:
            chapters_data.append((ch, en_text))
        else:
            # Try to get Hebrew at least
            he_text = extract_text_content(data, 'he')
            if he_text:
                chapters_data.append((ch, he_text))

    if not chapters_data:
        print(f"  No content found for {ref}")
        return False

    # Format and write
    md_content = format_book_as_markdown(ref, category, subcategory, chapters_data, he_title)
    filename = sanitize_filename(ref) + ".md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md_content)

    print(f"  Saved {filepath} ({len(chapters_data)} chapters)")
    return True


def download_talmud_tractate(tractate, output_dir):
    """Download a Talmud tractate page by page."""
    print(f"Downloading Talmud {tractate}...")

    # Talmud pages use daf notation: 2a, 2b, 3a, 3b, ...
    # First get index for page count
    index_url = f"https://www.sefaria.org/api/index/{urllib.parse.quote(tractate)}"
    try:
        req = urllib.request.Request(index_url)
        req.add_header('User-Agent', 'RebbeDev-Library/1.0')
        with urllib.request.urlopen(req, timeout=30) as response:
            index_data = json.loads(response.read().decode('utf-8'))
        time.sleep(REQUEST_DELAY)
    except Exception as e:
        print(f"  Error fetching index for {tractate}: {e}")
        return False

    he_title = index_data.get('heTitle', '')
    schema = index_data.get('schema', {})
    lengths = schema.get('lengths', [])
    num_pages = lengths[0] if lengths else 100

    pages_data = []
    consecutive_failures = 0

    for page_num in range(2, num_pages + 2):  # Talmud starts at daf 2
        for side in ['a', 'b']:
            daf = f"{page_num}{side}"
            page_ref = f"{tractate}.{daf}"
            data = fetch_text(page_ref)

            if data is None:
                consecutive_failures += 1
                if consecutive_failures > 4:
                    break
                continue

            consecutive_failures = 0
            en_text = extract_text_content(data, 'en')
            if en_text:
                flat = flatten_text(en_text)
                if flat:
                    pages_data.append((daf, flat))

        if consecutive_failures > 4:
            break

    if not pages_data:
        print(f"  No content found for {tractate}")
        return False

    # Format as markdown
    lines = []
    lines.append("---")
    lines.append(f"title: \"Talmud {tractate}\"")
    if he_title:
        lines.append(f"he_title: \"{he_title}\"")
    lines.append(f"category: \"Talmud\"")
    lines.append(f"subcategory: \"Bavli\"")
    lines.append(f"source: \"Sefaria.org\"")
    lines.append(f"license: \"CC-BY-NC\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# Talmud Bavli: {tractate}")
    if he_title:
        lines.append(f"## {he_title}")
    lines.append("")

    for daf, segments in pages_data:
        lines.append(f"## Daf {daf}")
        lines.append("")
        for i, seg in enumerate(segments, 1):
            if seg.strip():
                lines.append(f"{seg}")
                lines.append("")
        lines.append("")

    filename = f"Talmud_{sanitize_filename(tractate)}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"  Saved {filepath} ({len(pages_data)} pages)")
    return True


def download_mishnah_tractate(tractate, output_dir):
    """Download a Mishnah tractate."""
    ref = f"Mishnah {tractate}"
    return download_biblical_book(ref, "Mishnah", "Seder", output_dir)


def download_simple_text(ref, category, subcategory, output_dir, filename_override=None):
    """Download a text that may be a single section."""
    print(f"Downloading {ref}...")

    data = fetch_text(ref)
    if data is None:
        # Try chapter-by-chapter approach
        return download_biblical_book(ref, category, subcategory, output_dir)

    en_text = extract_text_content(data, 'en')
    he_title = data.get('heRef', '')

    if en_text:
        flat = flatten_text(en_text)
        if flat:
            lines = []
            lines.append("---")
            lines.append(f"title: \"{ref}\"")
            if he_title:
                lines.append(f"he_title: \"{he_title}\"")
            lines.append(f"category: \"{category}\"")
            lines.append(f"subcategory: \"{subcategory}\"")
            lines.append(f"source: \"Sefaria.org\"")
            lines.append(f"license: \"CC-BY-NC\"")
            lines.append("---")
            lines.append("")
            lines.append(f"# {ref}")
            lines.append("")

            for i, verse in enumerate(flat, 1):
                if verse.strip():
                    lines.append(f"**{i}.** {verse}")
                    lines.append("")

            fname = filename_override or (sanitize_filename(ref) + ".md")
            filepath = os.path.join(output_dir, fname)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

            print(f"  Saved {filepath}")
            return True

    # Fallback to chapter approach
    return download_biblical_book(ref, category, subcategory, output_dir)


# ============================================================
# TEXT DEFINITIONS
# ============================================================

TORAH_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"
]

NEVIIM_BOOKS = [
    "Joshua", "Judges",
    "I Samuel", "II Samuel",
    "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum",
    "Habakkuk", "Zephaniah", "Haggai",
    "Zechariah", "Malachi"
]

KETUVIM_BOOKS = [
    "Psalms", "Proverbs", "Job",
    "Song of Songs", "Ruth", "Lamentations",
    "Ecclesiastes", "Esther", "Daniel",
    "Ezra", "Nehemiah",
    "I Chronicles", "II Chronicles"
]

TALMUD_TRACTATES = [
    # Seder Zeraim
    "Berakhot",
    # Seder Moed
    "Shabbat", "Eruvin", "Pesachim", "Rosh Hashanah",
    "Yoma", "Sukkah", "Beitzah", "Taanit",
    "Megillah", "Moed Katan", "Chagigah",
    # Seder Nashim
    "Yevamot", "Ketubot", "Nedarim", "Nazir",
    "Sotah", "Gittin", "Kiddushin",
    # Seder Nezikin
    "Bava Kamma", "Bava Metzia", "Bava Batra",
    "Sanhedrin", "Makkot", "Shevuot", "Avodah Zarah",
    "Horayot",
    # Seder Kodashim
    "Zevachim", "Menachot", "Chullin", "Bekhorot",
    "Arakhin", "Temurah", "Keritot", "Meilah",
    "Tamid",
    # Seder Tahorot
    "Niddah"
]

MISHNAH_TRACTATES = [
    # Seder Zeraim
    "Berakhot", "Peah", "Demai", "Kilayim", "Sheviit",
    "Terumot", "Maasrot", "Maaser Sheni", "Challah", "Orlah", "Bikkurim",
    # Seder Moed
    "Shabbat", "Eruvin", "Pesachim", "Shekalim", "Yoma",
    "Sukkah", "Beitzah", "Rosh Hashanah", "Taanit", "Megillah",
    "Moed Katan", "Chagigah",
    # Seder Nashim
    "Yevamot", "Ketubot", "Nedarim", "Nazir", "Sotah",
    "Gittin", "Kiddushin",
    # Seder Nezikin
    "Bava Kamma", "Bava Metzia", "Bava Batra", "Sanhedrin",
    "Makkot", "Shevuot", "Eduyot", "Avodah Zarah",
    "Pirkei Avot", "Horayot",
    # Seder Kodashim
    "Zevachim", "Menachot", "Chullin", "Bekhorot",
    "Arakhin", "Temurah", "Keritot", "Meilah",
    "Tamid", "Middot", "Kinnim",
    # Seder Tahorot
    "Kelim", "Oholot", "Negaim", "Parah", "Tahorot",
    "Mikvaot", "Niddah", "Makhshirin", "Zavim",
    "Tevul Yom", "Yadayim", "Oktzin"
]

MIDRASH_TEXTS = [
    "Bereishit Rabbah",
    "Shemot Rabbah",
    "Vayikra Rabbah",
    "Bamidbar Rabbah",
    "Devarim Rabbah",
    "Kohelet Rabbah",
    "Esther Rabbah",
    "Ruth Rabbah",
    "Eichah Rabbah",
    "Shir HaShirim Rabbah",
    "Mekhilta DeRabbi Yishmael",
    "Sifra",
    "Sifre Bamidbar",
    "Sifre Devarim",
    "Pesikta DeRav Kahana",
    "Tanchuma",
    "Midrash Tanchuma",
    "Pirkei DeRabbi Eliezer",
    "Avot DeRabbi Natan",
]

OTHER_TEXTS = [
    ("Mishneh Torah, Foundations of the Torah", "Halakhah", "Rambam"),
    ("Mishneh Torah, Human Dispositions", "Halakhah", "Rambam"),
    ("Mishneh Torah, Torah Study", "Halakhah", "Rambam"),
    ("Mishneh Torah, Repentance", "Halakhah", "Rambam"),
    ("Mishneh Torah, Prayer and the Priestly Blessing", "Halakhah", "Rambam"),
    ("Sefer HaChinukh", "Halakhah", "Mitzvot"),
    ("Kuzari", "Philosophy", "Medieval"),
    ("Guide for the Perplexed", "Philosophy", "Rambam"),
    ("Messilat Yesharim", "Mussar", "Ethics"),
    ("Orchot Tzadikim", "Mussar", "Ethics"),
    ("Tanya", "Chasidut", "Chabad"),
    ("Likutey Moharan", "Chasidut", "Breslov"),
    ("Shulchan Arukh, Orach Chayyim", "Halakhah", "Shulchan Arukh"),
    ("Shulchan Arukh, Yoreh De'ah", "Halakhah", "Shulchan Arukh"),
    ("Shulchan Arukh, Even HaEzer", "Halakhah", "Shulchan Arukh"),
    ("Shulchan Arukh, Choshen Mishpat", "Halakhah", "Shulchan Arukh"),
]

SIDDUR_TEXTS = [
    "Siddur Ashkenaz",
    "Siddur Sefard",
    "Pesach Haggadah",
]


def main():
    section = sys.argv[1] if len(sys.argv) > 1 else "all"

    sections_to_run = []
    if section == "all":
        sections_to_run = ["torah", "neviim", "ketuvim", "talmud", "mishnah", "midrash", "siddur", "other"]
    else:
        sections_to_run = [section]

    for sec in sections_to_run:
        if sec == "torah":
            print("\n=== DOWNLOADING TORAH ===")
            torah_dir = os.path.join(LIBRARY_DIR, "torah")
            for book in TORAH_BOOKS:
                download_biblical_book(book, "Tanakh", "Torah", torah_dir)

        elif sec == "neviim":
            print("\n=== DOWNLOADING NEVI'IM ===")
            neviim_dir = os.path.join(LIBRARY_DIR, "neviim")
            for book in NEVIIM_BOOKS:
                download_biblical_book(book, "Tanakh", "Neviim", neviim_dir)

        elif sec == "ketuvim":
            print("\n=== DOWNLOADING KETUVIM ===")
            ketuvim_dir = os.path.join(LIBRARY_DIR, "ketuvim")
            for book in KETUVIM_BOOKS:
                download_biblical_book(book, "Tanakh", "Ketuvim", ketuvim_dir)

        elif sec == "talmud":
            print("\n=== DOWNLOADING TALMUD BAVLI ===")
            talmud_dir = os.path.join(LIBRARY_DIR, "talmud")
            for tractate in TALMUD_TRACTATES:
                download_talmud_tractate(tractate, talmud_dir)

        elif sec == "mishnah":
            print("\n=== DOWNLOADING MISHNAH ===")
            mishnah_dir = os.path.join(LIBRARY_DIR, "mishnah")
            for tractate in MISHNAH_TRACTATES:
                download_mishnah_tractate(tractate, mishnah_dir)

        elif sec == "midrash":
            print("\n=== DOWNLOADING MIDRASH ===")
            midrash_dir = os.path.join(LIBRARY_DIR, "midrash")
            for text in MIDRASH_TEXTS:
                download_simple_text(text, "Midrash", "Aggadah", midrash_dir)

        elif sec == "siddur":
            print("\n=== DOWNLOADING SIDDUR & LITURGY ===")
            siddur_dir = os.path.join(LIBRARY_DIR, "siddur")
            for text in SIDDUR_TEXTS:
                download_simple_text(text, "Liturgy", "Siddur", siddur_dir)

        elif sec == "other":
            print("\n=== DOWNLOADING OTHER TEXTS ===")
            other_dir = os.path.join(LIBRARY_DIR, "other")
            for text_info in OTHER_TEXTS:
                ref, category, subcategory = text_info
                download_simple_text(ref, category, subcategory, other_dir)

    print("\n=== DOWNLOAD COMPLETE ===")


if __name__ == "__main__":
    main()
