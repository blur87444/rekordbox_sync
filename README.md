# rekordbox-sync

Kopiert Tracks aus rekordbox-Playlists in einen Ordner, z. B. um sie aufs Handy zu bringen
(iTunes-Dateifreigabe, USB, Syncthing ...).

- liest Playlists aus einem rekordbox-XML-Export oder einer M3U8-Datei
- benennt die Kopien sauber als `Artist - Titel.ext`
- bereinigt Tags (Titel/Artist/Album) in den **Kopien**: Katalognummern wie `[SUBB9605]`,
  `(FREE DOWNLOAD)` usw. fliegen raus, WAVs bekommen die Infos aus rekordbox
- wandelt optional WAV/AIFF/FLAC in MP3 um (`--convert mp3`, braucht ffmpeg)
- legt pro Playlist eine `.m3u8` mit relativen Pfaden an
- inkrementell: spätere Läufe kopieren nur neue/geänderte Tracks

Die Originaldateien werden nie verändert oder verschoben.

## Installation

```powershell
pip install -r requirements.txt
winget install ffmpeg        # nur für --convert
```

## Benutzung

In rekordbox: *Datei → Bibliothek → Sammlung im XML-Format exportieren*.

```powershell
python rekordbox_sync.py lib.xml --list
python rekordbox_sync.py lib.xml -p "100% Jungle" -t "C:\Users\me\Music\Handy" --mirror --convert mp3
```

| Option | Bedeutung |
|---|---|
| `-p NAME` | Playlist (mehrfach möglich, `Ordner/Playlist` für verschachtelte) |
| `--all` | alle Playlists |
| `--list` | Playlists auflisten |
| `--mirror` | Dateien im Ziel löschen, die nicht mehr in der Playlist sind |
| `--convert mp3` | WAV/AIFF/FLAC → MP3 (`--bitrate`, Standard 320k) |
| `--numbered` | Dateien durchnummerieren (001, 002 ...) |
| `--no-tags` | Tags nicht anfassen |
| `--raw-names` | Originalnamen und -tags behalten |
| `-n` | Testlauf, ändert nichts |
