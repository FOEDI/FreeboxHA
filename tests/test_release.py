"""Check the public distribution without packaging local development state."""

import json
from pathlib import Path
from zipfile import ZipFile

from scripts.build_release import DOCUMENTS, PACKAGE, build_release


def release_tree(root: Path) -> None:
    package = root / PACKAGE
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
    (package / "__init__.py").write_text("# integration", encoding="utf-8")
    (package / "private.log").write_text("secret", encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__/cached.py").write_text("cache", encoding="utf-8")
    for name in DOCUMENTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public", encoding="utf-8")


def test_archive_contains_only_installable_sources_and_public_documents(tmp_path):
    release_tree(tmp_path)
    target = build_release(tmp_path)
    assert target.name == "FreeboxHA-v1.0.0.zip"
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {*DOCUMENTS, f"{PACKAGE}/manifest.json", f"{PACKAGE}/__init__.py"}
        assert json.loads(archive.read(f"{PACKAGE}/manifest.json"))["version"] == "1.0.0"


def test_archive_is_reproducible(tmp_path):
    release_tree(tmp_path)
    first = build_release(tmp_path).read_bytes()
    assert build_release(tmp_path).read_bytes() == first
