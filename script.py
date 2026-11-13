#!/usr/bin/env python3
"""
rekordbox_sync.py – kopiert die Tracks von rekordbox-Playlists in einen Ordner,
z. B. um sie aufs Handy zu bringen (USB, Syncthing, Cloud-Ordner ...).

Eingabe (eins von beiden):
  * rekordbox-XML   (rekordbox: Datei > Bibliothek > "Sammlung im XML-Format exportieren")
                    -> enthält ALLE Playlists, du wählst per --playlist aus
  * M3U8-Datei      (Rechtsklick auf Playlist > "Playlist in eine Datei exportieren")

Die Originaldateien werden nur KOPIERT, nie verschoben – sonst findet rekordbox
sie nicht mehr.

Beispiele:
  python rekordbox_sync.py rekordbox.xml --list
  python rekordbox_sync.py rekordbox.xml -p "Techno" -p "Sets/Sommer 2026" -t "D:\\Handy-Musik"
  python rekordbox_sync.py rekordbox.xml --all -t ~/Handy-Musik --mirror
  python rekordbox_sync.py "Meine Playlist.m3u8" -t ~/Handy-Musik --numbered
"""
import argparse
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

AUDIO_EXT = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac",
             ".alac", ".ogg", ".mp4"}


# --------------------------------------------------------------------------- #
# Einlesen
# --------------------------------------------------------------------------- #
def location_to_path(location: str) -> Path:
    """file://localhost/C:/Musik/a%20b.mp3  ->  C:/Musik/a b.mp3"""
    path = unquote(urlparse(location).path)
    if re.match(r"^/[A-Za-z]:/", path):          # Windows-Laufwerksbuchstabe
        path = path[1:]
    return Path(path)


def read_xml(xml_file: Path) -> dict:
    """Gibt {"Ordner/Playlist": [track, ...]} zurück."""
    root = ET.parse(xml_file).getroot()

    by_id, by_loc = {}, {}
    collection = root.find("COLLECTION")
    if collection is None:
        sys.exit("Fehler: Keine <COLLECTION> in der XML – ist das ein rekordbox-Export?")
    for t in collection.findall("TRACK"):
        track = {
            "path": location_to_path(t.get("Location", "")),
            "artist": t.get("Artist", ""),
            "title": t.get("Name", ""),
            "duration": int(float(t.get("TotalTime", "0") or 0)),
        }
        by_id[t.get("TrackID")] = track
        by_loc[t.get("Location")] = track

    playlists = {}

    def walk(node, prefix):
        for child in node.findall("NODE"):
            name = child.get("Name", "")
            full = f"{prefix}/{name}" if prefix else name
            if child.get("Type") == "0":          # Ordner
                walk(child, full)
            else:                                 # Playlist
                key_type = child.get("KeyType", "0")
                lookup = by_id if key_type == "0" else by_loc
                tracks = [lookup[e.get("Key")] for e in child.findall("TRACK")
                          if e.get("Key") in lookup]
                playlists[full] = tracks

    root_node = root.find("PLAYLISTS/NODE")
    if root_node is not None:
        walk(root_node, "")
    return playlists


def read_m3u(m3u_file: Path) -> dict:
    tracks, info = [], {}
    for line in m3u_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            dur, _, label = line[8:].partition(",")
            artist, _, title = label.partition(" - ")
            info = {"duration": int(float(dur or 0)) if dur.lstrip("-").replace(".", "").isdigit() else 0,
                    "artist": artist if title else "",
                    "title": title or label}
        elif not line.startswith("#"):
            p = location_to_path(line) if line.startswith("file:") else Path(line)
            if not p.is_absolute():
                p = m3u_file.parent / p
            tracks.append({"path": p, "artist": "", "title": p.stem, "duration": 0, **info})
            info = {}
    return {m3u_file.stem: tracks}


