#!/usr/bin/env python3

import os
import logging

# Configure logging
def setup_logging(log_file='m3u_splitter.log'):
    """Set up logging to file and console without rotation or limits"""
    # Create logger
    logger = logging.getLogger('m3u_splitter')
    logger.setLevel(logging.DEBUG)
    
    # Create file handler which logs all messages
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler(f'logs/{log_file}', mode='a', encoding='utf-8')
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

def parse_m3u(file_path):
    """
    Parse an M3U file and extract the song information.
    
    Args:
        file_path: Path to the M3U file
        
    Returns:
        List of dictionaries with song information (path, title, artist, duration)
    """
    songs = []
    current_song = None
    
    logger.info(f"Parsing M3U file: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
                
            # Handle EXTM3U header
            if line == '#EXTM3U':
                continue
                
            # Handle EXTINF metadata line
            if line.startswith('#EXTINF:'):
                # Format: #EXTINF:duration,artist - title
                try:
                    # Extract duration and title/artist info
                    metadata = line[8:].split(',', 1)
                    duration = int(metadata[0]) if len(metadata) > 0 else 0
                    title_artist = metadata[1] if len(metadata) > 1 else ''
                    
                    # Try to split artist and title
                    artist = ''
                    title = title_artist
                    if ' - ' in title_artist:
                        parts = title_artist.split(' - ', 1)
                        artist = parts[0].strip()
                        title = parts[1].strip() if len(parts) > 1 else ''
                    
                    # Create a new song entry
                    current_song = {
                        'path': '',
                        'title': title,
                        'artist': artist,
                        'duration': duration,
                        'metadata': title_artist  # Keep the original metadata string
                    }
                    logger.debug(f"Parsed metadata: {artist} - {title}")
                except Exception as e:
                    logger.warning(f"Could not parse EXTINF line: {line} - {e}")
                    current_song = None
            # Handle file path line
            elif not line.startswith('#') and current_song is not None:
                current_song['path'] = line
                songs.append(current_song)
                current_song = None
            # Handle other lines starting with # (comments or other directives)
            elif line.startswith('#'):
                continue
            # Handle file path without metadata
            elif not line.startswith('#'):
                songs.append({
                    'path': line,
                    'title': '',
                    'artist': '',
                    'duration': 0,
                    'metadata': ''
                })
    
    return songs

def split_into_batches(songs, batch_size=100):
    """
    Split a list of songs into batches of specified size.
    
    Args:
        songs: List of song URLs/paths
        batch_size: Size of each batch (default: 100)
        
    Returns:
        List of batches, each containing up to batch_size songs
    """
    return [songs[i:i + batch_size] for i in range(0, len(songs), batch_size)]

def save_batches(batches, input_file_path, base_filename='playlist_batch'):
    """
    Save each batch as a separate M3U file in a folder within the same directory as the input file.
    
    Args:
        batches: List of batches
        input_file_path: Path to the original M3U file
        base_filename: Base name for batch files (default: 'playlist_batch')
        
    Returns:
        tuple: (List of saved file paths, output directory)
    """
    # Get the directory of the input file
    input_dir = os.path.dirname(os.path.abspath(input_file_path))
    input_filename = os.path.basename(input_file_path)
    input_name_without_ext = os.path.splitext(input_filename)[0]
    
    # Create a 'batches' folder inside the input file's directory
    output_dir = os.path.join(input_dir, f"{input_name_without_ext}_batches")
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Created output directory: {output_dir}")
    
    saved_files = []
    for i, batch in enumerate(batches):
        file_path = os.path.join(output_dir, f"{base_filename}_{i+1}.m3u")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            for song in batch:
                # Write the EXTINF line if we have metadata
                if song['metadata']:
                    f.write(f"#EXTINF:{song['duration']},{song['metadata']}\n")
                # Write the file path
                f.write(f"{song['path']}\n")
        saved_files.append(file_path)
        logger.debug(f"Saved batch file: {file_path} with {len(batch)} songs")
    
    return saved_files, output_dir

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Split M3U playlists into batches')
    parser.add_argument('m3u_file', help='Path to the M3U file')
    parser.add_argument('-s', '--batch-size', type=int, default=100, help='Number of songs per batch')
    parser.add_argument('-n', '--base-name', default='playlist_batch', help='Base name for batch files')
    parser.add_argument('-o', '--output-dir', help='Optional: Override the default output directory')
    parser.add_argument('--log-file', default='m3u_splitter.log', help='Log file path')
    
    args = parser.parse_args()
    
    # Set up logging with the specified log file
    global logger
    logger = setup_logging(args.log_file)
    
    logger.info(f"Starting M3U Splitter")
    logger.info(f"Parsing {args.m3u_file}...")
    songs = parse_m3u(args.m3u_file)
    logger.info(f"Found {len(songs)} songs")
    
    batches = split_into_batches(songs, args.batch_size)
    logger.info(f"Split into {len(batches)} batches")
    
    if args.output_dir:
        # Use the provided output directory if specified
        os.makedirs(args.output_dir, exist_ok=True)
        logger.info(f"Using specified output directory: {args.output_dir}")
        saved_files = save_batches(batches, args.output_dir, args.base_name)[0]
        output_dir = args.output_dir
    else:
        # Otherwise save in a folder next to the input file
        saved_files, output_dir = save_batches(batches, args.m3u_file, args.base_name)
    
    logger.info(f"Saved batch files to {output_dir}/")
    
    return saved_files

if __name__ == '__main__':
    main()
