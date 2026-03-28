import json
import time
import argparse
import re
import lyricsgenius

GENIUS_TOKEN = "GjjUC7uX2Nx8gfM3LbEW-rneORyOxs1ntRAAnKxsxEVq-OOK-iaCygsENIQTcL7K"

def clean_lyrics(text: str) -> str:
    text = re.sub(r'\d+Embed$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(EmbedShare|URLCopyEmbedCopy).*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def load_songs(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("tracks", "items", "songs"):
            if key in data and isinstance(data[key], list):
                return data[key]
    raise ValueError(
        "Unrecognized JSON shape. Expected a list of songs or a dict with "
        "a 'tracks'/'items'/'songs' key."
    )

def extract_name_and_artist(song: dict) -> tuple[str | None, str | None]:
    name = song.get("song_name") or song.get("name") or song.get("title")

    artists = song.get("artists", [])
    if artists and isinstance(artists[0], dict):
        artist = artists[0].get("name")
    elif artists and isinstance(artists[0], str):
        artist = artists[0]
    else:
        artist = song.get("artist") or song.get("artist_name")

    return name, artist

def fetch_lyrics(genius: lyricsgenius.Genius, name: str, artist: str | None) -> str | None:
    try:
        song = genius.search_song(name, artist or "")
        if song and song.lyrics:
            return clean_lyrics(song.lyrics)
    except Exception as e:
        print(f"    [!] Genius error for '{name}': {e}")
    return None

def enrich(input_path: str, output_path: str, delay: float = 0.5):
    songs = load_songs(input_path)
    print(f"Loaded {len(songs)} songs from {input_path}")

    genius = lyricsgenius.Genius(
        GENIUS_TOKEN,
        skip_non_songs=True,
        excluded_terms=["(Remix)", "(Live)"],
        remove_section_headers=False,
        verbose=False,
        retries=2,
    )

    results = []
    for i, song in enumerate(songs):
        name, artist = extract_name_and_artist(song)

        if not name:
            print(f"[{i+1}/{len(songs)}] Skipping — no track name found")
            results.append({**song, "lyrics": None, "lyrics_status": "missing_name"})
            continue

        label = f"'{name}'" + (f" by {artist}" if artist else "")
        print(f"[{i+1}/{len(songs)}] Fetching lyrics for {label} ...")

        lyrics = fetch_lyrics(genius, name, artist)

        if lyrics:
            print(f"    ✓ Found ({len(lyrics.split())} words)")
            status = "ok"
        else:
            print(f"    ✗ Not found")
            status = "not_found"

        results.append({
            **song,
            "lyrics": lyrics,
            "lyrics_status": status,
        })

        time.sleep(delay)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    found = sum(1 for r in results if r["lyrics_status"] == "ok")
    print(f"\nDone. {found}/{len(songs)} songs matched. Saved to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich Spotify JSON with Genius lyrics")
    parser.add_argument("--input",  required=True, help="Path to Spotify JSON file")
    parser.add_argument("--output", required=True, help="Path for output JSON file")
    parser.add_argument("--delay",  type=float, default=0.5,
                        help="Seconds between Genius requests (default 0.5)")
    args = parser.parse_args()
    enrich(args.input, args.output, args.delay)