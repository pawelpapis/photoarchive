import tempfile
from pathlib import Path
from zipfile import ZipFile

from photoarchive import DuplicateIndex, classify, extract_zip, move_to_archive


_ONE_BY_ONE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\x99c```\x00\x00\x00\x04\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_zip(path: Path) -> None:
    with ZipFile(path, "w") as zf:
        zf.writestr("Zdjęcia w iCloud/IMG_20260101_000001.jpg", b"photo")
        zf.writestr("inne/foldery/Screenshot 2026-01-02 at 10.00.00.png", b"screen")
        zf.writestr("root/VID_20260103_000001.mov", b"movie")
        zf.writestr("inne/foldery/IMG_9999.PNG", _ONE_BY_ONE_PNG)


def test_extract_and_classify():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)

        items = extract_zip(z, tmp / "work")
        by_name = {i.path.name: i for i in items}

        assert sorted(by_name) == [
            "IMG_20260101_000001.jpg",
            "IMG_9999.PNG",
            "Screenshot 2026-01-02 at 10.00.00.png",
            "VID_20260103_000001.mov",
        ]
        assert classify(by_name["IMG_20260101_000001.jpg"]) == "photos"
        assert classify(by_name["Screenshot 2026-01-02 at 10.00.00.png"]) == "screenshots"
        assert classify(by_name["VID_20260103_000001.mov"]) == "movies"


def test_iphone_named_png_goes_to_screenshots():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)

        items = extract_zip(z, tmp / "work")
        png_item = next(i for i in items if i.path.name == "IMG_9999.PNG")
        assert classify(png_item) == "screenshots"


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
