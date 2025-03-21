#!/usr/bin/env python3

import os
import time
import re
import logging
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

# Configure logging
def setup_logging(log_file='spotify_playlist_adder.log'):
    """Set up logging to file and console without rotation or limits"""
    # Create logger
    logger = logging.getLogger('spotify_playlist_adder')
    logger.setLevel(logging.DEBUG)
    
    # Create file handler which logs all messages
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create console handler with the same log level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logging()

# Load environment variables from .env file
load_dotenv()

def setup_spotify_client():
    """
    Set up and return the Spotify client with proper authentication.
    
    Returns:
        Authenticated Spotify client
    """
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')
    
    if not client_id or not client_secret:
        logger.error("Missing Spotify API credentials. Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env file")
        raise ValueError(
            "Missing Spotify API credentials. Please set SPOTIFY_CLIENT_ID and "
            "SPOTIFY_CLIENT_SECRET in your .env file"
        )
    
    logger.info(f"Setting up Spotify client with redirect URI: {redirect_uri}")
    
    # Set up authentication with the required scopes
    # playlist-modify-public if your playlist is public
    # playlist-modify-private if your playlist is private
    scope = "playlist-modify-public playlist-modify-private"
    
    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope
    )
    
    return spotipy.Spotify(auth_manager=auth_manager)

def is_spotify_url(url):
    """
    Check if a URL is a Spotify track URL.
    
    Args:
        url: URL string to check
        
    Returns:
        bool: True if it's a Spotify URL, False otherwise
    """
    parsed = urlparse(url)
    return parsed.netloc == 'open.spotify.com' and 'track' in parsed.path

