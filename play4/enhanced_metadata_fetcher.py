"""
Enhanced Metadata Fetcher with AcoustID Integration
Brings back full metadata functionality with progress output
"""
import subprocess
import json
import time
import os
import hashlib
import tempfile
import shutil
import logging
import re
from pathlib import Path
from typing import Optional

from .metadata import SongMetadata, MetadataSource, MetadataCache
from .player import Colors

logger = logging.getLogger(__name__)

class EnhancedMetadataFetcher:
    """Enhanced metadata fetcher with AcoustID and progress output"""
    
    def __init__(self, cache: MetadataCache, config):
        self.cache = cache
        self.config = config
        self.last_api_call = 0
        self.min_api_interval = 0.5  # Rate limiting
        
        # Try to import AcoustID
        self.acoustid = None
        self.musicbrainzngs = None
        try:
            import acoustid
            self.acoustid = acoustid
        except ImportError:
            logger.warning("AcoustID not available - pip install pyacoustid")
            
        try:
            import musicbrainzngs
            self.musicbrainzngs = musicbrainzngs
            musicbrainzngs.set_useragent("Play4.py", "4.2", "https://github.com/user/play4")
        except ImportError:
            logger.warning("MusicBrainz not available - pip install musicbrainzngs")
    
    def _rate_limit(self):
        """Enforce rate limiting for API calls"""
        elapsed = time.time() - self.last_api_call
        if elapsed < self.min_api_interval:
            time.sleep(self.min_api_interval - elapsed)
        self.last_api_call = time.time()
    
    def _validate_api_key(self) -> bool:
        """Validate AcoustID API key is present and properly formatted"""
        if not self.config.acoustid_api_key:
            return False
        return len(self.config.acoustid_api_key.strip()) >= 8
    
    def _download_sample_audio(self, url: str) -> Optional[str]:
        """Download a short sample for AcoustID fingerprinting"""
        if not self.config.download_sample_for_acoustid:
            return None
            
        try:
            # Create temp directory
            temp_dir = Path(tempfile.gettempdir()) / "play4_samples"
            temp_dir.mkdir(exist_ok=True)
            
            # Generate a safe filename
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            temp_file = temp_dir / f"sample_{url_hash}.%(ext)s"
            
            print(f"{Colors.CYAN}  🎵 Downloading audio sample for AcoustID analysis...{Colors.END}")
            
            # Get duration first to calculate optimal sample position
            try:
                duration_result = subprocess.run([
                    "yt-dlp", "--get-duration", url
                ], capture_output=True, text=True, timeout=10)
                
                total_duration = 0
                if duration_result.returncode == 0:
                    dur_str = duration_result.stdout.strip()
                    if ":" in dur_str:
                        parts = dur_str.split(":")
                        if len(parts) == 2:
                            total_duration = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            total_duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    else:
                        total_duration = float(dur_str)
            except:
                total_duration = 180  # Default fallback
            
            # Calculate optimal sample position (30% into the song)
            start_time = 30 if total_duration <= 60 else min(60, total_duration * 0.3)
            sample_duration = min(120, total_duration - start_time) if total_duration > 0 else 90
            
            # Download optimal sample for fingerprinting
            cmd = [
                "yt-dlp", "-f", "bestaudio",
                "--extract-audio", "--audio-format", "flac",
                "--postprocessor-args", f"ffmpeg:-ss {start_time} -t {sample_duration}",
                "--no-playlist",
                "--no-overwrites",
                "-o", str(temp_file),
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            
            if result.returncode == 0:
                # Find the downloaded file
                sample_path = None
                
                # Look for ExtractAudio destination
                output_pattern = re.search(r"\[ExtractAudio\] Destination: (.+\.flac)", result.stderr)
                if output_pattern:
                    sample_path = output_pattern.group(1)
                
                # Fallback: look for recent FLAC files
                if not sample_path:
                    current_time = time.time()
                    for flac_file in temp_dir.glob("*.flac"):
                        if current_time - os.path.getctime(flac_file) < 120:
                            sample_path = str(flac_file)
                            break
                
                if sample_path and os.path.exists(sample_path):
                    file_size = os.path.getsize(sample_path)
                    print(f"{Colors.GREEN}  ✅ Sample downloaded ({file_size // 1024}KB, {sample_duration:.0f}s from {start_time:.0f}s){Colors.END}")
                    return sample_path
                else:
                    print(f"{Colors.RED}  ❌ Sample file not found after download{Colors.END}")
            else:
                print(f"{Colors.RED}  ❌ Sample download failed{Colors.END}")
                
        except subprocess.TimeoutExpired:
            print(f"{Colors.RED}  ❌ Sample download timeout{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}  ❌ Sample download error: {str(e)[:50]}...{Colors.END}")
            
        return None
    
    def get_basic_metadata(self, url: str) -> SongMetadata:
        """Get basic metadata from yt-dlp"""
        try:
            result = subprocess.run([
                "yt-dlp", "--skip-download", "--print",
                '{"title":"%(title)s","artist":"%(artist)s","album":"%(album)s","duration":%(duration)s}',
                url
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                data = json.loads(result.stdout.strip())
                duration = data.get("duration")
                
                if isinstance(duration, (int, float)) and duration > 0:
                    duration = int(duration)
                else:
                    duration = 0
                
                title = data.get("title") or "Unknown Title"
                artist = data.get("artist") or "Unknown Artist"
                album = data.get("album") or "Unknown Album"
                
                return SongMetadata(
                    title=str(title)[:200],
                    artist=str(artist)[:100],
                    album=str(album)[:100],
                    duration=duration,
                    source=MetadataSource.YTDLP
                )
        except Exception as e:
            logger.warning(f"Failed to get basic metadata for {url}: {e}")
        
        return SongMetadata()
    
    def enhance_with_acoustid(self, audio_file: str, metadata: SongMetadata) -> SongMetadata:
        """Enhanced AcoustID lookup with detailed progress output"""
        if not self.acoustid or not self._validate_api_key():
            metadata.acoustid_attempted = True
            if not self.acoustid:
                print(f"{Colors.YELLOW}  ⚠️ AcoustID library not available{Colors.END}")
            else:
                print(f"{Colors.YELLOW}  ⚠️ AcoustID API key not configured{Colors.END}")
            return metadata
            
        if not audio_file or not os.path.exists(audio_file):
            print(f"{Colors.YELLOW}  ⚠️ Audio file not available for AcoustID analysis{Colors.END}")
            metadata.acoustid_attempted = True
            return metadata
            
        try:
            self._rate_limit()
            
            print(f"{Colors.CYAN}  🔍 Generating acoustic fingerprint...{Colors.END}")
            
            # Check file size
            file_size = os.path.getsize(audio_file)
            if file_size < 1000:
                print(f"{Colors.RED}  ❌ Audio file too small ({file_size} bytes){Colors.END}")
                metadata.acoustid_attempted = True
                return metadata
            
            # Generate fingerprint
            try:
                duration, fingerprint = self.acoustid.fingerprint_file(audio_file)
            except Exception as fp_error:
                print(f"{Colors.RED}  ❌ Fingerprint generation failed: {str(fp_error)[:50]}...{Colors.END}")
                metadata.acoustid_attempted = True
                return metadata
            
            if not fingerprint:
                print(f"{Colors.RED}  ❌ Could not generate audio fingerprint{Colors.END}")
                metadata.acoustid_attempted = True
                return metadata
            
            print(f"{Colors.GREEN}  ✅ Fingerprint generated ({duration:.1f}s audio){Colors.END}")
            
            # Duration sanity check
            if abs(duration - metadata.duration) > 30 and metadata.duration > 0:
                print(f"{Colors.YELLOW}  ⚠️ Duration mismatch: {duration:.0f}s vs {metadata.duration}s{Colors.END}")
            
            # Query AcoustID database
            print(f"{Colors.CYAN}  🌐 Querying AcoustID database...{Colors.END}")
            
            try:
                results = self.acoustid.lookup(
                    apikey=self.config.acoustid_api_key,
                    fingerprint=fingerprint,
                    duration=duration,
                    meta='recordings+releases+artists+tags'
                )
            except Exception as api_error:
                print(f"{Colors.RED}  ❌ AcoustID API error: {str(api_error)[:50]}...{Colors.END}")
                metadata.acoustid_attempted = True
                return metadata
            
            metadata.acoustid_attempted = True
            
            if not results or not results.get('results'):
                print(f"{Colors.YELLOW}  ❓ No matches found in AcoustID database{Colors.END}")
                return metadata
            
            # Process results
            sorted_results = sorted(results['results'], key=lambda x: x.get('score', 0), reverse=True)
            best_result = sorted_results[0]
            score = best_result.get('score', 0)
            
            print(f"{Colors.CYAN}  🎯 Best match confidence: {score:.1%} (threshold: {self.config.acoustid_confidence_threshold:.1%}){Colors.END}")
            
            # Use lower threshold for testing if configured
            effective_threshold = self.config.acoustid_confidence_threshold
            if score < effective_threshold and score > 0.3:
                print(f"{Colors.YELLOW}  🔍 Low confidence match, trying anyway...{Colors.END}")
                effective_threshold = 0.3
            
            if score >= effective_threshold:
                recordings = best_result.get('recordings', [])
                if recordings:
                    recording = recordings[0]
                    
                    enhanced = SongMetadata(
                        title=recording.get('title', metadata.title)[:200],
                        artist=metadata.artist,
                        album=metadata.album,
                        duration=int(duration) if duration > 0 else metadata.duration,
                        acoustid=best_result.get('id'),
                        confidence=score,
                        musicbrainz_id=recording.get('id'),
                        source=MetadataSource.ACOUSTID,
                        acoustid_attempted=True
                    )
                    
                    # Extract artist
                    if recording.get('artists'):
                        enhanced.artist = recording['artists'][0].get('name', metadata.artist)[:100]
                    
                    # Extract release info
                    releases = recording.get('releases', [])
                    if releases:
                        release = releases[0]
                        enhanced.album = release.get('title', metadata.album)[:100]
                        
                        # Get detailed release info from MusicBrainz
                        if release.get('id') and self.musicbrainzngs:
                            try:
                                self._rate_limit()
                                print(f"{Colors.CYAN}  🎼 Getting detailed metadata from MusicBrainz...{Colors.END}")
                                
                                mb_release = self.musicbrainzngs.get_release_by_id(
                                    release['id'], includes=['tags', 'release-groups']
                                )
                                release_data = mb_release.get('release', {})
                                
                                # Extract genres
                                if release_data.get('tag-list'):
                                    enhanced.genres = [
                                        tag['name'] for tag in release_data['tag-list'][:5]
                                        if tag.get('count', 0) > 0
                                    ]
                                
                                # Extract year
                                rg = release_data.get('release-group', {})
                                if rg.get('first-release-date'):
                                    try:
                                        enhanced.year = int(rg['first-release-date'][:4])
                                    except (ValueError, TypeError):
                                        pass
                                        
                            except Exception as e:
                                print(f"{Colors.YELLOW}  ⚠️ MusicBrainz lookup failed: {str(e)[:50]}...{Colors.END}")
                    
                    print(f"{Colors.GREEN}  ✅ AcoustID Success! {enhanced.artist} - {enhanced.title} ({enhanced.confidence:.1%}){Colors.END}")
                    if enhanced.genres:
                        print(f"{Colors.GREEN}    🏷️ Genres: {', '.join(enhanced.genres[:3])}{Colors.END}")
                    if enhanced.year:
                        print(f"{Colors.GREEN}    📅 Year: {enhanced.year}{Colors.END}")
                    
                    return enhanced
                else:
                    print(f"{Colors.YELLOW}  ❓ AcoustID match has no recording data{Colors.END}")
            else:
                print(f"{Colors.YELLOW}  ⚠️ AcoustID confidence {score:.1%} below threshold{Colors.END}")
        
        except Exception as e:
            print(f"{Colors.RED}  ❌ AcoustID lookup failed: {str(e)[:60]}...{Colors.END}")
            metadata.acoustid_attempted = True
        
        return metadata
    
    def enhance_with_musicbrainz(self, metadata: SongMetadata) -> SongMetadata:
        """Enhanced MusicBrainz text search"""
        if not self.musicbrainzngs:
            return metadata
            
        try:
            self._rate_limit()
            print(f"{Colors.CYAN}  🔍 Searching MusicBrainz by text...{Colors.END}")
            
            # Try multiple search strategies
            search_terms = [
                {'artist': metadata.artist, 'recording': metadata.title},
                {'query': f'artist:"{metadata.artist}" recording:"{metadata.title}"'},
                {'query': f'{metadata.artist} {metadata.title}'}
            ]
            
            for terms in search_terms:
                try:
                    result = self.musicbrainzngs.search_recordings(limit=5, **terms)
                    recordings = result.get('recording-list', [])
                    
                    if recordings:
                        best_recording = recordings[0]
                        
                        enhanced = SongMetadata(
                            title=best_recording.get('title', metadata.title)[:200],
                            artist=metadata.artist,
                            album=metadata.album,
                            duration=metadata.duration,
                            musicbrainz_id=best_recording.get('id'),
                            confidence=self.config.musicbrainz_confidence_threshold,
                            source=MetadataSource.MUSICBRAINZ,
                            acoustid_attempted=metadata.acoustid_attempted
                        )
                        
                        # Extract artist
                        if best_recording.get('artist-credit'):
                            artist_credit = best_recording['artist-credit'][0]
                            enhanced.artist = artist_credit.get('artist', {}).get('name', metadata.artist)[:100]
                        
                        # Extract release info
                        releases = best_recording.get('release-list', [])
                        if releases:
                            release = releases[0]
                            enhanced.album = release.get('title', metadata.album)[:100]
                        
                        print(f"{Colors.GREEN}  ✅ MusicBrainz text search success{Colors.END}")
                        return enhanced
                        
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"{Colors.YELLOW}  ⚠️ MusicBrainz search failed: {str(e)[:50]}...{Colors.END}")
        
        return metadata
    
    def get_metadata(self, url: str, audio_file: str = None, show_progress: bool = True) -> SongMetadata:
        """Get comprehensive metadata with enhanced progress output"""
        if show_progress:
            print(f"{Colors.CYAN}🔍 Analyzing metadata for: {url[:60]}...{Colors.END}")
        
        # Check cache first
        cached = self.cache.get_metadata(url)
        if cached and cached.is_complete_metadata():
            if show_progress:
                print(f"{Colors.GREEN}  ✅ Using cached metadata (confidence: {cached.confidence:.1%}){Colors.END}")
            cached.source = MetadataSource.CACHE
            return cached
        
        # Get basic metadata
        if show_progress:
            print(f"{Colors.CYAN}  📝 Getting basic metadata...{Colors.END}")
        metadata = self.get_basic_metadata(url)
        
        if show_progress:
            print(f"{Colors.GREEN}  ✅ Basic: {metadata.artist} - {metadata.title}{Colors.END}")
        
        # Skip enhancement if disabled
        if not self.config.auto_enhance_metadata:
            self.cache.save_metadata(url, metadata)
            return metadata
        
        # Try AcoustID enhancement
        if self.config.acoustid_for_playback and self._validate_api_key():
            # Try with provided audio file first
            if audio_file and os.path.exists(audio_file):
                if show_progress:
                    print(f"{Colors.CYAN}  🎯 Trying AcoustID with audio file...{Colors.END}")
                enhanced = self.enhance_with_acoustid(audio_file, metadata)
                if enhanced.confidence >= self.config.acoustid_confidence_threshold:
                    self.cache.save_metadata(url, enhanced)
                    return enhanced
            
            # Download sample if configured
            elif self.config.download_sample_for_acoustid:
                sample_file = self._download_sample_audio(url)
                if sample_file:
                    try:
                        enhanced = self.enhance_with_acoustid(sample_file, metadata)
                        if enhanced.confidence >= self.config.acoustid_confidence_threshold:
                            self.cache.save_metadata(url, enhanced)
                            return enhanced
                    finally:
                        # Clean up sample
                        try:
                            os.unlink(sample_file)
                        except:
                            pass
        
        # Mark AcoustID as attempted if we tried
        metadata.acoustid_attempted = True
        
        # Fallback to MusicBrainz
        enhanced = self.enhance_with_musicbrainz(metadata)
        if enhanced.confidence >= self.config.musicbrainz_confidence_threshold:
            metadata = enhanced
        
        # Cache and return
        self.cache.save_metadata(url, metadata)
        return metadata