#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import struct
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zipfile import BadZipFile, ZipFile

IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tiff", ".webp", ".bmp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp", ".hevc"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Porządkuje zdjęcia i filmy z archiwów iCloud ZIP do struktury: "
            "ROK/MIESIAC/{photos,movies,screenshots,downloads}."
        )
    )
    parser.add_argument("zip_files", nargs="+", type=Path, help="Pliki *.zip do przetworzenia")
    parser.add_argument("--target", required=True, type=Path, help="Folder docelowy z archiwum")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help=(
            "Folder roboczy do rozpakowywania ZIP (np. szybki SSD). "
            "Jeśli pominięty, używany jest systemowy katalog tymczasowy."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pokaż co zostałoby zrobione, bez kopiowania plików",
    )
    return parser.parse_args()


@dataclass
class MediaItem:
    path: Path
    archive_rel_path: Path
    zip_datetime: Optional[datetime]


class DuplicateIndex:
    def __init__(self, root: Path):
        self.root = root
        self.paths_by_size: Dict[int, List[Path]] = defaultdict(list)
        self.hash_cache: Dict[Path, str] = {}

    def build(self) -> None:
        if not self.root.exists():
            return
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in MEDIA_EXTS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            self.paths_by_size[size].append(path)

    def _file_hash(self, path: Path) -> str:
        if path in self.hash_cache:
            return self.hash_cache[path]
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
        self.hash_cache[path] = digest
        return digest

    def has_duplicate(self, candidate: Path) -> bool:
        try:
            size = candidate.stat().st_size
        except OSError:
            return False
        maybe = self.paths_by_size.get(size)
        if not maybe:
            return False
        cand_hash = self._file_hash(candidate)
        for path in maybe:
            if self._file_hash(path) == cand_hash:
                return True
        return False

    def add(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return
        self.paths_by_size[size].append(path)


def extract_zip(zip_path: Path, workspace: Path) -> List[MediaItem]:
    extracted: List[MediaItem] = []
    with ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            in_zip = Path(info.filename)
            if in_zip.suffix.lower() not in MEDIA_EXTS:
                continue
            out_path = workspace / in_zip
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            dt = None
            try:
                dt = datetime(*info.date_time)
            except ValueError:
                pass
            extracted.append(MediaItem(path=out_path, archive_rel_path=in_zip, zip_datetime=dt))
    return extracted




def _extract_exif_datetime(path: Path) -> Optional[datetime]:
    ext = path.suffix.lower()
    if ext not in {".jpg", ".jpeg", ".heic", ".heif"}:
        return None
    try:
        with path.open("rb") as f:
            data = f.read(2 * 1024 * 1024)
    except OSError:
        return None

    text = data.decode("latin1", errors="ignore")
    # Typowe pola EXIF/XMP: DateTimeOriginal / CreateDate w formacie YYYY:MM:DD HH:MM:SS
    for match in re.finditer(r"(19|20)\d{2}:[01]\d:[0-3]\d [0-2]\d:[0-5]\d:[0-5]\d", text):
        raw = match.group(0)
        try:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None
def guess_taken_date(path: Path, fallback: Optional[datetime]) -> datetime:
    # 1) Najpierw próbujemy metadane obrazu (EXIF/XMP), bo są najbardziej wiarygodne.
    exif_dt = _extract_exif_datetime(path)
    if exif_dt:
        return exif_dt

    # 2) Potem data z wpisu ZIP (jeśli jest).
    if fallback:
        return fallback

    # 3) Na końcu data zaszyta w nazwie pliku (np. IMG_20260123_123456.jpg).
    name = path.stem
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime(y, mo, d)
        except ValueError:
            pass

    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts)


SCREENSHOT_KEYWORDS = (
    "screenshot",
    "screen_shot",
    "zrzut ekranu",
    "zrzut-ekranu",
    "zrzut",
)


def _png_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        with path.open("rb") as f:
            header = f.read(24)
    except OSError:
        return None
    if len(header) < 24:
        return None
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def _jpeg_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        with path.open("rb") as f:
            data = f.read(512 * 1024)
    except OSError:
        return None
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None

    i = 2
    while i + 1 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):
            continue
        if i + 1 >= len(data):
            break
        seg_len = int.from_bytes(data[i:i+2], "big")
        if seg_len < 2 or i + seg_len > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 7 >= len(data):
                break
            height = int.from_bytes(data[i+3:i+5], "big")
            width = int.from_bytes(data[i+5:i+7], "big")
            return width, height
        i += seg_len
    return None


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    ext = path.suffix.lower()
    if ext == ".png":
        return _png_size(path)
    if ext in {".jpg", ".jpeg"}:
        return _jpeg_size(path)
    return None


