#!/usr/bin/env python3

import logging
import os
import time
from collections import defaultdict

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

# Configure logging
def setup_logging(log_file='logs/spotify_playlist_deduplicator.log'):
    """Set up logging to file and console without rotation or limits"""
    # Create logger
    logger = logging.getLogger('spotify_playlist_deduplicator')
    logger.setLevel(logging.DEBUG)
    
    # Create file handler which logs all messages
    os.makedirs('logs', exist_ok=True)
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
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
    
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

def get_playlist_tracks(sp, playlist_id):
    """
    Get all tracks from a Spotify playlist.
    
    Args:
        sp: Authenticated Spotify client
        playlist_id: ID of the Spotify playlist
        
    Returns:
        List of track items from the playlist
    """
    results = sp.playlist_items(playlist_id)
    tracks = results['items']
    
    # Spotify paginates results, so we need to get all pages
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    
    logger.info(f"Retrieved {len(tracks)} tracks from playlist")
    return tracks

def find_duplicates(tracks):
    """
    Find duplicate tracks in a list of Spotify track items.
    
    Args:
        tracks: List of track items from a Spotify playlist
        
    Returns:
        tuple: (dict of unique tracks by ID, list of duplicate track positions to remove)
    """
    track_ids = {}
    duplicates = []
    
    for position, item in enumerate(tracks):
        # Skip None items or items without track info
        if not item or 'track' not in item or not item['track']:
            continue
            
        track = item['track']
        track_id = track['id']
        
        if track_id in track_ids:
            # This is a duplicate
            logger.debug(f"Found duplicate track: {track['name']} by {', '.join([artist['name'] for artist in track['artists']])}")
            duplicates.append(position)
        else:
            # First time seeing this track
            track_ids[track_id] = {
                'position': position,
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']]
            }
    
    logger.info(f"Found {len(duplicates)} duplicate tracks out of {len(tracks)} total tracks")
    return track_ids, duplicates

def remove_duplicates(sp, playlist_id, duplicate_positions, tracks):
    """
    Remove duplicate tracks from a Spotify playlist.
    
    Args:
        sp: Authenticated Spotify client
        playlist_id: ID of the Spotify playlist
        duplicate_positions: List of track positions to remove
        tracks: List of track items from the playlist
        
    Returns:
        int: Number of tracks removed
    """
    if not duplicate_positions:
        logger.info("No duplicates to remove")
        return 0
    
    # Sort positions in descending order to avoid index shifting when removing tracks
    positions_to_remove = sorted(duplicate_positions, reverse=True)
    
    # We need to get the track URIs for the positions we want to remove
    tracks_to_remove = []
    for pos in positions_to_remove:
        if 0 <= pos < len(tracks) and tracks[pos].get('track') and tracks[pos]['track'].get('uri'):
            track_uri = tracks[pos]['track']['uri']
            tracks_to_remove.append({"uri": track_uri, "positions": [pos]})
    
    if not tracks_to_remove:
        logger.error("No valid tracks to remove")
        return 0
    
    # Process in batches to avoid hitting rate limits
    batch_size = 100
    batches = [tracks_to_remove[i:i + batch_size] for i in range(0, len(tracks_to_remove), batch_size)]
    
    removed_count = 0
    for batch in batches:
        try:
            sp.playlist_remove_specific_occurrences_of_items(playlist_id, batch)
            removed_count += len(batch)
            logger.info(f"Removed batch of {len(batch)} duplicate tracks")
            
            # Sleep to avoid rate limits if there are more batches
            if len(batches) > 1:
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error removing tracks: {e}")
    
    return removed_count

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Remove duplicate tracks from a Spotify playlist')
    parser.add_argument('playlist_id', help='Spotify playlist ID or URL')
    parser.add_argument('--dry-run', action='store_true', help='Only detect duplicates without removing them')
    parser.add_argument('--log-file', default='logs/spotify_playlist_deduplicator.log', help='Log file path')
    
    args = parser.parse_args()
    
    # Set up logging with the specified log file
    logger = setup_logging(args.log_file)
    
    # Extract playlist ID from URL if needed
    playlist_id = args.playlist_id
    if 'spotify.com/playlist/' in playlist_id:
        playlist_id = playlist_id.split('playlist/')[1].split('?')[0]
    
    logger.info(f"Starting Spotify Playlist Deduplicator")
    logger.info(f"Target playlist ID: {playlist_id}")
    
    try:
        # Set up Spotify client
        sp = setup_spotify_client()
        
        # Get playlist details
        playlist = sp.playlist(playlist_id)
        playlist_name = playlist['name']
        logger.info(f"Working with playlist: {playlist_name}")
        
        # Get all tracks from the playlist
        tracks = get_playlist_tracks(sp, playlist_id)
        
        # Find duplicate tracks
        unique_tracks, duplicate_positions = find_duplicates(tracks)
        
        if duplicate_positions:
            logger.info(f"Found {len(duplicate_positions)} duplicates in playlist '{playlist_name}'")
            
            # Print duplicate details
            for position in sorted(duplicate_positions):
                track = tracks[position]['track']
                artists = ', '.join([artist['name'] for artist in track['artists']])
                logger.info(f"Duplicate: {track['name']} by {artists}")
            
            # Remove duplicates if not in dry-run mode
            if not args.dry_run:
                removed = remove_duplicates(sp, playlist_id, duplicate_positions, tracks)
                logger.info(f"Successfully removed {removed} duplicate tracks from playlist '{playlist_name}'")
            else:
                logger.info("Dry run mode - no tracks were removed")
        else:
            logger.info(f"No duplicates found in playlist '{playlist_name}'")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    
    return 0

if __name__ == '__main__':
    main()
