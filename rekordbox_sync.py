#!/usr/bin/env python3
"""
rekordbox_sync.py – kopiert die Tracks von rekordbox-Playlists in einen Ordner,
z. B. um sie aufs Handy zu bringen (iTunes-Dateifreigabe, USB, Syncthing ...).

Was das Skript macht:
  * liest Playlists aus einem rekordbox-XML-Export (oder einer M3U8-Datei)
  * kopiert die Tracks pro Playlist in einen eigenen Unterordner
  * benennt die Kopien sauber als "Artist - Titel.ext"
  * bereinigt die Tags (Titel/Artist/Album) in den KOPIEN
      - Katalognummern wie [SUBB9605], (UYA009), "(FREE DOWNLOAD)" fliegen raus
      - WAV-Dateien bekommen die Infos aus rekordbox
  * optional: wandelt WAV/AIFF/FLAC in MP3 um (spart viel Platz, braucht ffmpeg)
  * legt pro Playlist eine .m3u8 mit relativen Pfaden an
  * merkt sich, was schon erledigt ist -> spätere Läufe kopieren nur Änderungen

Die Originaldateien werden NIE verändert oder verschoben.

Voraussetzungen:
  pip install mutagen          (für die Tags; ohne mutagen werden nur Dateinamen bereinigt)
  ffmpeg im PATH               (nur für --convert; Windows: winget install ffmpeg)

Eingabe:
  rekordbox: Datei > Bibliothek > "Sammlung im XML-Format exportieren"

Beispiele:
  python rekordbox_sync.py lib.xml --list
  python rekordbox_sync.py lib.xml -p "100% Jungle" -t "C:\\Users\\pasca\\Music\\Handy" --mirror
  python rekordbox_sync.py lib.xml -p "100% Jungle" -t Handy --mirror --convert mp3
  python rekordbox_sync.py lib.xml --all -t Handy -n          (Testlauf, ändert nichts)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

AUDIO_EXT = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac",
             ".alac", ".ogg", ".mp4"}
CONVERTIBLE = {".wav", ".aif", ".aiff", ".flac"}      # verlustfrei -> lohnt sich
STATE_FILE = ".rekordbox_sync.json"


# =========================================================================== #
# Einlesen
# =========================================================================== #
def location_to_path(location: str) -> Path:
    """file://localhost/C:/Musik/a%20b.mp3  ->  C:/Musik/a b.mp3"""
    path = unquote(urlparse(location).path)
    if re.match(r"^/[A-Za-z]:/", path):               # Windows-Laufwerksbuchstabe
        path = path[1:]
    return Path(path)


def read_xml(xml_file: Path) -> dict:
    """Gibt {"Ordner/Playlist": [track, ...]} zurück."""
    root = ET.parse(xml_file).getroot()
    collection = root.find("COLLECTION")
    if collection is None:
        sys.exit("Fehler: Keine <COLLECTION> in der XML – ist das ein rekordbox-Export?")

    by_id, by_loc = {}, {}
    for t in collection.findall("TRACK"):
        track = {
            "path": location_to_path(t.get("Location", "")),
            "artist": t.get("Artist", ""),
            "title": t.get("Name", ""),
            "album": t.get("Album", ""),
            "duration": int(float(t.get("TotalTime", "0") or 0)),
        }
        by_id[t.get("TrackID")] = track
        by_loc[t.get("Location")] = track

    playlists = {}

    def walk(node, prefix):
        for child in node.findall("NODE"):
            full = f"{prefix}/{child.get('Name', '')}" if prefix else child.get("Name", "")
            if child.get("Type") == "0":              # Ordner
                walk(child, full)
            else:                                     # Playlist
                lookup = by_id if child.get("KeyType", "0") == "0" else by_loc
                playlists[full] = [lookup[e.get("Key")] for e in child.findall("TRACK")
                                   if e.get("Key") in lookup]

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
            try:
                dur = int(float(dur))
            except ValueError:
                dur = 0
            info = {"duration": dur, "artist": artist if title else "", "title": title or label}
        elif not line.startswith("#"):
            p = location_to_path(line) if line.startswith("file:") else Path(line)
            if not p.is_absolute():
                p = m3u_file.parent / p
            tracks.append({"path": p, "artist": "", "title": p.stem, "album": "",
                           "duration": 0, **info})
            info = {}
    return {m3u_file.stem: tracks}


