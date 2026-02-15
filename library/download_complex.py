#!/usr/bin/env python3
"""
Download complex-schema texts from Sefaria API (texts with named sections, not numbered chapters).
Handles Siddur, Haggadah, Mekhilta, and other non-standard structures.
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "https://www.sefaria.org/api/v3/texts/"
LIBRARY_DIR = os.path.dirname(os.path.abspath(__file__))
REQUEST_DELAY = 1.0
MAX_RETRIES = 4


def sanitize_filename(name):
    name = name.replace(" ", "_")
    name = re.sub(r'[^\w\-]', '', name)
    return name


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


def extract_section_refs(schema, parent_ref=""):
    """Recursively extract all leaf-node references from a complex schema."""
    refs = []
    node_type = schema.get('nodeType', '')

    if node_type == 'JaggedArrayNode' or 'addressTypes' in schema:
        # This is a leaf node with actual text
        titles = schema.get('titles', [])
        en_title = ""
        for t in titles:
            if t.get('lang') == 'en' and t.get('primary', False):
                en_title = t['text']
                break
        if not en_title:
            for t in titles:
                if t.get('lang') == 'en':
                    en_title = t['text']
                    break

        if parent_ref and en_title:
            ref = f"{parent_ref}, {en_title}"
        elif en_title:
            ref = en_title
        else:
            ref = parent_ref

        if ref:
            refs.append((ref, en_title or ref))

    elif node_type == 'SchemaNode' or 'nodes' in schema:
        titles = schema.get('titles', [])
        en_title = ""
        for t in titles:
            if t.get('lang') == 'en' and t.get('primary', False):
                en_title = t['text']
                break

        current_ref = parent_ref
        if en_title and parent_ref and en_title != parent_ref:
            current_ref = f"{parent_ref}, {en_title}"
        elif en_title:
            current_ref = en_title

        for node in schema.get('nodes', []):
            refs.extend(extract_section_refs(node, current_ref))

    return refs


def download_complex_text(title, category, subcategory, output_dir):
    """Download a text with complex schema."""
    print(f"Downloading {title}...")

    # Get index to understand structure
    index_url = f"https://www.sefaria.org/api/index/{urllib.parse.quote(title)}"
    index_data = fetch_json(index_url)
    if not index_data:
        print(f"  Could not fetch index for {title}")
        return False

    he_title = index_data.get('heTitle', '')
    schema = index_data.get('schema', {})

    # Extract all section references
    section_refs = extract_section_refs(schema)
    if not section_refs:
        print(f"  No sections found for {title}")
        return False

    print(f"  Found {len(section_refs)} sections")

    lines = []
    lines.append("---")
    lines.append(f'title: "{title}"')
    if he_title:
        lines.append(f'he_title: "{he_title}"')
    lines.append(f'category: "{category}"')
    lines.append(f'subcategory: "{subcategory}"')
    lines.append(f'source: "Sefaria.org"')
    lines.append(f'license: "CC-BY-NC"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    if he_title:
        lines.append(f"## {he_title}")
    lines.append("")

    sections_downloaded = 0
    for ref, section_name in section_refs:
        encoded = urllib.parse.quote(ref)
        url = f"{BASE_URL}{encoded}?version=primary&language=en"
        data = fetch_json(url)

        if data is None:
            continue

        versions = data.get('versions', [])
        text_content = None
        for v in versions:
            if v.get('language') == 'en':
                text_content = v.get('text')
                break
        if not text_content and versions:
            text_content = versions[0].get('text')

        if text_content:
            flat = flatten_text(text_content)
            if flat:
                # Use section name as header
                display_name = section_name.replace(title + ", ", "")
                lines.append(f"## {display_name}")
                lines.append("")
                for i, para in enumerate(flat, 1):
                    if para.strip():
                        lines.append(f"{para}")
                        lines.append("")
                lines.append("")
                sections_downloaded += 1

    if sections_downloaded == 0:
        print(f"  No content downloaded for {title}")
        return False

    filename = sanitize_filename(title) + ".md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"  Saved {filepath} ({sections_downloaded} sections)")
    return True


def main():
    siddur_dir = os.path.join(LIBRARY_DIR, "siddur")
    midrash_dir = os.path.join(LIBRARY_DIR, "midrash")
    other_dir = os.path.join(LIBRARY_DIR, "other")

    os.makedirs(siddur_dir, exist_ok=True)
    os.makedirs(midrash_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)

    # Siddur texts
    print("\n=== SIDDUR & LITURGY ===")
    siddur_texts = [
        ("Siddur Ashkenaz", "Liturgy", "Siddur"),
        ("Siddur Sefard", "Liturgy", "Siddur"),
        ("Pesach Haggadah", "Liturgy", "Haggadah"),
    ]
    for title, cat, subcat in siddur_texts:
        download_complex_text(title, cat, subcat, siddur_dir)

    # Complex Midrash texts
    print("\n=== COMPLEX MIDRASH ===")
    midrash_texts = [
        ("Mekhilta DeRabbi Yishmael", "Midrash", "Halakhic Midrash"),
        ("Sifra", "Midrash", "Halakhic Midrash"),
        ("Sifre Bamidbar", "Midrash", "Halakhic Midrash"),
        ("Sifre Devarim", "Midrash", "Halakhic Midrash"),
        ("Pesikta DeRav Kahana", "Midrash", "Aggadic Midrash"),
        ("Tanchuma", "Midrash", "Aggadic Midrash"),
        ("Midrash Tanchuma", "Midrash", "Aggadic Midrash"),
        ("Pirkei DeRabbi Eliezer", "Midrash", "Aggadic Midrash"),
        ("Avot DeRabbi Natan", "Midrash", "Aggadic Midrash"),
    ]
    for title, cat, subcat in midrash_texts:
        download_complex_text(title, cat, subcat, midrash_dir)

    # Complex other texts
    print("\n=== COMPLEX OTHER TEXTS ===")
    other_texts = [
        ("Guide for the Perplexed", "Philosophy", "Rambam"),
        ("Messilat Yesharim", "Mussar", "Ethics"),
        ("Orchot Tzadikim", "Mussar", "Ethics"),
        ("Tanya", "Chasidut", "Chabad"),
        ("Likutey Moharan", "Chasidut", "Breslov"),
        ("Sefer HaChinukh", "Halakhah", "Mitzvot"),
    ]
    for title, cat, subcat in other_texts:
        download_complex_text(title, cat, subcat, other_dir)

    print("\n=== COMPLEX DOWNLOADS COMPLETE ===")


if __name__ == "__main__":
    main()
