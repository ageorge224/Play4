#!/usr/bin/env python3
"""
Main application with Anchored Progress System - Fixed Version
Separates progress bar from analysis output for clean display
Avoids circular imports
"""
import sys
import os
import signal
import time
import threading
import subprocess
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Set, Optional, Tuple
from pathlib import Path

# Local imports
from .config import Config
from .metadata import MetadataCache, SongMetadata, MetadataSource
from .player import play_song, Colors
from .downloads import DownloadManager
from .terminal import TerminalHandler
from .utils import setup_logging
from .fast_queue_manager import FastQueueManager, QueueItem, SourceType
from .compact_progress_system import (
    compact_terminal,
    CompactPlaybackProgress,
    compact_analysis,
)
from .anchored_progress_system import EnhancedPlaybackProgress
from .enhanced_session_manager import SessionManager
from .fixed_metadata_fetcher_no_circular import EnhancedMetadataFetcher


class PlayerState:
    def __init__(self, config: Config):
        self.config = config
        self.current_mpv_process: Optional[subprocess.Popen] = None
        self.should_exit = False
        self.active_downloads = []
        self.downloads_lock = threading.Lock()
        self.downloads_count = 0
        self.already_downloading: Set[str] = set()
        self.paused = False
        self.current_song_url = None
        self.current_metadata = None
        self.failed_downloads = {}
        self.executor = ThreadPoolExecutor(max_workers=config.max_workers)

        # Enhanced components
        self.cache = MetadataCache(config.cache_db, config.max_cache_age_days)
        self.metadata_fetcher = EnhancedMetadataFetcher(self.cache, config)
        self.queue_manager = FastQueueManager(
            config, self.metadata_fetcher, self.executor
        )
        self.session_manager = SessionManager(config)