# =========================================================================== #
# Namen & Tags bereinigen
# =========================================================================== #
# Katalognummern am Ende: "-SUBB9605-", "(UYA009)", "[SUBB9605]"
CATALOG_RE = re.compile(r"\s*[\(\[\-]\s*[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*\s*[\)\]\-]\s*$")
# Werbe-Anhängsel: "(FREE DOWNLOAD)", "[Free DL]", "(Bandcamp Exclusive)" ...
JUNK_RE = re.compile(r"\s*[\(\[]\s*(free\s*(download|dl)|bandcamp( exclusive| edition)?|"
                     r"out now|preview|promo)\s*[\)\]]", re.I)
# Bandcamp-Dateiname: "Artist - Album - 07 Titel"
BANDCAMP_RE = re.compile(r"^(?P<artist>.+?) - .+ - \d{1,3}\.? (?P<title>.+)$")
# Tracknummer vorne: "02. Titel", "07 - Titel", "03 Titel"
TRACKNO_RE = re.compile(r"^\d{1,3}(\.|\s-)?\s+")


def tidy(text: str) -> str:
    text = JUNK_RE.sub("", text)
    while CATALOG_RE.search(text):
        text = CATALOG_RE.sub("", text)
    text = re.sub(r"([\(\[])\s+", r"\1", text)        # "( Remix )" -> "(Remix)"
    text = re.sub(r"\s+([\)\]])", r"\1", text)
    if " " not in text:                               # "Artist_-_Titel", nicht "F_ck"
        text = text.replace("_", " ")
    return re.sub(r"\s{2,}", " ", text).strip(" -")


def clean_from_filename(stem: str) -> str:
    m = BANDCAMP_RE.match(stem)
    if m:
        title = m["title"]
        # Compilation: Titel enthält schon "Artist - Titel"
        stem = title if " - " in title else f"{m['artist']} - {title}"
    return TRACKNO_RE.sub("", stem)


def clean_meta(track: dict, src: Path) -> dict:
    """Bereinigte Werte für Artist / Titel / Album."""
    artist = track.get("artist", "").strip()
    title = track.get("title", "").strip()
    album = track.get("album", "").strip()

    if not title or title == src.stem:                # kein Titel-Tag -> aus Dateinamen raten
        guess = clean_from_filename(src.stem)
        if not artist and " - " in guess:
            artist, title = guess.split(" - ", 1)
        else:
            title = guess

    # "Subjects" / "Subjects - Kookaburra" -> Titel "Kookaburra"
    if artist and title.lower().startswith(artist.lower() + " - "):
        title = title[len(artist) + 3:]
    # Label-Compilation: Artist "Monkey Business", Titel "DJ K & Bman - The Void",
    # Album "Monkey Business And Friends 8"  -> Artist "DJ K & Bman", Titel "The Void"
    elif " - " in title and artist and artist.lower() in album.lower():
        artist, title = title.split(" - ", 1)

    return {"artist": tidy(artist), "title": tidy(title) or src.stem, "album": album}