def _looks_like_screenshot_name(name: str) -> bool:
    lower_name = name.lower()
    if any(k in lower_name for k in SCREENSHOT_KEYWORDS):
        return True
    # iOS bywa eksportowany jako IMG_1234.PNG dla screenshotów
    if re.match(r"^img(?:_e)?_\d{4,}$", Path(name).stem.lower()):
        return Path(name).suffix.lower() == ".png"
    return False


def _looks_like_phone_screen_ratio(path: Path) -> bool:
    size = _image_size(path)
    if not size:
        return False
    width, height = size
    if width == 0 or height == 0:
        return False
    long_edge = max(width, height)
    short_edge = min(width, height)
    ratio = long_edge / short_edge
    # Ekrany smartfonów: zwykle od ok. 1.9:1 do 2.25:1
    return 1.9 <= ratio <= 2.3




def _jpeg_contains_camera_exif(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            data = f.read(1024 * 1024)
    except OSError:
        return False

    lowered = data.lower()
    if b"exif" not in lowered:
        return False

    camera_markers = (
        b"apple",
        b"iphone",
        b"datetimeoriginal",
        b"lensmodel",
        b"fnumber",
        b"exposuretime",
    )
    return any(marker in lowered for marker in camera_markers)


def _looks_like_camera_photo(item: MediaItem) -> bool:
    ext = item.path.suffix.lower()
    lower_name = item.path.name.lower()
    iphone_prefixes = ("img_", "dsc", "pxl_", "mvimg")

    if ext in {".heic", ".heif"} and lower_name.startswith(iphone_prefixes):
        return True

    if ext in {".jpg", ".jpeg"} and lower_name.startswith(iphone_prefixes):
        return _jpeg_contains_camera_exif(item.path)

    return False
def classify(item: MediaItem) -> str:
    lower_name = item.path.name.lower()
    lower_rel = str(item.archive_rel_path).lower()
    ext = item.path.suffix.lower()

    if any(k in lower_rel for k in SCREENSHOT_KEYWORDS) or _looks_like_screenshot_name(item.path.name):
        return "screenshots"

    if ext in VIDEO_EXTS:
        return "movies"

    if ext in IMAGE_EXTS:
        if ext == ".png" and _looks_like_phone_screen_ratio(item.path):
            return "screenshots"
        if "download" in lower_rel or "pobrane" in lower_rel:
            return "downloads"
        return "photos" if _looks_like_camera_photo(item) else "downloads"

    return "downloads"


def unique_destination_path(base_dir: Path, src_name: str) -> Path:
    candidate = base_dir / src_name
    if not candidate.exists():
        return candidate
    stem = Path(src_name).stem
    suffix = Path(src_name).suffix
    idx = 1
    while True:
        candidate = base_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def move_to_archive(
    item: MediaItem,
    target_root: Path,
    duplicates: DuplicateIndex,
    dry_run: bool = False,
) -> str:
    date = guess_taken_date(item.path, item.zip_datetime)
    year = str(date.year)
    month = str(date.month)
    category = classify(item)

    dest_dir = target_root / year / month / category
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    if duplicates.has_duplicate(item.path):
        return f"SKIP duplicate: {item.path.name}"

    dest = unique_destination_path(dest_dir, item.path.name)
    if dry_run:
        return f"COPY {item.path} -> {dest}"

    shutil.copy2(item.path, dest)
    duplicates.add(dest)
    return f"OK {item.path.name} -> {dest}"


def validate_inputs(zip_files: Iterable[Path]) -> None:
    for zip_path in zip_files:
        if not zip_path.exists() or not zip_path.is_file():
            raise FileNotFoundError(f"Brak pliku ZIP: {zip_path}")
        if zip_path.suffix.lower() != ".zip":
            raise ValueError(f"Plik nie jest ZIP: {zip_path}")


def main() -> int:
    args = parse_args()
    try:
        validate_inputs(args.zip_files)
    except Exception as exc:
        print(f"Błąd walidacji: {exc}", file=sys.stderr)
        return 2

    target = args.target
    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    duplicates = DuplicateIndex(target)
    duplicates.build()

    work_parent = args.work_dir
    if work_parent is not None:
        work_parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with tempfile.TemporaryDirectory(dir=work_parent) as tmp:
        tmp_path = Path(tmp)
        for zip_path in args.zip_files:
            zip_workspace = tmp_path / zip_path.stem
            zip_workspace.mkdir(parents=True, exist_ok=True)
            print(f"Przetwarzam {zip_path} ...")
            try:
                items = extract_zip(zip_path, zip_workspace)
            except (BadZipFile, OSError) as exc:
                print(f"  Pomijam uszkodzony ZIP: {zip_path} ({exc})", file=sys.stderr)
                continue
            if not items:
                print("  Brak plików multimedialnych w archiwum ZIP")
                continue
            for item in items:
                msg = move_to_archive(item, target, duplicates, dry_run=args.dry_run)
                print("  " + msg)
                total += 1

    print(f"Gotowe. Przetworzono elementów: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