def extract_track_id_from_url(url):
    """
    Extract track ID from a Spotify URL.
    
    Args:
        url: Spotify track URL
        
    Returns:
        str: Spotify track ID
    """
    # URL format: https://open.spotify.com/track/1234567890abcdef
    match = re.search(r'track/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def extract_search_query_from_song(song):
    """
    Extract search query from song information.
    
    Args:
        song: Dictionary containing song information
        
    Returns:
        str: Search query for Spotify
    """
    # If we have artist and title from metadata, use those
    if song.get('artist') and song.get('title'):
        return f"track:{song['title']} artist:{song['artist']}"
    
    # Otherwise, try to extract from the file path
    file_path = song.get('path', '')
    if not file_path:
        return ''
        
    # Remove file extension and directory path
    filename = os.path.basename(file_path)
    filename_without_ext = os.path.splitext(filename)[0]
    
    # Common patterns: "Artist - Title" or "Title - Artist"
    parts = filename_without_ext.split(' - ', 1)
    
    if len(parts) == 2:
        # Assume artist - title format
        artist, title = parts
        return f"track:{title} artist:{artist}"
    
    # If we can't parse it, just use the filename as a search term
    return filename_without_ext

def process_m3u_batch(sp, file_path, playlist_id, failed_output='failed_tracks.txt', rate_limit=100, skip_failures=True):
    """
    Process a batch of songs from an M3U file and add them to a Spotify playlist.
    
    Args:
        sp: Authenticated Spotify client
        file_path: Path to the M3U batch file
        playlist_id: ID of the target Spotify playlist
        failed_output: Path to write failed tracks to (updated gradually)
        rate_limit: Maximum number of API calls per batch to avoid rate limiting
        skip_failures: Whether to skip tracks that couldn't be found
        
    Returns:
        tuple: (number of tracks added, number of tracks failed, list of failed tracks)
    """
    from m3u_splitter import parse_m3u
    
    tracks = parse_m3u(file_path)
    track_ids = []
    failed_tracks = []
    count = 0
    
    logger.info(f"Processing {len(tracks)} tracks from {file_path}...")
    
    # Open the failed tracks file in append mode to update it gradually
    failed_file = open(failed_output, 'a', encoding='utf-8')
    
    try:
        for track in tracks:
            count += 1
            
            # Check if we're hitting rate limits
            if count % rate_limit == 0:
                logger.info(f"Processed {count} tracks. Sleeping to avoid rate limits...")
                time.sleep(5)  # Sleep to avoid rate limits
            
            # Get the track path
            track_path = track.get('path', '')
            
            # Handle Spotify URLs directly
            if is_spotify_url(track_path):
                track_id = extract_track_id_from_url(track_path)
                if track_id:
                    track_ids.append(track_id)
                    logger.debug(f"Found Spotify track ID directly from URL: {track_id}")
                    continue
            
            # Handle file paths or other formats by searching
            try:
                query = extract_search_query_from_song(track)
                if not query:
                    # Write to failed tracks file immediately
                    failed_file.write(f"{track_path}\n")
                    failed_file.flush()  # Ensure it's written to disk
                    failed_tracks.append(track)  # Store the full track info for M3U generation
                    logger.warning(f"Could not generate search query for track: {track_path}")
                    continue
                    
                logger.debug(f"Searching for: {query}")
                results = sp.search(q=query, type='track', limit=1)
                
                if results['tracks']['items']:
                    track_id = results['tracks']['items'][0]['id']
                    track_ids.append(track_id)
                    logger.info(f"Found track: {track.get('artist', '')} - {track.get('title', '')}")
                else:
                    # Write to failed tracks file immediately
                    failed_file.write(f"{track_path}\n")
                    failed_file.flush()  # Ensure it's written to disk
                    failed_tracks.append(track)  # Store the full track info for M3U generation
                    logger.warning(f"Could not find track: {track.get('artist', '')} - {track.get('title', '')}")
            except Exception as e:
                # Write to failed tracks file immediately
                failed_file.write(f"{track_path}\n")
                failed_file.flush()  # Ensure it's written to disk
                failed_tracks.append(track)  # Store the full track info for M3U generation
                logger.error(f"Error processing track {track.get('artist', '')} - {track.get('title', '')}: {e}")
    
        # Add tracks to playlist in batches of 100 (Spotify API limit)
        successful = 0
        
        for i in range(0, len(track_ids), 100):
            batch = track_ids[i:i+100]
            try:
                sp.playlist_add_items(playlist_id, batch)
                successful += len(batch)
                logger.info(f"Added batch of {len(batch)} tracks to playlist")
                # Sleep to avoid rate limits
                time.sleep(2)
            except Exception as e:
                logger.error(f"Error adding batch to playlist: {e}")
        
        # Return the results from inside the try block
        return successful, len(failed_tracks), failed_tracks
    finally:
        # Make sure the file is closed even if an exception occurs
        if failed_file and not failed_file.closed:
            failed_file.close()

def create_failed_m3u(failed_tracks, output_path):
    """
    Create an M3U file from the failed tracks in the same format as the original M3U.
    
    Args:
        failed_tracks: List of track dictionaries that failed to be added
        output_path: Path to save the M3U file
        
    Returns:
        Path to the created M3U file
    """
    # Create the directory if it doesn't exist
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for track in failed_tracks:
            # Write the EXTINF line if we have metadata
            if track.get('metadata') or (track.get('artist') and track.get('title')):
                duration = track.get('duration', 0)
                metadata = track.get('metadata', '')
                
                # If no metadata but we have artist and title, create it
                if not metadata and track.get('artist') and track.get('title'):
                    metadata = f"{track['artist']} - {track['title']}"
                    
                f.write(f"#EXTINF:{duration},{metadata}\n")
            
            # Write the file path
            f.write(f"{track['path']}\n")
    
    logger.info(f"Created failed tracks M3U file: {output_path}")
    return output_path

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Add songs from M3U files to a Spotify playlist')
    parser.add_argument('--playlist-id', required=True, help='Spotify playlist ID to add songs to')
    parser.add_argument('--m3u-file', help='Original M3U file path - will look for batches in {filename}_batches folder')
    parser.add_argument('--batch-dir', help='Directory containing batch M3U files (alternative to --m3u-file)')
    parser.add_argument('--batch-file', help='Single M3U batch file to process (alternative to --m3u-file or --batch-dir)')
    parser.add_argument('--failed-output', default='failed_tracks.txt', help='File to save failed tracks to')
    parser.add_argument('--failed-m3u', default='failed_tracks.m3u', help='M3U file to save failed tracks to')
    parser.add_argument('--log-file', default='spotify_playlist_adder.log', help='Log file path')
    
    args = parser.parse_args()
    
    # Set up logging with the specified log file
    global logger
    logger = setup_logging(args.log_file)
    
    # Clear the failed tracks file at the start
    with open(args.failed_output, 'w', encoding='utf-8') as f:
        pass  # Just create/truncate the file
    
    try:
        logger.info("Starting Spotify Playlist Adder")
        sp = setup_spotify_client()
        logger.info("Successfully authenticated with Spotify")
        
        total_added = 0
        total_failed = 0
        all_failed_tracks = []
        
        if args.batch_file:
            # Process a single batch file
            logger.info(f"Processing single batch file: {args.batch_file}")
            added, failed, failed_tracks = process_m3u_batch(sp, args.batch_file, args.playlist_id, args.failed_output)
            total_added += added
            total_failed += failed
            all_failed_tracks.extend(failed_tracks)
        else:
            # Determine batch directory
            batch_dir = None
            if args.m3u_file:
                # Use the {filename}_batches folder in the same directory as the original M3U file
                input_dir = os.path.dirname(os.path.abspath(args.m3u_file))
                input_filename = os.path.basename(args.m3u_file)
                input_name_without_ext = os.path.splitext(input_filename)[0]
                batch_dir = os.path.join(input_dir, f"{input_name_without_ext}_batches")
                logger.info(f"Using batch directory derived from M3U file: {batch_dir}")
            elif args.batch_dir:
                # Use the specified batch directory
                batch_dir = args.batch_dir
                logger.info(f"Using specified batch directory: {batch_dir}")
            else:
                logger.error("Error: Either --m3u-file, --batch-dir, or --batch-file must be specified")
                return
            
            # Process all batch files in the directory
            import glob
            batch_files = sorted(glob.glob(os.path.join(batch_dir, '*.m3u')))
            
            if not batch_files:
                logger.error(f"No M3U files found in {batch_dir}")
                return
            
            logger.info(f"Found {len(batch_files)} batch files to process")
            
            for batch_file in batch_files:
                logger.info(f"Processing batch file: {batch_file}")
                added, failed, failed_tracks = process_m3u_batch(sp, batch_file, args.playlist_id, args.failed_output)
                total_added += added
                total_failed += failed
                all_failed_tracks.extend(failed_tracks)
        
        # Create an M3U file of the failed tracks
        if all_failed_tracks:
            create_failed_m3u(all_failed_tracks, args.failed_m3u)
            logger.info(f"Summary: Added {total_added} tracks to playlist, Failed to add {total_failed} tracks")
            logger.info(f"Failed tracks saved to {args.failed_output} and {args.failed_m3u}")
        else:
            logger.info(f"Summary: Added {total_added} tracks to playlist, No failed tracks")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

if __name__ == '__main__':
    main()
