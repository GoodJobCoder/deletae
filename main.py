from dotenv import load_dotenv
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from openai import OpenAI
import json
from collections import Counter

load_dotenv()

# === CREDENTIALS ===
SPOTIFY_CLIENT_ID     = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI  = 'http://127.0.0.1:8888/callback'
OPENAI_API_KEY        = os.getenv('OPENAI_API_KEY')  # get a new one from platform.openai.com/api-keys

# === SPOTIFY AUTH ===
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope="user-top-read",
    open_browser=True       # opens browser for auth automatically like before
))

client = OpenAI(api_key=OPENAI_API_KEY)

# === 1. FETCH TOP TRACKS ===
def get_top_tracks(limit=50, time_range='medium_term'):
    results = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    print(f"Fetched {len(results['items'])} top tracks.")
    return results['items']

# === 2. BULK ANALYSIS WITH OPENAI (genres included — Spotify perms too flaky) ===
def get_openai_features_bulk(tracks):
    track_list = "\n".join([
        f"{i+1}. \"{t['name']}\" by {t['artists'][0]['name']}"
        for i, t in enumerate(tracks)
    ])

    prompt = f"""You are a professional music analyst. For each song listed, estimate the following features based on your knowledge of the track.

For each song return:
- song_name: the name of the song
- energy (0.0–1.0): intensity and power
- valence (0.0–1.0): musical positivity/happiness
- tempo (integer BPM)
- danceability (0.0–1.0): rhythmic suitability for dancing
- acousticness (0.0–1.0): 0=fully electronic, 1=fully acoustic
- instrumentalness (0.0–1.0): 0=vocal-heavy, 1=fully instrumental
- key_mode: "major" or "minor"
- genre: top-level genre (e.g. "hip-hop", "pop", "rock", "r&b", "electronic")
- subgenre: specific subgenre (e.g. "bedroom pop", "trap", "indie folk", "hyperpop")
- primary_instrument: dominant instrument (e.g. "guitar", "synth", "piano", "drums")
- lyrical_theme: dominant theme (e.g. "love", "heartbreak", "party", "introspective", "rebellion", "nostalgia")
- vocal_style: (e.g. "melodic", "rap", "breathy", "powerful", "none")
- era: decade of sound aesthetic (e.g. "80s", "90s", "2010s", "2020s")

Songs:
{track_list}

CRITICAL: Return ONLY a raw JSON array of {len(tracks)} objects, one per song. Start with [ and end with ]. No markdown, no code fences, no wrapping object."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a professional music analyst. Always return a pure JSON array with no markdown or explanation."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Extract array from first [ to last ]
    start = raw.find("[")
    end   = raw.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON array found in response:\n{raw}")

    parsed = json.loads(raw[start:end])

    if not isinstance(parsed, list):
        raise ValueError(f"Expected a list, got {type(parsed)}")

    print(f"Successfully analyzed {len(parsed)} tracks.")
    return parsed

# === 3. BUILD TASTE PROFILE ===
def build_taste_profile(ai_features):
    # Filter out any non-dict entries just in case
    ai_features = [f for f in ai_features if isinstance(f, dict)]
    if not ai_features:
        raise ValueError("No valid track features returned from OpenAI")
    # ... rest of function unchanged
    numeric_keys = ['energy', 'valence', 'tempo', 'danceability', 'acousticness', 'instrumentalness']
    averages = {}
    for key in numeric_keys:
        vals = [f[key] for f in ai_features if f.get(key) is not None]
        averages[key] = round(sum(vals) / len(vals), 4) if vals else 0

    genres       = [f.get('genre') for f in ai_features if f.get('genre')]
    subgenres    = [f.get('subgenre') for f in ai_features if f.get('subgenre')]
    instruments  = [f.get('primary_instrument') for f in ai_features if f.get('primary_instrument')]
    themes       = [f.get('lyrical_theme') for f in ai_features if f.get('lyrical_theme')]
    vocal_styles = [f.get('vocal_style') for f in ai_features if f.get('vocal_style')]
    eras         = [f.get('era') for f in ai_features if f.get('era')]
    modes        = [f.get('key_mode') for f in ai_features if f.get('key_mode')]

    return {
        "audio_averages":   averages,
        "top_genres":       Counter(genres).most_common(5),
        "top_subgenres":    Counter(subgenres).most_common(3),
        "top_instruments":  Counter(instruments).most_common(3),
        "top_themes":       Counter(themes).most_common(3),
        "top_vocal_styles": Counter(vocal_styles).most_common(2),
        "dominant_era":     Counter(eras).most_common(1)[0][0] if eras else "2020s",
        "dominant_mode":    Counter(modes).most_common(1)[0][0] if modes else "major",
    }

# === 4. BUILD MUSIC GENERATION PROMPT ===
def build_music_gen_prompt(profile):
    avgs        = profile['audio_averages']
    genres      = ', '.join([g[0] for g in profile['top_genres'][:3]]) or "pop"
    subgenres   = ', '.join([g[0] for g in profile['top_subgenres'][:2]])
    instruments = ', '.join([i[0] for i in profile['top_instruments'] if i[0]])
    themes      = ', '.join([t[0] for t in profile['top_themes'][:2]])
    vocal       = profile['top_vocal_styles'][0][0] if profile['top_vocal_styles'] else 'melodic'

    energy_desc   = "high-energy" if avgs['energy'] > 0.6 else "mellow"
    mood_desc     = "upbeat and euphoric" if avgs['valence'] > 0.6 else ("bittersweet" if avgs['valence'] > 0.4 else "melancholic and moody")
    dance_desc    = "danceable and groovy" if avgs['danceability'] > 0.6 else "flowing and non-rhythmic"
    acoustic_desc = "acoustic and organic" if avgs['acousticness'] > 0.5 else "polished and electronic"
    vocal_desc    = "instrumental" if avgs['instrumentalness'] > 0.4 else f"{vocal} vocals"

    return (
        f"Create a {energy_desc}, {mood_desc} song blending {genres} ({subgenres}). "
        f"Tempo: ~{int(avgs['tempo'])} BPM, {dance_desc}. "
        f"Sound: {acoustic_desc}. "
        f"Featured instruments: {instruments}. "
        f"Vocals: {vocal_desc}. "
        f"Lyrical themes: {themes}. "
        f"Key: {profile['dominant_mode']}. "
        f"Era aesthetic: {profile['dominant_era']}."
    )

# === MAIN ===
print("Fetching Spotify top tracks...")
tracks = get_top_tracks(limit=50)

print("Analyzing all tracks with OpenAI...")
ai_features = get_openai_features_bulk(tracks)

profile = build_taste_profile(ai_features)

print("\n=== TASTE PROFILE ===")
print(json.dumps(profile, indent=2, default=str))

prompt = build_music_gen_prompt(profile)
print("\n=== MUSIC GENERATION PROMPT ===")
print(prompt)

# === SAVE TO JSON ===
import os
output = {
    "tracks": ai_features,
    "taste_profile": profile,
    "music_generation_prompt": prompt
}

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_profile.json")
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nSaved to {output_path}")