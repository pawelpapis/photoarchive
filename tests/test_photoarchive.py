import tempfile
from pathlib import Path
from zipfile import ZipFile

from photoarchive import DuplicateIndex, classify, extract_zip, move_to_archive


def _make_zip(path: Path) -> None:
    with ZipFile(path, "w") as zf:
        zf.writestr("Zdjęcia w iCloud/IMG_20260101_000001.jpg", b"photo")
        zf.writestr("Zdjęcia w iCloud/Screenshot 2026-01-02 at 10.00.00.png", b"screen")
        zf.writestr("Zdjęcia w iCloud/VID_20260103_000001.mov", b"movie")


def test_extract_and_classify():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)

        items = extract_zip(z, tmp / "work")
        names = sorted(i.path.name for i in items)
        assert names == [
            "IMG_20260101_000001.jpg",
            "Screenshot 2026-01-02 at 10.00.00.png",
            "VID_20260103_000001.mov",
        ]
        assert classify(items[0].path) in {"photos", "screenshots", "movies", "downloads"}


def test_duplicate_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)
        items = extract_zip(z, tmp / "work")

        target = tmp / "target"
        target.mkdir()
        idx = DuplicateIndex(target)
        idx.build()

        msg1 = move_to_archive(items[0], target, idx)
        msg2 = move_to_archive(items[0], target, idx)

        assert msg1.startswith("OK")
        assert msg2.startswith("SKIP duplicate")
