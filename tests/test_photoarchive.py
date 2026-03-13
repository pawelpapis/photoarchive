import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZipInfo

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
        zf.writestr("Zdjęcia w iCloud/IMG_20260101_000001.HEIC", b"heic-photo")
        zf.writestr("inne/foldery/Screenshot 2026-01-02 at 10.00.00.png", b"screen")
        zf.writestr("root/VID_20260103_000001.mov", b"movie")
        zf.writestr("inne/foldery/IMG_9999.PNG", _ONE_BY_ONE_PNG)
        zf.writestr("memes/IMG_20250101_123000.jpg", b"meme-without-exif")


def test_extract_and_classify():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)

        items = extract_zip(z, tmp / "work")
        by_name = {i.path.name: i for i in items}

        assert sorted(by_name) == [
            "IMG_20250101_123000.jpg",
            "IMG_20260101_000001.HEIC",
            "IMG_9999.PNG",
            "Screenshot 2026-01-02 at 10.00.00.png",
            "VID_20260103_000001.mov",
        ]
        assert classify(by_name["IMG_20260101_000001.HEIC"]) == "photos"
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


def test_non_camera_img_jpg_goes_to_downloads():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "in.zip"
        _make_zip(z)

        items = extract_zip(z, tmp / "work")
        meme_item = next(i for i in items if i.path.name == "IMG_20250101_123000.jpg")
        assert classify(meme_item) == "downloads"


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


def test_exif_date_has_priority_over_filename_and_zip_date():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "dated.zip"

        fake_jpg = (
            b"Exif\x00\x00 Apple iPhone DateTimeOriginal 2021:07:15 10:11:12 "
            b"random-bytes"
        )

        with ZipFile(z, "w") as zf:
            info_name = "folder/IMG_20250401_120000.jpg"
            zf.writestr(info_name, fake_jpg)

        items = extract_zip(z, tmp / "work")
        item = items[0]

        target = tmp / "target"
        target.mkdir()
        idx = DuplicateIndex(target)
        idx.build()

        msg = move_to_archive(item, target, idx)
        assert "2021/7/photos" in msg


def test_main_skips_corrupted_zip_and_continues():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bad_zip = tmp / "bad.zip"
        bad_zip.write_bytes(b"this-is-not-a-zip")

        good_zip = tmp / "good.zip"
        with ZipFile(good_zip, "w") as zf:
            info = ZipInfo("x/IMG_20260101_000001.HEIC")
            info.date_time = (2026, 1, 1, 12, 0, 0)
            zf.writestr(info, b"heic-photo")

        target = tmp / "target"
        script = Path(__file__).resolve().parents[1] / "photoarchive.py"
        result = subprocess.run(
            [sys.executable, str(script), str(bad_zip), str(good_zip), "--target", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert "Pomijam uszkodzony ZIP" in result.stderr
        assert (target / "2026" / "1" / "photos" / "IMG_20260101_000001.HEIC").exists()