# --------------------------------------------------------------------------- #
# Kopieren
# --------------------------------------------------------------------------- #
def safe_name(name: str) -> str:
    """Entfernt Zeichen, die auf Windows/Android/FAT nicht erlaubt sind."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "_"


def needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    s, d = src.stat(), dst.stat()
    # 2 s Toleranz wegen FAT/exFAT-Zeitstempeln auf SD-Karten/USB-Sticks
    return s.st_size != d.st_size or s.st_mtime > d.st_mtime + 2


def sync_playlist(name, tracks, target: Path, mirror, numbered, dry):
    folder = target / safe_name(name.replace("/", " - "))
    if not dry:
        folder.mkdir(parents=True, exist_ok=True)

    used, entries = set(), []
    copied = skipped = missing = 0

    for i, t in enumerate(tracks, 1):
        src = t["path"]
        if not src.is_file():
            print(f"  ! fehlt: {src}")
            missing += 1
            continue

        base = f"{i:03d} - {src.name}" if numbered else src.name
        stem, ext = os.path.splitext(safe_name(base))
        cand, n = stem + ext, 2
        while cand.lower() in used:               # gleicher Dateiname aus anderem Ordner
            cand, n = f"{stem} ({n}){ext}", n + 1
        used.add(cand.lower())
        dst = folder / cand

        if needs_copy(src, dst):
            print(f"  + {cand}")
            if not dry:
                shutil.copy2(src, dst)
            copied += 1
        else:
            skipped += 1
        entries.append((cand, t))

    removed = 0
    if mirror and folder.exists():
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXT and f.name.lower() not in used:
                print(f"  - {f.name}")
                if not dry:
                    f.unlink()
                removed += 1

    # Playlist mit relativen Pfaden -> funktioniert auf dem Handy
    if not dry:
        lines = ["#EXTM3U"]
        for fname, t in entries:
            label = f"{t['artist']} - {t['title']}" if t["artist"] else t["title"]
            lines += [f"#EXTINF:{t['duration']},{label}", fname]
        (folder / f"{safe_name(name.split('/')[-1])}.m3u8").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    print(f"  = {copied} kopiert, {skipped} unverändert, {removed} entfernt, {missing} fehlen")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="rekordbox-Playlists in einen Ordner kopieren")
    ap.add_argument("source", type=Path, help="rekordbox-XML oder M3U8-Datei")
    ap.add_argument("-t", "--target", type=Path, help="Zielordner")
    ap.add_argument("-p", "--playlist", action="append", default=[],
                    help="Playlist-Name oder Pfad 'Ordner/Playlist' (mehrfach möglich, nur XML)")
    ap.add_argument("--all", action="store_true", help="alle Playlists (nur XML)")
    ap.add_argument("--list", action="store_true", help="Playlists in der XML auflisten")
    ap.add_argument("--mirror", action="store_true",
                    help="Tracks im Zielordner löschen, die nicht mehr in der Playlist sind")
    ap.add_argument("--numbered", action="store_true",
                    help="Dateien mit 001, 002 ... durchnummerieren (Reihenfolge bleibt erhalten)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    args = ap.parse_args()

    src = args.source.expanduser()
    if not src.is_file():
        sys.exit(f"Fehler: {src} nicht gefunden")

    is_xml = src.suffix.lower() == ".xml"
    playlists = read_xml(src) if is_xml else read_m3u(src)

    if args.list:
        for name, tracks in playlists.items():
            print(f"{len(tracks):5d}  {name}")
        return

    if not args.target:
        sys.exit("Fehler: Zielordner mit -t angeben")

    if is_xml:
        if args.all:
            selected = playlists
        elif args.playlist:
            selected = {}
            for wanted in args.playlist:
                hits = {k: v for k, v in playlists.items()
                        if k == wanted or k.split("/")[-1] == wanted}
                if not hits:
                    print(f"Warnung: Playlist '{wanted}' nicht gefunden (--list zeigt alle)")
                elif len(hits) > 1 and wanted not in playlists:
                    print(f"Warnung: '{wanted}' ist mehrdeutig, bitte vollen Pfad nutzen: "
                          + ", ".join(hits))
                    continue
                selected.update(hits)
        else:
            sys.exit("Fehler: Bei XML bitte --playlist NAME oder --all angeben (--list zeigt alle)")
    else:
        selected = playlists

    target = args.target.expanduser()
    for name, tracks in selected.items():
        print(f"\n[{name}]  ({len(tracks)} Tracks)")
        sync_playlist(name, tracks, target, args.mirror, args.numbered, args.dry_run)


if __name__ == "__main__":
    main()