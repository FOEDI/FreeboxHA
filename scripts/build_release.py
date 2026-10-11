"""Build a reproducible install archive containing only public release files."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path("custom_components/freebox_ultra_ultimate")
DOCUMENTS = (
    "README.md",
    "LICENSE",
    "docs/api-research.md",
    "docs/validation.md",
    "docs/release-notes.md",
    "examples/automations.yaml",
)


def build_release(root: Path = ROOT) -> Path:
    """Build identical archive bytes for identical source files."""
    version = json.loads((root / PACKAGE / "manifest.json").read_text(encoding="utf-8"))["version"]
    target = root / "dist" / f"FreeboxHA-v{version}.zip"
    target.parent.mkdir(exist_ok=True)
    sources = [
        path
        for path in (root / PACKAGE).rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".pem"} and "__pycache__" not in path.parts
    ]
    sources.extend(root / name for name in DOCUMENTS)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(sources):
            info = ZipInfo(path.relative_to(root).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return target


if __name__ == "__main__":
    print(build_release())
