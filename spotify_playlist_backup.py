#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import spotipy
import yaml
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


def setup_logging(log_file: str = 'logs/spotify_playlist_backup.log') -> logging.Logger:
    """Configure console + file logging."""
    logger = logging.getLogger('spotify_playlist_backup')
    logger.setLevel(logging.DEBUG)

    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Avoid duplicate handlers when running multiple times
    if logger.handlers:
        logger.handlers.clear()

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()

# Load environment variables once module is imported
load_dotenv()


def setup_spotify_client() -> spotipy.Spotify:
    """Authenticate using env credentials and return a Spotify client."""
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')

    if not client_id or not client_secret:
        logger.error('Missing Spotify API credentials. Set SPOTIFY_CLIENT_ID/SECRET in .env')
        raise ValueError('Missing Spotify API credentials')

    scope = 'playlist-read-private playlist-read-collaborative user-library-read'

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
    )

    return spotipy.Spotify(auth_manager=auth_manager)


def load_config(path: str) -> Dict[str, Any]:
    """Load YAML config and apply defaults."""
    if not os.path.exists(path):
        raise FileNotFoundError(f'Config file not found: {path}')

    with open(path, 'r', encoding='utf-8') as handle:
        raw_config = yaml.safe_load(handle) or {}

    config = {
        'output_root': raw_config.get('output_root', 'backups'),
        'mode': raw_config.get('mode', 'all').lower(),
        'selected_playlists': raw_config.get('selected_playlists', []),
        'exclude_playlists': raw_config.get('exclude_playlists', []),
        'default_format': raw_config.get('default_format', 'both'),
        'include_liked_songs': raw_config.get('include_liked_songs', True),
    }

    if config['mode'] not in {'all', 'selected'}:
        raise ValueError("Config 'mode' must be either 'all' or 'selected'")

    return config


def slugify(value: str) -> str:
    """Simple slug for filesystem folders."""
    value = value.strip().lower()
    value = re.sub(r'[^a-z0-9\-\s_]+', '', value)
    value = re.sub(r'[\s_]+', '-', value)
    return value[:60] or 'playlist'


def ensure_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def fetch_all_playlists(sp: spotipy.Spotify) -> List[Dict[str, Any]]:
    playlists = []
    limit = 50
    offset = 0

    while True:
        response = sp.current_user_playlists(limit=limit, offset=offset)
        playlists.extend(response.get('items', []))
        if response.get('next'):
            offset += limit
        else:
            break

    logger.info(f'Found {len(playlists)} playlists for current user')
    return playlists


def fetch_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> List[Dict[str, Any]]:
    items = []
    limit = 100
    offset = 0

    while True:
        response = sp.playlist_items(playlist_id, limit=limit, offset=offset)
        items.extend(response.get('items', []))
        if response.get('next'):
            offset += limit
        else:
            break

    return items


def fetch_liked_songs(sp: spotipy.Spotify) -> List[Dict[str, Any]]:
    items = []
    limit = 50
    offset = 0

    while True:
        response = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items.extend(response.get('items', []))
        if response.get('next'):
            offset += limit
        else:
            break

    logger.info(f'Retrieved {len(items)} liked songs')
    return items


