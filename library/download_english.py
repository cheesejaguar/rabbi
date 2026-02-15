#!/usr/bin/env python3
"""
Download English translations of key texts from Sefaria API v2.
These are stored alongside the Hebrew originals for bilingual RAG.
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse

LIBRARY_DIR = os.path.dirname(os.path.abspath(__file__))
REQUEST_DELAY = 1.0
MAX_RETRIES = 4


def sanitize_filename(name):
    name = name.replace(" ", "_")
    name = re.sub(r'[^\w\-]', '', name)
    return name


def strip_html(text):
    return re.sub(r'<[^>]+>', '', text)


def flatten_text(text):
    results = []
    if isinstance(text, str):
        clean = strip_html(text)
        if clean.strip():
            results.append(clean)
    elif isinstance(text, list):
        for item in text:
            results.extend(flatten_text(item))
    return results


def fetch_json(url, retries=MAX_RETRIES):
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
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 404:
                return None
            else:
                print(f"  HTTP {e.code}, attempt {attempt + 1}")
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error: {e}, attempt {attempt + 1}")
            time.sleep(2 ** attempt)
    return None


def download_english_book(ref, category, subcategory, output_dir):
    """Download English translation of a biblical book using v2 API."""
    print(f"Downloading English: {ref}...")

    # Get index for chapter count and Hebrew title
    index_url = f"https://www.sefaria.org/api/index/{urllib.parse.quote(ref)}"
    index_data = fetch_json(index_url)
    if not index_data:
        print(f"  Could not fetch index for {ref}")
        return False

    he_title = index_data.get('heTitle', '')
    schema = index_data.get('schema', {})
    lengths = schema.get('lengths', [])
    num_chapters = lengths[0] if lengths else 50

    lines = []
    lines.append("---")
    lines.append(f'title: "{ref}"')
    if he_title:
        lines.append(f'he_title: "{he_title}"')
    lines.append(f'category: "{category}"')
    lines.append(f'subcategory: "{subcategory}"')
    lines.append(f'language: "en"')
    lines.append(f'source: "Sefaria.org"')
    lines.append(f'license: "CC-BY-NC"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {ref} (English)")
    lines.append("")

    chapters_found = 0
    for ch in range(1, num_chapters + 1):
        ch_ref = f"{ref}.{ch}"
        encoded = urllib.parse.quote(ch_ref)

        # Use v2 API which returns 'text' (English) and 'he' (Hebrew)
        url = f"https://www.sefaria.org/api/texts/{encoded}?lang=en&context=0"
        data = fetch_json(url)

        if data is None:
            if chapters_found > 0:
                break
            continue

        en_text = data.get('text', [])
        if en_text:
            flat = flatten_text(en_text)
            if flat:
                lines.append(f"## Chapter {ch}")
                lines.append("")
                for i, verse in enumerate(flat, 1):
                    if verse.strip():
                        lines.append(f"**{ch}:{i}** {verse}")
                        lines.append("")
                lines.append("")
                chapters_found += 1

    if chapters_found == 0:
        print(f"  No English content for {ref}")
        return False

    filename = sanitize_filename(ref) + "_en.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"  Saved {filepath} ({chapters_found} chapters)")
    return True


def download_english_talmud(tractate, output_dir):
    """Download English translation of a Talmud tractate using v2 API."""
    print(f"Downloading English Talmud: {tractate}...")

    index_url = f"https://www.sefaria.org/api/index/{urllib.parse.quote(tractate)}"
    index_data = fetch_json(index_url)
    if not index_data:
        return False

    he_title = index_data.get('heTitle', '')
    schema = index_data.get('schema', {})
    lengths = schema.get('lengths', [])
    num_pages = lengths[0] if lengths else 100

    lines = []
    lines.append("---")
    lines.append(f'title: "Talmud {tractate}"')
    if he_title:
        lines.append(f'he_title: "{he_title}"')
    lines.append(f'category: "Talmud"')
    lines.append(f'subcategory: "Bavli"')
    lines.append(f'language: "en"')
    lines.append(f'source: "Sefaria.org (William Davidson Talmud)"')
    lines.append(f'license: "CC-BY-NC"')
    lines.append("---")
    lines.append("")
    lines.append(f"# Talmud Bavli: {tractate} (English)")
    lines.append("")

    pages_found = 0
    consecutive_failures = 0

    for page_num in range(2, num_pages + 2):
        for side in ['a', 'b']:
            daf = f"{page_num}{side}"
            ref = f"{tractate}.{daf}"
            encoded = urllib.parse.quote(ref)
            url = f"https://www.sefaria.org/api/texts/{encoded}?lang=en&context=0"
            data = fetch_json(url)

            if data is None:
                consecutive_failures += 1
                if consecutive_failures > 4:
                    break
                continue

            consecutive_failures = 0
            en_text = data.get('text', [])

            if en_text:
                flat = flatten_text(en_text)
                if flat:
                    lines.append(f"## Daf {daf}")
                    lines.append("")
                    for seg in flat:
                        if seg.strip():
                            lines.append(seg)
                            lines.append("")
                    lines.append("")
                    pages_found += 1

        if consecutive_failures > 4:
            break

    if pages_found == 0:
        print(f"  No English content for {tractate}")
        return False

    filename = f"Talmud_{sanitize_filename(tractate)}_en.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"  Saved {filepath} ({pages_found} pages)")
    return True


# Texts to download English translations for
TORAH = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]

NEVIIM = [
    "Joshua", "Judges", "I Samuel", "II Samuel", "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi"
]

KETUVIM = [
    "Psalms", "Proverbs", "Job", "Song of Songs", "Ruth",
    "Lamentations", "Ecclesiastes", "Esther", "Daniel",
    "Ezra", "Nehemiah", "I Chronicles", "II Chronicles"
]

# English translations for the most commonly studied Talmud tractates
KEY_TALMUD = [
    "Berakhot", "Shabbat", "Pesachim", "Yoma", "Sukkah",
    "Megillah", "Taanit", "Sanhedrin", "Bava Kamma",
    "Bava Metzia", "Bava Batra", "Gittin", "Kiddushin",
    "Avodah Zarah", "Chullin", "Niddah"
]


def main():
    import sys
    section = sys.argv[1] if len(sys.argv) > 1 else "all"

    if section in ("all", "tanakh"):
        print("\n=== ENGLISH TORAH ===")
        torah_dir = os.path.join(LIBRARY_DIR, "torah")
        for book in TORAH:
            download_english_book(book, "Tanakh", "Torah", torah_dir)

        print("\n=== ENGLISH NEVI'IM ===")
        neviim_dir = os.path.join(LIBRARY_DIR, "neviim")
        for book in NEVIIM:
            download_english_book(book, "Tanakh", "Neviim", neviim_dir)

        print("\n=== ENGLISH KETUVIM ===")
        ketuvim_dir = os.path.join(LIBRARY_DIR, "ketuvim")
        for book in KETUVIM:
            download_english_book(book, "Tanakh", "Ketuvim", ketuvim_dir)

    if section in ("all", "talmud"):
        print("\n=== ENGLISH TALMUD (KEY TRACTATES) ===")
        talmud_dir = os.path.join(LIBRARY_DIR, "talmud")
        for tractate in KEY_TALMUD:
            download_english_talmud(tractate, talmud_dir)

    print("\n=== ENGLISH DOWNLOADS COMPLETE ===")


if __name__ == "__main__":
    main()
