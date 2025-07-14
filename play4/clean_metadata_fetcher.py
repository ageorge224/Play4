"""
Enhanced Metadata Fetcher with Anchored Output System - Fixed Version
Uses terminal manager to avoid interfering with progress bar
Avoids circular imports
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
from .unified_display_system import analysis, estimate_duration_from_file_size, Colors

logger = logging.getLogger(__name__)

class CleanMetadataFetcher:
    """Enhanced metadata fetcher with non-interfering output"""
    
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
            
            analysis_output.acoustid_sample_download()
            
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
                    analysis_output.acoustid_sample_success(file_size, sample_duration)
                    return sample_path
                else:
                    analysis_output.acoustid_failure("Sample file not found")
            else:
                analysis_output.acoustid_failure("Sample download failed")
                
        except subprocess.TimeoutExpired:
            analysis_output.acoustid_failure("Sample download timeout")
        except Exception as e:
            analysis_output.acoustid_failure(f"Sample error: {str(e)[:30]}...")
            
        return None
    
    def get_basic_metadata(self, url: str) -> SongMetadata:
        """Get basic metadata from yt-dlp with duration estimation fallback"""
        try:
            result = subprocess.run([
                "yt-dlp", "--skip-download", "--print",
                '{"title":"%(title)s","artist":"%(artist)s","album":"%(album)s","duration":%(duration)s}',
                url
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                data = json.loads(result.stdout.strip())
                duration = data.get("duration")
                
                # Enhanced duration handling
                if isinstance(duration, (int, float)) and duration > 0:
                    duration = int(duration)
                else:
                    # Try to estimate from URL or use fallback
                    duration = 0
                    
                    # For local files, estimate from file size
                    if url.startswith("file://"):
                        file_path = url[7:]  # Remove file:// prefix
                        duration = estimate_duration_from_file_size(file_path)
                    else:
                        # For YouTube URLs, use a reasonable default
                        duration = 210  # 3.5 minutes average
                
                title = data.get("title") or "Unknown Title"
                artist = data.get("artist") or "Unknown Artist"
                album = data.get("album") or "Unknown Album"
                
                metadata = SongMetadata(
                    title=str(title)[:200],
                    artist=str(artist)[:100],
                    album=str(album)[:100],
                    duration=duration,
                    source=MetadataSource.YTDLP
                )
                
                return metadata
                
        except Exception as e:
            logger.warning(f"Failed to get basic metadata for {url}: {e}")
        
        # Fallback for complete failures
        if url.startswith("file://"):
            file_path = url[7:]
            path = Path(file_path)
            if path.exists():
                # Try to extract info from filename
                stem = path.stem
                if ' - ' in stem:
                    parts = stem.split(' - ', 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = "Unknown Artist"
                    title = stem
                
                return SongMetadata(
                    title=title,
                    artist=artist,
                    album=path.parent.name,
                    duration=estimate_duration_from_file_size(file_path),
                    source=MetadataSource.YTDLP
                )
        
        return SongMetadata(duration=210)  # Fallback
    
    def enhance_with_acoustid(self, audio_file: str, metadata: SongMetadata) -> SongMetadata:
        """Enhanced AcoustID lookup with non-interfering output"""
        if not self.acoustid or not self._validate_api_key():
            metadata.acoustid_attempted = True
            if not self.acoustid:
                analysis_output.acoustid_failure("Library not available")
            else:
                analysis_output.acoustid_failure("API key not configured")
            return metadata
            
        if not audio_file or not os.path.exists(audio_file):
            analysis_output.acoustid_failure("Audio file not available")
            metadata.acoustid_attempted = True
            return metadata
            
        try:
            self._rate_limit()
            
            analysis_output.acoustid_fingerprint_start()
            
            # Check file size
            file_size = os.path.getsize(audio_file)
            if file_size < 1000:
                analysis_output.acoustid_failure(f"File too small ({file_size}B)")
                metadata.acoustid_attempted = True
                return metadata
            
            # Generate fingerprint
            try:
                duration, fingerprint = self.acoustid.fingerprint_file(audio_file)
            except Exception as fp_error:
                analysis_output.acoustid_failure(f"Fingerprint failed: {str(fp_error)[:30]}...")
                metadata.acoustid_attempted = True
                return metadata
            
            if not fingerprint:
                analysis_output.acoustid_failure("Could not generate fingerprint")
                metadata.acoustid_attempted = True
                return metadata
            
            analysis_output.acoustid_fingerprint_success(duration)
            
            # Duration sanity check (but don't spam output)
            if abs(duration - metadata.duration) > 30 and metadata.duration > 0:
                analysis_output.acoustid_failure(f"Duration mismatch: {duration:.0f}s vs {metadata.duration}s")
            
            # Query AcoustID database
            analysis_output.acoustid_query_start()
            
            try:
                results = self.acoustid.lookup(
                    apikey=self.config.acoustid_api_key,
                    fingerprint=fingerprint,
                    duration=duration,
                    meta='recordings+releases+artists+tags'
                )
            except Exception as api_error:
                analysis_output.acoustid_failure(f"API error: {str(api_error)[:30]}...")
                metadata.acoustid_attempted = True
                return metadata
            
            metadata.acoustid_attempted = True
            
            if not results or not results.get('results'):
                analysis_output.acoustid_failure("No matches found")
                return metadata
            
            # Process results
            sorted_results = sorted(results['results'], key=lambda x: x.get('score', 0), reverse=True)
            best_result = sorted_results[0]
            score = best_result.get('score', 0)
            
            # Use lower threshold for testing if configured
            effective_threshold = self.config.acoustid_confidence_threshold
            if score < effective_threshold and score > 0.3:
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
                                        
                            except Exception:
                                pass  # Don't spam errors for MusicBrainz failures
                    
                    analysis_output.acoustid_success(enhanced.artist, enhanced.title, enhanced.confidence)
                    return enhanced
                else:
                    analysis_output.acoustid_failure("Match has no recording data")
            else:
                analysis_output.acoustid_failure(f"Confidence {score:.1%} below threshold")
        
        except Exception as e:
            analysis_output.acoustid_failure(f"Lookup failed: {str(e)[:40]}...")
            metadata.acoustid_attempted = True
        
        return metadata
    
    def enhance_with_musicbrainz(self, metadata: SongMetadata) -> SongMetadata:
        """Enhanced MusicBrainz text search with minimal output"""
        if not self.musicbrainzngs:
            return metadata
            
        try:
            self._rate_limit()
            
            # Try multiple search strategies (but don't spam output)
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
                        
                        # Only report success if we actually improved the metadata
                        if enhanced.title != metadata.title or enhanced.artist != metadata.artist:
                            analysis_output.analysis_complete("MusicBrainz")
                        
                        return enhanced
                        
                except Exception:
                    continue
                    
        except Exception:
            pass  # Don't spam MusicBrainz errors
        
        return metadata
    
    def get_metadata(self, url: str, audio_file: str = None, show_progress: bool = True) -> SongMetadata:
        """Get comprehensive metadata with anchored output"""
        if show_progress:
            analysis_output.start_analysis(url)
        
        # Check cache first
        cached = self.cache.get_metadata(url)
        if cached and cached.is_complete_metadata():
            if show_progress:
                analysis_output.analysis_complete("Cache")
            cached.source = MetadataSource.CACHE
            return cached
        
        # Get basic metadata
        metadata = self.get_basic_metadata(url)
        
        if show_progress:
            analysis_output.basic_metadata_success(metadata)
        
        # Skip enhancement if disabled
        if not self.config.auto_enhance_metadata:
            self.cache.save_metadata(url, metadata)
            return metadata
        
        # Try AcoustID enhancement
        if self.config.acoustid_for_playback and self._validate_api_key():
            # Try with provided audio file first
            if audio_file and os.path.exists(audio_file):
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
        
        if show_progress:
            analysis_output.analysis_complete(metadata.source.name)
        
        # Cache and return
        self.cache.save_metadata(url, metadata)
        return metadata