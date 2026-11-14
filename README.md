🇬🇧 English | [🇩🇪 Deutsch](README.de.md)

# rekordbox-sync

> [!WARNING]
> **This project is 100% AI-generated.** All code and documentation were written by an AI
> (Claude by Anthropic). The script was only tested with sample files, not with a real
> rekordbox library. Use it at your own risk and try a dry run (`-n`) first.
> Your original files are never modified, only copies are written.

Copies the tracks of rekordbox playlists into a folder, e.g. to get them onto your phone
(iTunes file sharing, USB, Syncthing ...).

- reads playlists from a rekordbox XML export or an M3U8 file
- names the copies cleanly as `Artist - Title.ext`
- cleans up the tags (title/artist/album) of the **copies**: catalogue numbers such as
  `[SUBB9605]`, `(FREE DOWNLOAD)` etc. are removed, WAV files get the metadata from rekordbox
- optionally converts WAV/AIFF/FLAC to MP3 (`--convert mp3`, requires ffmpeg)
- creates an `.m3u8` per playlist with relative paths
- incremental: later runs only copy new or changed tracks

Your original files are never modified or moved.

> [!NOTE]
> The command-line output and help texts of the script are currently in German.

## Installation

```powershell
pip install -r requirements.txt
winget install ffmpeg        # only needed for --convert
```

## Usage

In rekordbox: *File → Library → Export Collection in xml format*.

```powershell
python rekordbox_sync.py lib.xml --list
python rekordbox_sync.py lib.xml -p "100% Jungle" -t "C:\Users\me\Music\Phone" --mirror --convert mp3
```

| Option | Meaning |
|---|---|
| `-p NAME` | playlist (can be repeated, use `Folder/Playlist` for nested ones) |
| `--all` | all playlists |
| `--list` | list playlists |
| `--mirror` | delete files in the target that are no longer in the playlist |
| `--convert mp3` | WAV/AIFF/FLAC → MP3 (`--bitrate`, default 320k) |
| `--numbered` | number the files (001, 002 ...) to keep the order |
| `--no-tags` | leave tags untouched |
| `--raw-names` | keep original file names and tags |
| `-n` | dry run, changes nothing |

## Roadmap / ideas

- **Push tracks directly into the iPhone app [My Own Music](https://apps.apple.com/app/id6755663081)**
  Right now the copied tracks have to be dragged into the app by hand
  (iTunes → device → File Sharing → My Own Music). The idea: a new option such as
  `--push-ios` sends the synced folder straight into the app's documents via USB, with no
  clicking in iTunes. `--mirror` would then also remove tracks from the phone that were
  removed from the playlist.
  *Possible approach (not tested yet):* [`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3),
  which can access the documents folder of apps that support iTunes file sharing
  (house_arrest/AFC service). On Windows this needs Apple's device driver, which comes with
  iTunes or the "Apple Devices" app.
- English command-line output, or switch automatically based on the system language.

Ideas, feedback and pull requests are welcome!
