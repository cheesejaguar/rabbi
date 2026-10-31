"""Guards for the Vercel deployment's dependency files."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def _requirement_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_requirements_have_no_local_or_editable_entries():
    """`uv export` emits `-e .` for the project itself unless told not to.

    In api/requirements.txt that resolves to the api/ directory, and Vercel's
    build fails with "Distribution not found at: file:///vercel/path0/api/api".
    Regenerate with `uv export --no-hashes --no-dev --no-emit-project`.
    """
    for name in ("requirements.txt", "api/requirements.txt"):
        bad = [line for line in _requirement_lines(ROOT / name)
               if line.startswith(("-e", ".", "/", "file:")) or " @ file:" in line]
        assert bad == [], f"{name} contains local/editable entries: {bad}"


def test_api_and_root_requirements_match():
    assert (ROOT / "requirements.txt").read_text() == (ROOT / "api/requirements.txt").read_text()