def enhanced_play_song(
    url: str, metadata: SongMetadata
) -> Tuple[subprocess.Popen, EnhancedPlaybackProgress]:
    """Enhanced play_song that uses anchored progress"""
    print(f"{Colors.GREEN}▶️ Playing: {url[:60]}...{Colors.END}")
    print(f"{Colors.CYAN}🎵 {metadata.artist} - {metadata.title}{Colors.END}")
    print(
        f"{Colors.DIM}   Album: {metadata.album} | Duration: {metadata.format_duration()}{Colors.END}"
    )

    # Enhanced mpv command
    mpv_cmd = [
        "mpv",
        "--no-video",
        "--quiet",
        "--no-terminal",
        "--profile=edifier",
        url,
    ]

    process = subprocess.Popen(
        mpv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    display_title = f"{metadata.artist} - {metadata.title}"
    progress = CompactPlaybackProgress(metadata.duration, display_title)
    compact_terminal.initialize_display()

    # Initialize the progress area
    terminal_manager.initialize_progress_area()

    return process, progress


def enhanced_playback_loop(state: PlayerState):
    """Enhanced main playback loop with anchored progress system"""
    terminal = TerminalHandler()
    download_manager = DownloadManager(state.config, state)

    print(f"\n{Colors.YELLOW}🎮 Enhanced Controls:{Colors.END}")
    print(f"{Colors.YELLOW} 1-4 {Colors.END}- Rate song (downloads in background)")
    print(f"{Colors.YELLOW} 'p' or space {Colors.END}- Pause/Resume")
    print(f"{Colors.YELLOW} 's' {Colors.END}- Skip song")
    print(f"{Colors.YELLOW} 'm' {Colors.END}- Show detailed metadata")
    print(f"{Colors.YELLOW} 'i' {Colors.END}- Show download/queue statistics")
    print(f"{Colors.YELLOW} 'b' {Colors.END}- Show queue buffer status")
    print(f"{Colors.YELLOW} 'c' {Colors.END}- Compact mode (clear screen)")
    print(f"{Colors.YELLOW} 'q' {Colors.END}- Quit program")
    print(f"{Colors.CYAN}{'-' * 60}{Colors.END}")

    song_count = 0

    while not state.should_exit:
        # Get next song from smart queue
        queue_item = state.queue_manager.get_next_song()
        if not queue_item:
            compact_terminal.update_status("⏳ Waiting for more songs to be analyzed...")
            time.sleep(2)
            continue

        song_count += 1
        # Update session progress
        if hasattr(state, 'session_manager'):
            state.session_manager.update_session_progress(song_count - 1, queue_item.path_or_url)

        # Determine if this is a local file or YouTube URL
        if queue_item.source_type == SourceType.LOCAL_FILE:
            print(f"\n{Colors.BOLD}🎵 Local Song #{song_count}{Colors.END}")
            # For local files, use file:// URL for mpv
            play_url = queue_item.path_or_url
            state.current_song_url = f"file://{queue_item.path_or_url}"
        else:
            print(f"\n{Colors.BOLD}🌐 YouTube Song #{song_count}{Colors.END}")
            play_url = queue_item.path_or_url
            state.current_song_url = queue_item.path_or_url

        # Use the metadata we already have
        metadata = queue_item.metadata or SongMetadata()
        state.current_metadata = metadata

        # Show queue source info
        queue_stats = state.queue_manager.get_stats()
        if queue_item.source_type == SourceType.LOCAL_FILE:
            status_text = (
                f"📁 Local Collection ({queue_stats['local_remaining']} remaining)"
            )
        else:
            source_info = f"Pre-analyzed" if queue_item.metadata_ready else "Live"
            acoustid_info = (
                f" | AcoustID: {'✅' if queue_item.acoustid_analyzed else '❓'}"
            )
            status_text = f"🌐 YouTube Queue ({source_info}{acoustid_info})"

        compact_terminal.update_status(status_text)

        mpv_proc, progress = enhanced_play_song(play_url, metadata)
        state.current_mpv_process = mpv_proc
        saved_this_song = False
        song_done = False
        last_progress_update = 0
        terminal.clear_buffer()

        while not song_done and not state.should_exit:
            # Check if song ended
            if not state.paused and mpv_proc.poll() is not None:
                song_done = True
                break

            # Update progress every second
            current_time = time.time()
            if current_time - last_progress_update >= 1.0:
                if not state.paused:
                    progress.display()
                last_progress_update = current_time

            # Handle input
            key = terminal.get_keypress(timeout=0.5)
            if key:
                # Use compact mode for user interactions
                terminal_manager.clear_for_user_input()

                if key == "q":
                    print(f"{Colors.YELLOW}🛑 Quitting...{Colors.END}")
                    state.should_exit = True
                    if mpv_proc.poll() is None:
                        mpv_proc.terminate()
                    song_done = True

                elif key in state.config.music_dirs and not saved_this_song:
                    star_name = ["", "⭐", "⭐⭐", "⭐⭐⭐", "⭐⭐⭐⭐"][int(key)]
                    print(
                        f"{Colors.GREEN}{star_name} Rating {key} stars - Download started{Colors.END}"
                    )
                    # For local files, use the original URL for downloading
                    download_url = (
                        queue_item.path_or_url
                        if queue_item.source_type == SourceType.YOUTUBE_URL
                        else state.current_song_url
                    )
                    download_manager.download_song_background(
                        download_url, state.config.music_dirs[key]
                    )
                    saved_this_song = True

                elif key in ["p", " "]:
                    try:
                        if not state.paused:
                            os.kill(mpv_proc.pid, signal.SIGTSTP)
                            progress.pause()
                            print(f"{Colors.YELLOW}⏸️ PAUSED{Colors.END}")
                            state.paused = True
                        else:
                            os.kill(mpv_proc.pid, signal.SIGCONT)
                            progress.resume()
                            print(f"{Colors.GREEN}▶️ RESUMED{Colors.END}")
                            state.paused = False
                    except (ProcessLookupError, OSError):
                        song_done = True

                elif key == "s":
                    print(f"{Colors.YELLOW}⏭️ Skipping{Colors.END}")
                    if state.paused:
                        try:
                            os.kill(mpv_proc.pid, signal.SIGCONT)
                            state.paused = False
                        except:
                            pass
                    mpv_proc.terminate()
                    song_done = True

                elif key == "c":
                    # Compact mode - clear screen and show minimal info
                    terminal_manager.initialize_progress_area()
                    print(
                        f"{Colors.GREEN}🎵 Now Playing: {metadata.artist} - {metadata.title}{Colors.END}"
                    )
                    print(f"{Colors.CYAN}Progress will resume below...{Colors.END}")
                    compact_terminal.initialize_display()

                elif key == "m":
                    if state.current_metadata:
                        metadata = state.current_metadata
                        print(f"\n{Colors.CYAN}🎵 Detailed Metadata:{Colors.END}")
                        print(f"  {Colors.BOLD}Title:{Colors.END} {metadata.title}")
                        print(f"  {Colors.BOLD}Artist:{Colors.END} {metadata.artist}")
                        print(f"  {Colors.BOLD}Album:{Colors.END} {metadata.album}")
                        print(
                            f"  {Colors.BOLD}Duration:{Colors.END} {metadata.format_duration()}"
                        )
                        print(
                            f"  {Colors.BOLD}Source:{Colors.END} {metadata.source.name}"
                        )
                        if metadata.acoustid_attempted:
                            acoustid_status = (
                                "✅ Success"
                                if metadata.source == MetadataSource.ACOUSTID
                                else "❓ No confident match"
                            )
                            print(
                                f"  {Colors.BOLD}AcoustID Status:{Colors.END} {acoustid_status}"
                            )
                        if metadata.genres:
                            print(
                                f"  {Colors.BOLD}Genres:{Colors.END} {', '.join(metadata.genres)}"
                            )
                        if metadata.year:
                            print(f"  {Colors.BOLD}Year:{Colors.END} {metadata.year}")
                        if metadata.acoustid:
                            print(
                                f"  {Colors.BOLD}AcoustID:{Colors.END} {metadata.acoustid[:8]}..."
                            )
                        if metadata.musicbrainz_id:
                            print(
                                f"  {Colors.BOLD}MusicBrainz ID:{Colors.END} {metadata.musicbrainz_id}"
                            )
                        if metadata.confidence > 0:
                            print(
                                f"  {Colors.BOLD}Confidence:{Colors.END} {metadata.confidence:.1%}"
                            )

                        # Show source-specific info
                        if queue_item.source_type == SourceType.LOCAL_FILE:
                            file_path = Path(queue_item.path_or_url)
                            print(f"  {Colors.BOLD}File:{Colors.END} {file_path.name}")
                            print(
                                f"  {Colors.BOLD}Location:{Colors.END} {file_path.parent.name}"
                            )
                        else:
                            print(
                                f"  {Colors.BOLD}URL:{Colors.END} {queue_item.path_or_url[:60]}..."
                            )

                        print(
                            f"\n{Colors.CYAN}Press any key to continue...{Colors.END}"
                        )
                        terminal.get_keypress(timeout=10)
                        compact_terminal.initialize_display()

                elif key == "i":
                    # Show comprehensive statistics
                    print(f"\n{Colors.CYAN}📊 System Statistics:{Colors.END}")

                    # Download stats
                    completed_count = 0
                    with state.downloads_lock:
                        for future in state.active_downloads[:]:
                            if future.done():
                                completed_count += 1
                                state.active_downloads.remove(future)

                    print(
                        f"  {Colors.BOLD}Downloads:{Colors.END} {state.downloads_count} completed, {len(state.already_downloading)} active"
                    )
                    if completed_count > 0:
                        print(
                            f"  {Colors.GREEN}✅ {completed_count} downloads just completed!{Colors.END}"
                        )
                    if state.failed_downloads:
                        print(
                            f"  {Colors.RED}Failed:{Colors.END} {len(state.failed_downloads)} downloads"
                        )

                    # Queue stats
                    queue_stats = state.queue_manager.get_stats()
                    print(f"  {Colors.BOLD}Queue Status:{Colors.END}")
                    print(f"    Local: {queue_stats['local_remaining']} remaining")
                    print(
                        f"    YouTube: {queue_stats['youtube_remaining']} total, {queue_stats['ready_buffer_size']} ready"
                    )
                    print(
                        f"    Analysis: {queue_stats['metadata_analyzed']} done, {queue_stats['currently_analyzing']} in progress"
                    )
                    print(
                        f"    AcoustID: {queue_stats['acoustid_analyzed']} successfully identified"
                    )

                    print(f"\n{Colors.CYAN}Press any key to continue...{Colors.END}")
                    terminal.get_keypress(timeout=10)
                    terminal_manager.initialize_progress_area()

                elif key == "b":
                    # Show detailed queue buffer status
                    state.queue_manager.show_status()
                    print(f"\n{Colors.CYAN}Press any key to continue...{Colors.END}")
                    terminal.get_keypress(timeout=10)
                    terminal_manager.initialize_progress_area()

                else:
                    print(f"{Colors.RED}❓ Unknown command '{key}'{Colors.END}")
                    print(
                        f"{Colors.DIM}Valid: 1-4 (rate), p/space (pause), s (skip), m (metadata), i (info), b (buffer), c (compact), q (quit){Colors.END}"
                    )
                    time.sleep(1)

            # Check for completed downloads (but don't spam output)
            if saved_this_song:
                with state.downloads_lock:
                    for future in state.active_downloads[:]:
                        if future.done():
                            try:
                                result = future.result()
                                if result:
                                    compact_analysis.add_message(
                                        f"Download completed: {os.path.basename(result)}",
                                        "success",
                                    )
                                    state.active_downloads.remove(future)
                            except Exception as e:
                                analysis_output.add_analysis_message(
                                    f"Download failed: {str(e)[:30]}...", "error"
                                )
                                state.active_downloads.remove(future)

            time.sleep(0.1)


def main():
    """Main entry point with anchored progress system"""
    logger = setup_logging()
    config = Config.load_from_file()
    state = PlayerState(config)

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        print(f"\n{Colors.YELLOW}🛑 Gracefully shutting down...{Colors.END}")
        state.should_exit = True
        if state.current_mpv_process and state.current_mpv_process.poll() is None:
            state.current_mpv_process.terminate()
        state.queue_manager.cleanup()
        state.executor.shutdown(wait=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(
        f"{Colors.HEADER}🎵 Play4.py Enhanced Music Player with Anchored Progress{Colors.END}"
    )
    print(
        f"{Colors.CYAN}Version 4.2 - Modular with Smart Queue & Clean Output{Colors.END}"
    )

    # Show config location
    config_location = config.get_config_location()
    print(f"{Colors.DIM}📁 Config: {config_location}{Colors.END}")

    # Show AcoustID status
    if config.auto_enhance_metadata:
        if config.acoustid_api_key and len(config.acoustid_api_key.strip()) >= 8:
            print(
                f"{Colors.GREEN}✅ AcoustID integration enabled (key: {config.acoustid_api_key[:4]}...){Colors.END}"
            )
        else:
            print(
                f"{Colors.YELLOW}⚠️ AcoustID disabled - invalid or missing API key{Colors.END}"
            )
            print(
                f"{Colors.YELLOW}   Get a key from: https://acoustid.org/api-key{Colors.END}"
            )
            print(f"{Colors.YELLOW}   Add it to: {config_location}{Colors.END}")
    else:
        print(f"{Colors.YELLOW}ℹ️ Metadata enhancement disabled in config{Colors.END}")

    # Setup music directories
    for star, folder in config.music_dirs.items():
        folder_path = Path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        existing_count = len(list(folder_path.glob("*.flac")))
        print(
            f"{Colors.GREEN}✅ {star}-star folder: {folder} ({existing_count} songs){Colors.END}"
        )

    # Initialize fast queue system
    print(f"\n{Colors.HEADER}🚀 Initializing Fast Queue System...{Colors.END}")
    has_local_files = state.queue_manager.initialize()

    if has_local_files:
        print(
            f"{Colors.GREEN}🎵 Starting immediate playback from local collection!{Colors.END}"
        )
        print(f"{Colors.CYAN}   YouTube playlists loading in background...{Colors.END}")
        print(f"{Colors.CYAN}   Metadata analysis running in background...{Colors.END}")
    else:
        print(
            f"{Colors.YELLOW}⏳ No local files found, waiting for YouTube playlist loading...{Colors.END}"
        )
        # Wait a bit for playlists to load
        time.sleep(3)

    # Save config to local directory if it doesn't exist
    config_location = config.get_config_location()
    if not os.path.exists(config_location):
        print(f"{Colors.CYAN}💾 Creating local config file...{Colors.END}")
        config.save_to_file()

    # Start enhanced playback loop
    enhanced_playback_loop(state)

    # Final statistics
    final_stats = state.queue_manager.get_stats()
    print(f"\n{Colors.GREEN}{Colors.BOLD}🎵 Session Complete!{Colors.END}")
    print(f"{Colors.CYAN}📊 Final Statistics:{Colors.END}")
    print(f"  {Colors.BOLD}Songs Downloaded:{Colors.END} {state.downloads_count}")
    print(
        f"  {Colors.BOLD}Metadata Analyzed:{Colors.END} {final_stats['metadata_analyzed']}"
    )
    print(
        f"  {Colors.BOLD}AcoustID Successes:{Colors.END} {final_stats['acoustid_analyzed']}"
    )
    print(f"  {Colors.BOLD}Failed Downloads:{Colors.END} {len(state.failed_downloads)}")

    # Cleanup
    state.queue_manager.cleanup()
    state.executor.shutdown(wait=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
