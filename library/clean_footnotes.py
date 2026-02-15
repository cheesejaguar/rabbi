#!/usr/bin/env python3
"""
Clean up footnote artifacts in downloaded markdown files.
Sefaria HTML includes <sup> footnote markers and <i> footnote text
that sometimes merge with the body text after HTML stripping.
"""

import os
import re
import sys


def clean_footnotes(text):
    """Remove footnote markers and inline footnote text from stripped HTML."""
    # Remove patterns like: wordaFootnote text here  (sup marker + i tag content merged)
    # Pattern: a lowercase letter followed by a capital letter starting a footnote
    # Common Sefaria footnote patterns after HTML strip:
    # "texta Footnote text here rest of verse" -> "text rest of verse"

    # First pass: remove <sup>...</sup> and <i>...</i> tags and their content
    text = re.sub(r'<sup[^>]*>.*?</sup>', '', text)
    text = re.sub(r'<i class="footnote">.*?</i>', '', text, flags=re.DOTALL)
    text = re.sub(r'<i[^>]*>.*?</i>', '', text, flags=re.DOTALL)

    # Remove any remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Clean up double spaces
    text = re.sub(r'  +', ' ', text)

    return text.strip()


def process_file(filepath):
    """Clean footnotes from a markdown file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check if file has potential footnote artifacts
    # (indicated by having sup/footnote content or merged text)
    original = content

    # Re-process: for lines that have footnote-like patterns
    cleaned = clean_footnotes(content)

    if cleaned != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned)
        return True
    return False


def main():
    library_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) > 1:
        dirs = [os.path.join(library_dir, d) for d in sys.argv[1:]]
    else:
        dirs = [os.path.join(library_dir, d) for d in
                ['torah', 'neviim', 'ketuvim', 'talmud', 'mishnah',
                 'midrash', 'siddur', 'other']]

    total_cleaned = 0
    for dirpath in dirs:
        if not os.path.isdir(dirpath):
            continue
        for filename in sorted(os.listdir(dirpath)):
            if not filename.endswith('.md'):
                continue
            filepath = os.path.join(dirpath, filename)
            if process_file(filepath):
                total_cleaned += 1
                print(f"Cleaned: {filename}")

    print(f"\nTotal files cleaned: {total_cleaned}")


if __name__ == "__main__":
    main()
