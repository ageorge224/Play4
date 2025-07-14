"""
Utility functions
Complete implementation with all necessary functionality
"""
import subprocess
import logging
from pathlib import Path
from typing import List
from urllib.parse import urlparse

def setup_logging(debug: bool = False):
    """Setup logging configuration"""
    log_file = Path.home() / ".cache" / "play4.log"
    log_file.parent.mkdir(exist_ok=True)
    
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.NullHandler()  # Don't spam console unless debug
        ]
    )
    return logging.getLogger(__name__)

def get_playlist_videos(playlist_url: str) -> List[str]:
    """Fetch video URLs from playlist with better error handling"""
    try:
        result = subprocess.run([
            "yt-dlp", "--flat-playlist", "--print", "%(url)s", 
            "--playlist-end", "1000",  # Limit for safety
            playlist_url
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            videos = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            # Filter out invalid URLs
            valid_videos = []
            for video in videos:
                if urlparse(video).scheme in ['http', 'https']:
                    valid_videos.append(video)
            return valid_videos
        else:
            logging.error(f"yt-dlp error: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logging.warning("Timeout fetching playlist")
    except Exception as e:
        logging.error(f"Error fetching playlist: {e}")
    return []