def safe_name(name: str) -> str:
    """Entfernt Zeichen, die auf Windows/iOS/Android/FAT nicht erlaubt sind."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "_"


def basename_for(meta: dict) -> str:
    name = f"{meta['artist']} - {meta['title']}" if meta["artist"] else meta["title"]
    return safe_name(name[:150].strip())


def write_tags(path: Path, meta: dict) -> str:
    """Schreibt Titel/Artist/Album in die Datei. Gibt '' oder eine Warnung zurück."""
    try:
        import mutagen
        from mutagen.id3 import TIT2, TPE1, TALB
        from mutagen.mp4 import MP4
    except ImportError:
        return "mutagen fehlt"
    try:
        f = mutagen.File(path)
        if f is None:
            return "Format unbekannt"
        if f.tags is None:
            f.add_tags()
        ext = path.suffix.lower()
        values = {k: v for k, v in meta.items() if v}

        if isinstance(f, MP4):                                        # .m4a / ALAC
            for key, frame in (("title", "\xa9nam"), ("artist", "\xa9ART"), ("album", "\xa9alb")):
                if key in values:
                    f.tags[frame] = [values[key]]
        elif ext in (".flac", ".ogg"):                                # Vorbis-Kommentare
            for key in ("title", "artist", "album"):
                if key in values:
                    f.tags[key] = [values[key]]
        else:                                                         # ID3: mp3, aiff, wav
            for key, frame in (("title", TIT2), ("artist", TPE1), ("album", TALB)):
                if key in values:
                    f.tags.setall(frame.__name__, [frame(encoding=3, text=values[key])])
        f.save()
        return ""
    except Exception as e:                                            # Tags nie fatal
        return f"Tags nicht geschrieben: {e}"


# =========================================================================== #
# Kopieren / Umwandeln
# =========================================================================== #
def convert_mp3(src: Path, dst: Path, bitrate: str) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
           "-map", "0:a:0", "-map", "0:v?", "-c:v", "copy",          # Cover mitnehmen
           "-c:a", "libmp3lame", "-b:a", bitrate,
           "-map_metadata", "0", "-id3v2_version", "3", str(dst)]
    subprocess.run(cmd, check=True)


def load_state(target: Path) -> dict:
    try:
        return json.loads((target / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sync_playlist(name, tracks, target, state, opt):
    folder = target / safe_name(name.replace("/", " - "))
    if not opt.dry_run:
        folder.mkdir(parents=True, exist_ok=True)
    pl_state = state.setdefault(name, {})
    new_state = {}

    used, entries = set(), []
    stats = dict(copied=0, skipped=0, removed=0, missing=0)

    for i, t in enumerate(tracks, 1):
        src = t["path"]
        if not src.is_file():
            print(f"  ! fehlt: {src}")
            stats["missing"] += 1
            continue

        meta = t if opt.raw_names else clean_meta(t, src)
        convert = opt.convert and src.suffix.lower() in CONVERTIBLE
        ext = ".mp3" if convert else src.suffix.lower()
        stem = src.stem if opt.raw_names else basename_for(meta)
        if opt.numbered:
            stem = f"{i:03d} - {stem}"

        cand, n = stem + ext, 2
        while cand.lower() in used:                   # gleicher Name doppelt
            cand, n = f"{stem} ({n}){ext}", n + 1
        used.add(cand.lower())
        dst = folder / cand

        st = src.stat()
        fingerprint = {"src": str(src), "size": st.st_size, "mtime": int(st.st_mtime),
                       "convert": opt.bitrate if convert else None,
                       "tags": None if (opt.raw_names or opt.no_tags) else
                               [meta["artist"], meta["title"], meta["album"]]}
        new_state[cand] = fingerprint

        if dst.exists() and pl_state.get(cand) == fingerprint:
            stats["skipped"] += 1
        else:
            print(f"  + {cand}" + ("   (-> mp3)" if convert else ""))
            stats["copied"] += 1
            if not opt.dry_run:
                try:
                    if convert:
                        convert_mp3(src, dst, opt.bitrate)
                    else:
                        shutil.copy2(src, dst)
                except (OSError, subprocess.CalledProcessError) as e:
                    print(f"    ! Fehler: {e}")
                    new_state.pop(cand, None)
                    continue
                if fingerprint["tags"]:
                    warn = write_tags(dst, meta)
                    if warn:
                        print(f"    ! {warn}")
        entries.append((cand, meta, t["duration"]))

    if opt.mirror and folder.exists():
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXT and f.name.lower() not in used:
                print(f"  - {f.name}")
                stats["removed"] += 1
                if not opt.dry_run:
                    f.unlink()

    if not opt.dry_run:
        lines = ["#EXTM3U"]
        for fname, meta, dur in entries:
            label = f"{meta['artist']} - {meta['title']}" if meta["artist"] else meta["title"]
            lines += [f"#EXTINF:{dur},{label}", fname]
        (folder / f"{safe_name(name.split('/')[-1])}.m3u8").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        state[name] = new_state

    print("  = {copied} kopiert, {skipped} unverändert, {removed} entfernt, "
          "{missing} fehlen".format(**stats))


# =========================================================================== #
def main():
    ap = argparse.ArgumentParser(description="rekordbox-Playlists in einen Ordner kopieren")
    ap.add_argument("source", type=Path, help="rekordbox-XML oder M3U8-Datei")
    ap.add_argument("-t", "--target", type=Path, help="Zielordner")
    ap.add_argument("-p", "--playlist", action="append", default=[],
                    help="Playlist-Name oder 'Ordner/Playlist' (mehrfach möglich, nur XML)")
    ap.add_argument("--all", action="store_true", help="alle Playlists (nur XML)")
    ap.add_argument("--list", action="store_true", help="Playlists in der XML auflisten")
    ap.add_argument("--mirror", action="store_true",
                    help="Dateien im Zielordner löschen, die nicht mehr in der Playlist sind")
    ap.add_argument("--numbered", action="store_true",
                    help="Dateien mit 001, 002 ... durchnummerieren (Reihenfolge bleibt)")
    ap.add_argument("--convert", choices=["mp3"],
                    help="WAV/AIFF/FLAC beim Kopieren in MP3 umwandeln (braucht ffmpeg)")
    ap.add_argument("--bitrate", default="320k", help="MP3-Bitrate für --convert (Standard 320k)")
    ap.add_argument("--no-tags", action="store_true", help="Tags in den Kopien nicht anfassen")
    ap.add_argument("--raw-names", action="store_true",
                    help="Original-Dateinamen und -Tags behalten (keine Bereinigung)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    opt = ap.parse_args()

    src = opt.source.expanduser()
    if not src.is_file():
        sys.exit(f"Fehler: {src} nicht gefunden")

    is_xml = src.suffix.lower() == ".xml"
    playlists = read_xml(src) if is_xml else read_m3u(src)

    if opt.list:
        for name, tracks in playlists.items():
            print(f"{len(tracks):5d}  {name}")
        return
    if not opt.target:
        sys.exit("Fehler: Zielordner mit -t angeben")

    if opt.convert and not shutil.which("ffmpeg"):
        sys.exit("Fehler: --convert braucht ffmpeg (Windows: 'winget install ffmpeg', "
                 "danach neues Terminal öffnen)")
    if not (opt.no_tags or opt.raw_names):
        try:
            import mutagen  # noqa: F401
        except ImportError:
            print("Hinweis: 'pip install mutagen' fehlt – Tags werden nicht bereinigt, "
                  "nur Dateinamen.\n")
            opt.no_tags = True

    if is_xml:
        if opt.all:
            selected = playlists
        elif opt.playlist:
            selected = {}
            for wanted in opt.playlist:
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
            sys.exit("Fehler: Bei XML bitte --playlist NAME oder --all angeben "
                     "(--list zeigt alle)")
    else:
        selected = playlists

    target = opt.target.expanduser()
    state = load_state(target)
    for name, tracks in selected.items():
        print(f"\n[{name}]  ({len(tracks)} Tracks)")
        sync_playlist(name, tracks, target, state, opt)

    if not opt.dry_run:
        target.mkdir(parents=True, exist_ok=True)
        (target / STATE_FILE).write_text(json.dumps(state, indent=1, ensure_ascii=False),
                                         encoding="utf-8")


if __name__ == "__main__":
    main()