def normalize_tracks(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []

    for index, item in enumerate(items):
        track = item.get('track')
        if not track:
            normalized.append(
                {
                    'position': index,
                    'id': None,
                    'uri': None,
                    'name': 'Unavailable Track',
                    'artists': [],
                    'album': None,
                    'duration_ms': None,
                    'is_local': False,
                    'spotify_url': None,
                    'added_at': item.get('added_at'),
                    'added_by': None,
                    'explicit': None,
                    'available': False,
                }
            )
            continue

        artists = track.get('artists') or []
        normalized.append(
            {
                'position': index,
                'id': track.get('id'),
                'uri': track.get('uri'),
                'name': track.get('name'),
                'artists': [{'id': artist.get('id'), 'name': artist.get('name')} for artist in artists],
                'album': {
                    'id': track.get('album', {}).get('id'),
                    'name': track.get('album', {}).get('name'),
                },
                'duration_ms': track.get('duration_ms'),
                'is_local': track.get('is_local', False),
                'spotify_url': (track.get('external_urls') or {}).get('spotify'),
                'added_at': item.get('added_at'),
                'added_by': (item.get('added_by') or {}).get('id'),
                'explicit': track.get('explicit'),
                'available': True,
            }
        )

    return normalized


def write_json(path: str, data: Any) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def write_m3u(tracks: List[Dict[str, Any]], destination: str) -> None:
    lines = ['#EXTM3U']
    for track in tracks:
        name = track.get('name') or 'Unknown Title'
        artists = ', '.join(artist['name'] for artist in track.get('artists', []))
        duration_ms = track.get('duration_ms')
        duration_seconds = int(duration_ms / 1000) if duration_ms else -1
        metadata = f"{artists} - {name}" if artists else name
        lines.append(f"#EXTINF:{duration_seconds},{metadata}")

        if track.get('spotify_url'):
            lines.append(track['spotify_url'])
        elif track.get('uri'):
            lines.append(track['uri'])
        else:
            lines.append(name)

    with open(destination, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')


def parse_format(value: Optional[str]) -> List[str]:
    if not value:
        value = 'both'

    normalized = value.lower()
    if normalized == 'both':
        return ['json', 'm3u']
    if normalized in {'json', 'm3u'}:
        return [normalized]

    logger.warning(f"Unknown format '{value}', defaulting to both")
    return ['json', 'm3u']


def resolve_identifier(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, dict):
        return {key: entry.get(key) for key in ('id', 'name') if entry.get(key)}

    if isinstance(entry, str):
        value = entry.strip()
        if value.startswith('spotify:playlist:'):
            return {'id': value.split(':')[-1]}
        if 'open.spotify.com/playlist/' in value:
            playlist_id = value.split('open.spotify.com/playlist/')[1].split('?')[0]
            return {'id': playlist_id}
        if re.fullmatch(r'[A-Za-z0-9]{22}', value):
            return {'id': value}
        return {'name': value}

    return {}


def determine_playlist_exports(config: Dict[str, Any], playlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {playlist['id']: playlist for playlist in playlists}
    name_map: Dict[str, List[Dict[str, Any]]] = {}
    for playlist in playlists:
        name_key = (playlist.get('name') or '').casefold()
        name_map.setdefault(name_key, []).append(playlist)

    exports: List[Dict[str, Any]] = []

    def find_playlist(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        playlist_id = entry.get('id')
        playlist_name = entry.get('name')
        if playlist_id:
            playlist = by_id.get(playlist_id)
            if not playlist:
                logger.warning(f"Playlist with ID '{playlist_id}' not found; skipping")
            return playlist
        if playlist_name:
            matches = name_map.get(playlist_name.casefold(), [])
            if not matches:
                logger.warning(f"Playlist named '{playlist_name}' not found; skipping")
                return None
            if len(matches) > 1:
                logger.warning(f"Playlist name '{playlist_name}' is ambiguous; skipping")
                return None
            return matches[0]
        logger.warning('Playlist entry missing both id and name; skipping')
        return None

    def resolve_ids(entries: List[Any]) -> List[str]:
        resolved_ids = []
        for entry in entries:
            details = resolve_identifier(entry)
            playlist = find_playlist(details)
            if playlist:
                resolved_ids.append(playlist['id'])
        return resolved_ids

    default_format = config['default_format']

    if config['mode'] == 'all':
        excluded_ids = set(resolve_ids(config.get('exclude_playlists', [])))
        for playlist in playlists:
            if playlist['id'] in excluded_ids:
                continue
            exports.append(
                {
                    'id': playlist['id'],
                    'name': playlist.get('name'),
                    'format': parse_format(default_format),
                }
            )
    else:
        for entry in config.get('selected_playlists', []):
            details = resolve_identifier(entry)
            if isinstance(entry, dict):
                if entry.get('name') and 'name' not in details:
                    details['name'] = entry.get('name')
                entry_format = parse_format(entry.get('format') or default_format)
            else:
                entry_format = parse_format(default_format)
            playlist = find_playlist(details)
            if playlist:
                exports.append(
                    {
                        'id': playlist['id'],
                        'name': playlist.get('name'),
                        'format': entry_format,
                    }
                )

    return exports


def write_metadata_files(base_dir: str, metadata: Dict[str, Any], tracks: List[Dict[str, Any]]) -> None:
    write_json(os.path.join(base_dir, 'metadata.json'), metadata)
    write_json(os.path.join(base_dir, 'tracks.json'), tracks)


def backup_playlist(
    sp: spotipy.Spotify,
    playlist_id: str,
    playlist_name: str,
    playlist_dir: str,
    export_formats: List[str],
) -> Dict[str, Any]:
    logger.info(f"Backing up playlist '{playlist_name}' ({playlist_id})")
    details = sp.playlist(playlist_id)
    track_items = fetch_playlist_tracks(sp, playlist_id)
    normalized_tracks = normalize_tracks(track_items)

    metadata = {
        'id': details.get('id'),
        'name': details.get('name'),
        'description': details.get('description'),
        'owner': {
            'id': details.get('owner', {}).get('id'),
            'display_name': details.get('owner', {}).get('display_name'),
        },
        'public': details.get('public'),
        'collaborative': details.get('collaborative'),
        'snapshot_id': details.get('snapshot_id'),
        'tracks_total': details.get('tracks', {}).get('total'),
        'images': details.get('images', []),
        'href': details.get('external_urls', {}).get('spotify'),
    }

    ensure_directory(playlist_dir)

    if 'json' in export_formats:
        write_metadata_files(playlist_dir, metadata, normalized_tracks)

    if 'm3u' in export_formats:
        write_m3u(normalized_tracks, os.path.join(playlist_dir, 'playlist.m3u'))

    return {
        'id': metadata['id'],
        'name': metadata['name'],
        'track_count': len(normalized_tracks),
        'directory': playlist_dir,
        'formats': export_formats,
    }


def backup_liked_songs(
    sp: spotipy.Spotify,
    user: Dict[str, Any],
    liked_dir: str,
    export_formats: List[str],
) -> Dict[str, Any]:
    logger.info('Backing up Liked Songs')
    liked_items = fetch_liked_songs(sp)
    normalized_tracks = normalize_tracks(liked_items)

    metadata = {
        'id': 'liked_songs',
        'name': 'Liked Songs',
        'description': 'Spotify saved tracks library',
        'owner': {
            'id': user.get('id'),
            'display_name': user.get('display_name'),
        },
        'tracks_total': len(normalized_tracks),
        'snapshot_id': None,
    }

    ensure_directory(liked_dir)

    if 'json' in export_formats:
        write_metadata_files(liked_dir, metadata, normalized_tracks)

    if 'm3u' in export_formats:
        write_m3u(normalized_tracks, os.path.join(liked_dir, 'playlist.m3u'))

    return {
        'id': 'liked_songs',
        'name': 'Liked Songs',
        'track_count': len(normalized_tracks),
        'directory': liked_dir,
        'formats': export_formats,
    }


def create_manifest(path: str, summary: Dict[str, Any]) -> None:
    write_json(path, summary)


def main() -> None:
    parser = argparse.ArgumentParser(description='Backup Spotify playlists to JSON + M3U files')
    parser.add_argument('--config', default='playlist_backup.yaml', help='Path to backup config file')
    parser.add_argument('--log-file', default='logs/spotify_playlist_backup.log', help='Log file path')

    args = parser.parse_args()

    global logger
    logger = setup_logging(args.log_file)

    try:
        config = load_config(args.config)
    except Exception as exc:
        logger.error(f'Unable to load config: {exc}')
        return

    try:
        sp = setup_spotify_client()
    except Exception as exc:
        logger.error(f'Spotify auth failed: {exc}')
        return

    user_profile = sp.current_user()
    playlists = fetch_all_playlists(sp)
    planned_exports = determine_playlist_exports(config, playlists)

    if not planned_exports and not config.get('include_liked_songs', True):
        logger.warning('No playlists to export and liked songs disabled; nothing to do')
        return

    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    root_dir = os.path.join(config['output_root'], timestamp)
    ensure_directory(root_dir)

    export_records = []

    for entry in planned_exports:
        playlist_id = entry['id']
        playlist_name = entry.get('name') or playlist_id
        playlist_slug = slugify(playlist_name)
        playlist_dir = os.path.join(root_dir, f'{playlist_slug}_{playlist_id[:8]}')
        result = backup_playlist(sp, playlist_id, playlist_name, playlist_dir, entry['format'])
        export_records.append(result)

    if config.get('include_liked_songs', True):
        liked_dir = os.path.join(root_dir, 'liked_songs')
        result = backup_liked_songs(sp, user_profile, liked_dir, parse_format(config['default_format']))
        export_records.append(result)

    manifest = {
        'run_started_at': timestamp,
        'user': {
            'id': user_profile.get('id'),
            'display_name': user_profile.get('display_name'),
        },
        'mode': config['mode'],
        'include_liked_songs': config.get('include_liked_songs', True),
        'output_root': config['output_root'],
        'backups_created': export_records,
    }

    create_manifest(os.path.join(root_dir, 'manifest.json'), manifest)
    logger.info(f"Backup complete: saved {len(export_records)} entries to {root_dir}")


if __name__ == '__main__':
    main()
