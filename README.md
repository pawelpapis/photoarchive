# photoarchive

Aplikacja CLI do porządkowania zdjęć i filmów z archiwów iCloud (`*.zip`) do struktury:

```text
<target>/<rok>/<miesiąc>/{photos,movies,screenshots,downloads}
```

## Wymagania

- Python 3.10+
- Ubuntu / Linux

## Uruchomienie

```bash
python3 photoarchive.py archiwum1.zip archiwum2.zip --target /ścieżka/do/archiwum
```

Opcjonalnie możesz wskazać szybki dysk roboczy (np. SSD) do rozpakowywania ZIP:

```bash
python3 photoarchive.py archiwum.zip --target /mnt/archive --work-dir /mnt/ssd/tmp
```

Tryb podglądu (bez kopiowania):

```bash
python3 photoarchive.py archiwum.zip --target /mnt/archive --dry-run
```

## Zasady działania

- Odczytuje pliki multimedialne z folderu `Zdjęcia w iCloud` wewnątrz ZIP.
- Tworzy folder docelowy, jeśli nie istnieje.
- Grupuje pliki wg roku/miesiąca i typu (`photos`, `movies`, `screenshots`, `downloads`).
- Nie kopiuje duplikatów: porównuje rozmiar i hash SHA-256 z już istniejącymi plikami.
- Obsługuje wiele plików ZIP w jednym uruchomieniu.

## Testy

```bash
python3 -m pytest -q
```
