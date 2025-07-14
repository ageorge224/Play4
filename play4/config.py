"""
Configuration management for Play4.py - Local directory version
Moves config to Play4 folder for easier management
"""
import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)

@dataclass
class Config:
    """Enhanced configuration with local directory support"""
    playlists: List[str] = field(default_factory=list)
    music_dirs: Dict[str, str] = field(default_factory=dict)
    download_timeout: int = 300
    session_file: str = ""
    cache_db: str = ""
    max_workers: int = 3
    acoustid_timeout: int = 30
    acoustid_api_key: str = ""
    acoustid_confidence_threshold: float = 0.7
    musicbrainz_confidence_threshold: float = 0.5
    resume_session: bool = True
    skip_existing: bool = True
    auto_enhance_metadata: bool = True
    rename_after_download: bool = False
    check_duplicates: bool = True
    auto_organize: bool = False
    max_cache_age_days: int = 30
    retry_failed_downloads: bool = True
    max_retries: int = 3
    acoustid_for_playback: bool = True
    download_sample_for_acoustid: bool = True
    max_sample_duration: int = 120
    
    def _is_valid_api_key(self) -> bool:
        """More lenient validation for registered keys"""
        return bool(self.acoustid_api_key and len(self.acoustid_api_key.strip()) >= 8)
    
    def __post_init__(self):
        home = Path.home()
        
        # Use local Play4 directory for config and cache
        play4_dir = Path(__file__).parent.parent  # Go up from play4/ to Play4/
        
        if not self.session_file:
            self.session_file = str(play4_dir / "session.json")
        if not self.cache_db:
            self.cache_db = str(play4_dir / "metadata.db")
        
        if not self.playlists:
            self.playlists = [
                "https://www.youtube.com/watch?v=GwkUq3cXe8o&list=RDGwkUq3cXe8o",
                "https://www.youtube.com/watch?v=X4jmOPivM7U&list=RDX4jmOPivM7U",
            ]
        if not self.music_dirs:
            self.music_dirs = {
                "1": str(home / "Music" / "1star"),
                "2": str(home / "Music" / "2star"), 
                "3": str(home / "Music" / "3star"),
                "4": str(home / "Music" / "4star"),
            }
        
        # Ensure parent directories exist
        os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.cache_db), exist_ok=True)
        
        # Validate thresholds
        self.acoustid_confidence_threshold = max(0.0, min(1.0, self.acoustid_confidence_threshold))
        self.musicbrainz_confidence_threshold = max(0.0, min(1.0, self.musicbrainz_confidence_threshold))

    @classmethod
    def load_from_file(cls, config_path: str = None):
        """Load configuration from local Play4 directory"""
        if not config_path:
            # Default to config.json in the Play4 directory (same level as play4.py)
            script_dir = Path(__file__).parent.parent  # Go up from play4/ to Play4/
            config_path = str(script_dir / "config.json")
        
        default_config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                    # Filter out comment fields (starting with _) and validate configuration
                    filtered_config = {
                        k: v for k, v in loaded_config.items() 
                        if not k.startswith('_')
                    }
                    default_config.update(filtered_config)
                    logger.info(f"Loaded configuration from {config_path}")
            except Exception as e:
                logger.error(f"Error loading config from {config_path}: {e}")
        else:
            logger.info(f"No config file found at {config_path}, using defaults")
        
        return cls(**default_config)
    
    def save_to_file(self, config_path: str = None):
        """Save current configuration to local Play4 directory"""
        if not config_path:
            script_dir = Path(__file__).parent.parent
            config_path = str(script_dir / "config.json")
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            config_dict = {
                '_comment': 'Play4.py configuration file - edit as needed',
                '_location': 'This file is in your Play4 directory for easy access',
                'playlists': self.playlists,
                'music_dirs': self.music_dirs,
                'download_timeout': self.download_timeout,
                'acoustid_api_key': self.acoustid_api_key,
                'acoustid_confidence_threshold': self.acoustid_confidence_threshold,
                'musicbrainz_confidence_threshold': self.musicbrainz_confidence_threshold,
                'resume_session': self.resume_session,
                'skip_existing': self.skip_existing,
                'auto_enhance_metadata': self.auto_enhance_metadata,
                'rename_after_download': self.rename_after_download,
                'check_duplicates': self.check_duplicates,
                'auto_organize': self.auto_organize,
                'max_cache_age_days': self.max_cache_age_days,
                'retry_failed_downloads': self.retry_failed_downloads,
                'max_retries': self.max_retries,
                'acoustid_for_playback': self.acoustid_for_playback,
                'download_sample_for_acoustid': self.download_sample_for_acoustid,
                'max_sample_duration': self.max_sample_duration
            }
            with open(config_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
            logger.info(f"Configuration saved to {config_path}")
            print(f"✅ Config saved to: {config_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
    
    def get_config_location(self) -> str:
        """Get the current config file location"""
        script_dir = Path(__file__).parent.parent
        return str(script_dir / "config.json")