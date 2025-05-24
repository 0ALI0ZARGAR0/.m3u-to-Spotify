# Spotify Playlist Manager

This project helps you split large M3U playlists into smaller batches of 100 songs each, and then upload those songs to a specified Spotify playlist.
This was a need of mine I came across and implemented on a weekend morning.

## Setup

1. Install dependencies:

   ```
   pip install -r requirements.txt
   ```
   
   > 🚀 Shoutout: Try [uv](https://github.com/astral-sh/uv) for extremely fast installs — `uv pip install -r requirements.txt`

2. Set up Spotify Developer credentials:

   - Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Create a new app
   - Note your Client ID and Client Secret
   - Add `http://localhost:8888/callback` to the Redirect URIs in your app settings

3. Create a `.env` file based on the `.env.example` template and fill in your Spotify credentials:
   ```
   cp .env.example .env
   # Edit .env with your text editor
   ```

## Usage

### Step 1: Split your M3U playlist into batches

```
python m3u_splitter.py path/to/your/playlist.m3u -o batches -s 100
```

Options:

- `-o, --output-dir`: Directory to save batch files (default: "batches")
- `-s, --batch-size`: Number of songs per batch (default: 200)
- `-n, --base-name`: Base name for batch files (default: "playlist_batch")

### Step 2: Get your Spotify playlist ID

1. Open your playlist in Spotify
2. Click the three dots (•••) > Share > Copy Spotify URI
3. The playlist ID is the part after `spotify:playlist:`

Alternatively, from the URL `https://open.spotify.com/playlist/abcdef123456`, the ID would be `abcdef123456`.

### Step 3: Add songs to your Spotify playlist

```
python spotify_playlist_adder.py --playlist-id YOUR_PLAYLIST_ID --batch-dir batches
```

To process just a single batch file:

```
python spotify_playlist_adder.py --playlist-id YOUR_PLAYLIST_ID --batch-file batches/playlist_batch_1.m3u
```

## Notes

- The script will attempt to match songs by artist and title when they're not Spotify URLs
- The first time you run the script, it will open a browser window for authentication
- Your Spotify access token will be cached locally for future use
- The script handles API rate limiting to avoid errors
- Failed tracks will be saved to `logs/failed_tracks.txt`
- The script parses the .m3u as what my .m3u files looked like, you may need to update the parser script to match your .m3u format.
