"""
Download management with background processing
Complete implementation with all necessary functionality
"""
import os
import subprocess
import hashlib
import threading
import logging
import re
from pathlib import Path
from typing import Optional, Set
from concurrent.futures import ThreadPoolExecutor

from .player import Colors

logger = logging.getLogger(__name__)

class DownloadManager:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.file_hashes = {}
        self.hash_lock = threading.Lock()
    
    def download_song_background(self, url: str, folder: str):
        """Start background download with completion tracking"""
        if url in self.state.already_downloading:
            print(f"{Colors.YELLOW}⚠️ Download already in progress{Colors.END}")
            return
            
        self.state.already_downloading.add(url)
        
        def download_wrapper():
            try:
                print(f"{Colors.BLUE}⬇️ Starting download to {os.path.basename(folder)}...{Colors.END}")
                result = self.download_song_sync(url, folder)
                if result:
                    return result
                return None
            except Exception as e:
                logger.error(f"Download failed: {e}")
                return None
            finally:
                with self.state.downloads_lock:
                    self.state.already_downloading.discard(url)
                
        future = self.state.executor.submit(download_wrapper)
        with self.state.downloads_lock:
            self.state.active_downloads.append(future)
    
    def download_song_sync(self, url: str, folder: str, retry_count: int = 0) -> Optional[str]:
        """Synchronous download with retry logic"""
        try:
            os.makedirs(folder, exist_ok=True)
            
            # Check if already exists
            if self.config.skip_existing:
                potential_filename = self.get_potential_filename(url)
                if potential_filename:
                    for ext in ['.flac', '.m4a', '.mp3']:
                        check_path = Path(folder) / (potential_filename + ext)
                        if check_path.exists():
                            print(f"{Colors.YELLOW}⚠️ Already exists: {check_path.name}{Colors.END}")
                            return None
            
            print(f"{Colors.BLUE}⬇️ Downloading to: {os.path.basename(folder)}{Colors.END}")
            
            cmd = [
                "yt-dlp", "-f", "bestaudio",
                "--extract-audio", "--audio-format", "flac",
                "--embed-thumbnail", "--add-metadata",
                "--parse-metadata", "%(title)s:%(meta_title)s",
                "--no-overwrites",
                "-o", os.path.join(folder, "%(title)s.%(ext)s"),
                url
            ]
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, 
                timeout=self.config.download_timeout
            )
            
            if result.returncode == 0:
                # Find the downloaded file
                output = re.search(r"\[ExtractAudio\] Destination: (.+\.flac)", result.stderr)
                if output:
                    file_path = output.group(1)
                    self.state.downloads_count += 1
                    
                    print(f"{Colors.GREEN}✅ Download complete! {os.path.basename(file_path)}{Colors.END}")
                    print(f"{Colors.GREEN}📊 Total downloads: {self.state.downloads_count}{Colors.END}")
                    
                    return file_path
            else:
                error_msg = result.stderr or result.stdout
                logger.error(f"Download failed: {error_msg}")
                
                # Retry logic
                if (retry_count < self.config.max_retries and 
                    self.config.retry_failed_downloads):
                    logger.info(f"Retrying download (attempt {retry_count + 1}/{self.config.max_retries})")
                    import time
                    time.sleep(2 ** retry_count)  # Exponential backoff
                    return self.download_song_sync(url, folder, retry_count + 1)
                else:
                    self.state.failed_downloads[url] = error_msg[:200]
                    print(f"{Colors.RED}❌ Download failed after {retry_count + 1} attempts{Colors.END}")
                
        except subprocess.TimeoutExpired:
            print(f"{Colors.RED}❌ Download timeout after {self.config.download_timeout}s{Colors.END}")
            if retry_count < self.config.max_retries:
                import time
                time.sleep(2)
                return self.download_song_sync(url, folder, retry_count + 1)
        except Exception as e:
            logger.error(f"Download error: {e}")
            
        return None
    
    def get_potential_filename(self, url: str) -> Optional[str]:
        """Get potential filename for URL"""
        try:
            result = subprocess.run([
                "yt-dlp", "--get-filename", "-o", "%(title)s", url
            ], capture_output=True, text=True, timeout=10)
            filename = result.stdout.strip()
            # Sanitize filename
            return re.sub(r'[<>:"/\\|?*]', '', filename)[:100] if filename else None
        except Exception:
            return None