"""
Audio management for StudyCompanion add-on.
Handles background audio playback with 3-playlist day-based rotation.

Playlist Rules (within a 21-day study cycle):
- Playlist 1: Plays every day (1-31), loops forever
- Playlist 2: Plays on odd days 1, 5, 9, 13, 17, 21, 25, 29 (no loop)
- Playlist 3: Plays on odd days 3, 7, 11, 15, 19, 23, 27, 31 (no loop)
- Even days: Only Playlist 1

Cycle System:
- 21 days study + 5 days break = 26 day cycle
- During break days: No audio plays at all
- After break, cycle restarts from Day 1

Playback order: Non-looping playlists play first, then looping playlist.
Only ONE playlist plays at a time (sequential, not simultaneous).

IMPORTANT: Uses macOS's native afplay command for audio playback to avoid
Qt's FFmpeg audio renderer crashes on Bluetooth disconnect.
"""

import os
import subprocess
import threading
import re
import atexit
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional, Dict

SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}

# Audio is always available on macOS via afplay
_AUDIO_AVAILABLE = True

# Global state for 3-playlist system
_audio_volume: int = 50
_native_process = None
_native_playing = False
_current_playlist_id: int = 0  # 0=none, 1/2/3=playlist ID
_current_track_index: int = 0
_playlists: dict = {}  # {1: [files], 2: [files], 3: [files]}
_playlist_loops: dict = {}  # {1: True, 2: False, 3: False}
_playback_queue: List[Tuple[int, bool]] = []  # [(playlist_id, loops), ...]
_queue_index: int = 0
_cfg_ref: dict = {}  # Reference to config for saving track positions

# Track timing for progress display
_track_start_time: float = 0.0  # When current track started playing
_track_duration: float = 0.0    # Duration of current track in seconds
_track_paused: bool = False     # Is playback paused?
_track_paused_position: float = 0.0  # Position when paused


def _atexit_cleanup():
    """Emergency cleanup when Python exits - kill all afplay processes."""
    try:
        subprocess.run(["pkill", "-9", "afplay"], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        pass

# Register atexit handler as fallback (in case Anki is force-quit)
atexit.register(_atexit_cleanup)


def _get_audio_duration(filepath: str) -> float:
    """Get audio file duration in seconds using afinfo."""
    try:
        result = subprocess.run(
            ["afinfo", "-b", filepath],
            capture_output=True,
            text=True,
            timeout=5
        )
        # Parse output for duration
        for line in result.stdout.split('\n'):
            if 'estimated duration:' in line.lower():
                # Format: "estimated duration: 234.567 sec"
                parts = line.split(':')
                if len(parts) >= 2:
                    duration_str = parts[1].strip().replace('sec', '').strip()
                    return float(duration_str)
        # Alternative: look for "duration" in seconds
        for line in result.stdout.split('\n'):
            if 'duration' in line.lower() and 'sec' in line.lower():
                import re as regex
                match = regex.search(r'([\d.]+)\s*sec', line.lower())
                if match:
                    return float(match.group(1))
    except Exception as e:
        print(f"[StudyCompanion] Could not get duration for {filepath}: {e}")
    return 0.0


import time as _time


def _natural_key(text: str):
    """Natural sort key for filenames with numbers."""
    parts = re.split(r"(\d+)", text)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


def _folder_audio_files(folder: str) -> List[str]:
    """Get sorted audio files from a folder."""
    try:
        entries = os.listdir(folder)
    except Exception:
        return []
    files = [
        os.path.join(folder, f)
        for f in entries
        if os.path.splitext(f)[1].lower() in SUPPORTED_AUDIO_EXTS
    ]
    files.sort(key=lambda p: _natural_key(os.path.basename(p)))
    return files


def _expand_source(path: str) -> List[str]:
    """Expand a path (file or folder) to list of audio files."""
    p = str(path or "").strip()
    if not p:
        return []
    if os.path.isdir(p):
        return _folder_audio_files(p)
    if os.path.isfile(p) and os.path.splitext(p)[1].lower() in SUPPORTED_AUDIO_EXTS:
        return [p]
    return []


def get_current_day() -> int:
    """Get current day of month (1-31)."""
    return datetime.now().day


def get_cycle_info(cfg: dict, for_date: date = None) -> Dict:
    """
    Calculate cycle information for a given date.
    
    Returns dict with:
    - cycle_day: Day within current cycle (1-26, where 1-21 are study, 22-26 are break)
    - is_break: True if this is a break day
    - study_day: Effective day for playlist rules (1-21, or 0 if break)
    - cycle_number: Which cycle we're in (1, 2, 3, ...)
    - cycle_start: Start date of current cycle
    - cycle_end: End date of current cycle
    """
    if for_date is None:
        for_date = date.today()
    
    start_str = cfg.get("audio_cycle_start_date", "")
    study_days = int(cfg.get("audio_cycle_study_days", 21) or 21)
    break_days = int(cfg.get("audio_cycle_break_days", 5) or 5)
    cycle_length = study_days + break_days
    
    # If no start date set, use a default start date (Jan 1 of current year)
    # This way cycle days still make sense
    if not start_str:
        # Use Jan 1 of the year as implicit start
        implicit_start = date(for_date.year, 1, 1)
        days_elapsed = (for_date - implicit_start).days
        cycle_number = (days_elapsed // cycle_length) + 1
        day_in_cycle = (days_elapsed % cycle_length) + 1
        is_break = day_in_cycle > study_days
        study_day = day_in_cycle if not is_break else 0
        
        return {
            "cycle_day": day_in_cycle,
            "is_break": is_break,
            "study_day": study_day,
            "cycle_number": cycle_number,
            "cycle_start": implicit_start + timedelta(days=(cycle_number - 1) * cycle_length),
            "cycle_end": implicit_start + timedelta(days=cycle_number * cycle_length - 1),
            "no_cycle_configured": True,
        }
    
    try:
        cycle_start = datetime.strptime(start_str, "%Y-%m-%d").date()
    except ValueError:
        # Invalid date format, fallback to implicit start
        implicit_start = date(for_date.year, 1, 1)
        days_elapsed = (for_date - implicit_start).days
        cycle_number = (days_elapsed // cycle_length) + 1
        day_in_cycle = (days_elapsed % cycle_length) + 1
        is_break = day_in_cycle > study_days
        study_day = day_in_cycle if not is_break else 0
        
        return {
            "cycle_day": day_in_cycle,
            "is_break": is_break,
            "study_day": study_day,
            "cycle_number": cycle_number,
            "cycle_start": implicit_start + timedelta(days=(cycle_number - 1) * cycle_length),
            "cycle_end": implicit_start + timedelta(days=cycle_number * cycle_length - 1),
            "no_cycle_configured": True,
        }
    
    # Calculate days since cycle start
    days_elapsed = (for_date - cycle_start).days
    
    if days_elapsed < 0:
        # Date is before cycle start - no audio
        return {
            "cycle_day": 0,
            "is_break": True,
            "study_day": 0,
            "cycle_number": 0,
            "cycle_start": cycle_start,
            "cycle_end": cycle_start + timedelta(days=cycle_length - 1),
            "before_start": True,
        }
    
    # Which cycle are we in?
    cycle_number = (days_elapsed // cycle_length) + 1
    day_in_cycle = (days_elapsed % cycle_length) + 1  # 1-based
    
    # Calculate current cycle's start and end dates
    current_cycle_start = cycle_start + timedelta(days=(cycle_number - 1) * cycle_length)
    current_cycle_end = current_cycle_start + timedelta(days=cycle_length - 1)
    
    # Is this a break day?
    is_break = day_in_cycle > study_days
    
    # Effective study day (1-21 for study, 0 for break)
    study_day = day_in_cycle if not is_break else 0
    
    return {
        "cycle_day": day_in_cycle,
        "is_break": is_break,
        "study_day": study_day,
        "cycle_number": cycle_number,
        "cycle_start": current_cycle_start,
        "cycle_end": current_cycle_end,
    }


def get_effective_day(cfg: dict) -> int:
    """Get effective day considering manual override and cycle."""
    if cfg.get("audio_playlist_override_enabled", False):
        override_day = int(cfg.get("audio_playlist_override_day", 1) or 1)
        return max(1, min(31, override_day))
    
    # Use cycle-based study day
    cycle_info = get_cycle_info(cfg)
    if cycle_info.get("is_break", False):
        return 0  # Break day - no audio
    return cycle_info.get("study_day", get_current_day())


def get_playlists_for_day(day: int) -> List[Tuple[int, bool]]:
    """
    Get list of (playlist_id, loops) for a given day.
    Returns in playback order: non-looping first, then looping.
    
    Rules:
    - Day 0: Break day - no playlists
    - Playlist 1: Every day (loops)
    - Playlist 2: Days 1, 5, 9, 13, 17, 21 (no loop) - pattern: day % 4 == 1
    - Playlist 3: Days 3, 7, 11, 15, 19 (no loop) - pattern: day % 4 == 3
    - Even days: Only Playlist 1
    """
    playlists = []
    
    # Break day - no audio
    if day == 0:
        return playlists
    
    # Even days: only Playlist 1
    if day % 2 == 0:
        playlists.append((1, True))  # loops
    else:
        # Odd days
        # Pattern for P2: 1, 5, 9, 13, 17, 21 (day % 4 == 1, day <= 21)
        # Pattern for P3: 3, 7, 11, 15, 19 (day % 4 == 3, day <= 19)
        if day % 4 == 1 and day <= 21:
            # P2 first (no loop), then P1 (loops)
            playlists.append((2, False))
            playlists.append((1, True))
        elif day % 4 == 3 and day <= 19:
            # P3 first (no loop), then P1 (loops)
            playlists.append((3, False))
            playlists.append((1, True))
        else:
            # Other odd days (like day 23, 25, etc if cycle is longer)
            playlists.append((1, True))
    
    return playlists


def get_tracks_for_day(cfg: dict, day: int) -> Dict[int, List[str]]:
    """
    Get track names that would play on a given day.
    Returns {playlist_id: [track_names]} for display in calendar.
    """
    playlists = get_playlists_for_day(day)
    result = {}
    
    for pid, loops in playlists:
        path = cfg.get(f"audio_playlist_{pid}_path", "")
        enabled = cfg.get(f"audio_playlist_{pid}_enabled", True)
        
        if not enabled or not path:
            result[pid] = []
            continue
        
        files = _expand_source(path)
        # Get just the filenames without path
        track_names = [os.path.basename(f) for f in files]
        result[pid] = track_names
    
    return result


def get_playlist_names_for_day(day: int) -> List[str]:
    """Get human-readable playlist names for a day."""
    playlists = get_playlists_for_day(day)
    names = []
    for pid, loops in playlists:
        suffix = " (loops)" if loops else ""
        names.append(f"Playlist {pid}{suffix}")
    return names


def send_macos_notification(title: str, message: str) -> None:
    """Send a macOS notification using osascript."""
    try:
        # Escape quotes in the message
        message = message.replace('"', '\\"').replace("'", "\\'")
        title = title.replace('"', '\\"').replace("'", "\\'")
        script = f'display notification "{message}" with title "{title}"'
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[StudyCompanion] Notification error: {e}")


def _save_track_position(playlist_id: int, track_index: int, time_position: float = 0.0) -> None:
    """Save track index and time position to config for resume."""
    global _cfg_ref
    try:
        from .config_manager import write_config, get_config
        cfg = get_config()
        cfg[f"audio_track_position_{playlist_id}"] = track_index
        cfg[f"audio_time_position_{playlist_id}"] = time_position
        write_config(cfg)
        _cfg_ref = cfg
        print(f"[StudyCompanion] Saved position: P{playlist_id} Track {track_index}, Time {time_position:.1f}s")
    except Exception as e:
        print(f"[StudyCompanion] Failed to save track position: {e}")


def _get_track_position(cfg: dict, playlist_id: int) -> int:
    """Get saved track position from config."""
    return int(cfg.get(f"audio_track_position_{playlist_id}", 0) or 0)


def _mark_playlist_completed_today(playlist_id: int) -> None:
    """Mark a non-looping playlist as completed for today."""
    global _cfg_ref
    try:
        from .config_manager import write_config, get_config
        from datetime import date
        cfg = get_config()
        today_str = date.today().isoformat()  # e.g., "2026-01-14"
        cfg[f"audio_playlist_{playlist_id}_completed_date"] = today_str
        # Also reset track position to 0 for next cycle
        cfg[f"audio_track_position_{playlist_id}"] = 0
        cfg[f"audio_time_position_{playlist_id}"] = 0
        write_config(cfg)
        _cfg_ref = cfg
        print(f"[StudyCompanion] Playlist {playlist_id} marked as completed for {today_str}")
    except Exception as e:
        print(f"[StudyCompanion] Failed to mark playlist completed: {e}")


def _is_playlist_completed_today(cfg: dict, playlist_id: int) -> bool:
    """Check if a non-looping playlist has already completed today."""
    try:
        from datetime import date
        completed_date = cfg.get(f"audio_playlist_{playlist_id}_completed_date", "")
        today_str = date.today().isoformat()
        return completed_date == today_str
    except Exception:
        return False


def _stop_current_process() -> None:
    """Stop and wait for the current afplay process to fully terminate."""
    global _native_process
    
    if _native_process:
        try:
            _native_process.terminate()
            try:
                _native_process.wait(timeout=0.5)
            except Exception:
                _native_process.kill()
                try:
                    _native_process.wait(timeout=0.5)
                except Exception:
                    pass
        except Exception:
            pass
        _native_process = None
    
    # Also kill any stray afplay processes to be safe
    _kill_all_afplay()


def _native_play_current_track() -> None:
    """Play current track using macOS afplay command."""
    global _native_process, _native_playing, _current_track_index, _current_playlist_id
    global _track_start_time, _track_duration, _track_paused
    
    # CRITICAL: Stop any existing playback before starting new track
    _stop_current_process()
    
    if _current_playlist_id == 0 or _current_playlist_id not in _playlists:
        _native_playing = False
        return
    
    playlist = _playlists.get(_current_playlist_id, [])
    if not playlist or _current_track_index >= len(playlist):
        # End of current playlist, move to next in queue
        _advance_to_next_playlist()
        return
    
    path = playlist[_current_track_index]
    if not os.path.exists(path):
        # Skip missing file
        _current_track_index += 1
        _save_track_position(_current_playlist_id, _current_track_index)
        _native_play_current_track()
        return
    
    try:
        # Get track duration for progress display
        _track_duration = _get_audio_duration(path)
        _track_start_time = _time.time()
        _track_paused = False
        
        vol = max(0.0, min(1.0, _audio_volume / 100.0))
        _native_process = subprocess.Popen(
            ["afplay", "-v", str(vol), path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        _native_playing = True
        
        # Wait for completion in background thread
        def _wait_and_next():
            global _native_playing, _current_track_index
            try:
                if _native_process:
                    _native_process.wait()
                
                if not _native_playing:
                    return  # Stopped manually
                
                # Track finished naturally - reset time tracking
                global _track_start_time
                _track_start_time = 0
                
                # Move to next track
                _current_track_index += 1
                _save_track_position(_current_playlist_id, _current_track_index, 0.0)  # Reset time to 0
                
                # Check if we've finished this playlist
                playlist = _playlists.get(_current_playlist_id, [])
                loops = _playlist_loops.get(_current_playlist_id, False)
                
                if _current_track_index >= len(playlist):
                    if loops:
                        # Loop back to start
                        _current_track_index = 0
                        _save_track_position(_current_playlist_id, 0)
                        _native_play_current_track()
                    else:
                        # Move to next playlist in queue
                        _advance_to_next_playlist()
                else:
                    _native_play_current_track()
                    
            except Exception as e:
                print(f"[StudyCompanion] Native audio error: {e}")
                _native_playing = False
        
        thread = threading.Thread(target=_wait_and_next, daemon=True)
        thread.start()
        
    except Exception as e:
        print(f"[StudyCompanion] Failed to start native audio: {e}")
        _native_playing = False


def _advance_to_next_playlist() -> None:
    """Move to next playlist in the queue."""
    global _queue_index, _current_playlist_id, _current_track_index, _native_playing
    
    # Mark the current (finished) playlist as completed if it doesn't loop
    if _current_playlist_id > 0:
        loops = _playlist_loops.get(_current_playlist_id, False)
        if not loops:
            _mark_playlist_completed_today(_current_playlist_id)
            print(f"[StudyCompanion] Playlist {_current_playlist_id} finished (non-looping)")
    
    _queue_index += 1
    
    if _queue_index >= len(_playback_queue):
        # All playlists finished
        _native_playing = False
        _current_playlist_id = 0
        print("[StudyCompanion] All playlists finished for today")
        return
    
    # Start next playlist
    next_pid, next_loops = _playback_queue[_queue_index]
    _start_playlist(next_pid, next_loops)


def _start_playlist(playlist_id: int, loops: bool) -> None:
    """Start playing a specific playlist."""
    global _current_playlist_id, _current_track_index, _native_playing
    global _track_paused, _track_paused_position, _queue_index, _cfg_ref
    
    # CRITICAL: Stop any existing playback before starting new playlist
    _stop_current_process()
    
    # Reload config to get fresh saved positions
    from .config_manager import get_config
    _cfg_ref = get_config()
    
    playlist = _playlists.get(playlist_id, [])
    if not playlist:
        print(f"[StudyCompanion] Playlist {playlist_id} is empty, skipping")
        _advance_to_next_playlist()
        return
    
    # Check if this non-looping playlist already completed today
    if not loops and _is_playlist_completed_today(_cfg_ref, playlist_id):
        print(f"[StudyCompanion] Playlist {playlist_id} already completed today, skipping to next")
        # Move to next playlist without marking this one completed again
        next_queue_index = _queue_index + 1
        if next_queue_index < len(_playback_queue):
            _queue_index = next_queue_index
            next_pid, next_loops = _playback_queue[_queue_index]
            _start_playlist(next_pid, next_loops)
        else:
            _native_playing = False
            _current_playlist_id = 0
            print("[StudyCompanion] All playlists finished for today")
        return
    
    _current_playlist_id = playlist_id
    _playlist_loops[playlist_id] = loops
    
    print(f"[StudyCompanion] P{playlist_id} loops={loops}")
    
    # Resume from saved track position
    saved_track = _get_track_position(_cfg_ref, playlist_id)
    if saved_track >= len(playlist):
        # Non-looping playlist was at the end - it should have been marked completed
        # But just in case, reset to 0 for looping playlists
        if loops:
            saved_track = 0
        else:
            # This shouldn't happen if completion tracking works, but handle it
            print(f"[StudyCompanion] Playlist {playlist_id} track position at end, marking completed")
            _mark_playlist_completed_today(playlist_id)
            _advance_to_next_playlist()
            return
    _current_track_index = saved_track
    
    # Note: afplay doesn't support seeking, so we can only resume from track, not time position
    # Clear any saved time position since we can't use it
    if float(_cfg_ref.get(f"audio_time_position_{playlist_id}", 0) or 0) > 0:
        print(f"[StudyCompanion] Note: Cannot resume from time position (afplay limitation), starting track from beginning")
        _cfg_ref[f"audio_time_position_{playlist_id}"] = 0
        from .config_manager import write_config
        write_config(_cfg_ref)
    
    # Reset pause state
    _track_paused = False
    _track_paused_position = 0
    
    # Notify user
    if _cfg_ref.get("audio_show_notifications", True):
        loop_text = " (looping)" if loops else ""
        track_name = os.path.basename(playlist[_current_track_index]) if playlist else "Unknown"
        send_macos_notification(
            "StudyCompanion Audio",
            f"Now playing: Playlist {playlist_id}{loop_text} - {track_name}"
        )
    
    print(f"[StudyCompanion] Starting Playlist {playlist_id}, track {_current_track_index + 1}/{len(playlist)}")
    
    # Always play from start of track
    _native_playing = True
    _native_play_current_track()


def _kill_all_afplay() -> None:
    """Kill ALL afplay processes to clean up orphaned audio from previous sessions."""
    try:
        # Use pkill to kill all afplay processes
        subprocess.run(
            ["pkill", "-9", "afplay"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
    except Exception:
        pass


def _native_stop() -> None:
    """Stop native audio playback."""
    global _native_process, _native_playing
    
    _native_playing = False
    if _native_process:
        try:
            _native_process.terminate()
            try:
                _native_process.wait(timeout=1)
            except Exception:
                _native_process.kill()
            _native_process = None
        except Exception:
            pass
    
    # Also kill any orphaned afplay processes
    _kill_all_afplay()


def cleanup_audio_on_quit() -> None:
    """Clean up audio when Anki quits. Called by quit hook."""
    global _current_playlist_id, _current_track_index, _track_start_time, _track_paused, _track_paused_position
    
    print("[StudyCompanion] Cleaning up audio on quit...")
    
    # Save current track position (not time position, since afplay can't seek)
    if _current_playlist_id > 0 and (_native_playing or _track_paused):
        # Just save the track index, time position is always 0 since we can't resume mid-track
        print(f"[StudyCompanion] Saving position: Playlist {_current_playlist_id}, Track {_current_track_index}")
        _save_track_position(_current_playlist_id, _current_track_index, 0.0)
    
    _native_stop()


def setup_audio_player(cfg: dict) -> None:
    """Setup audio player with 3-playlist day-based rotation."""
    global _audio_volume, _playlists, _playlist_loops, _playback_queue
    global _queue_index, _cfg_ref, _current_playlist_id, _current_track_index
    
    if not _AUDIO_AVAILABLE:
        print("[StudyCompanion] Audio not available")
        return
    
    # CRITICAL: Kill ALL afplay processes first (cleanup orphans from previous sessions)
    print("[StudyCompanion] Cleaning up any orphaned audio processes...")
    _kill_all_afplay()
    
    # Stop any existing playback
    _native_stop()
    
    _cfg_ref = cfg
    _audio_volume = int(cfg.get("audio_volume", 50) or 50)
    
    # Load playlists from config
    _playlists = {
        1: _expand_source(cfg.get("audio_playlist_1_path", "")),
        2: _expand_source(cfg.get("audio_playlist_2_path", "")),
        3: _expand_source(cfg.get("audio_playlist_3_path", "")),
    }
    
    # Log playlist info
    for pid in [1, 2, 3]:
        count = len(_playlists[pid])
        path = cfg.get(f"audio_playlist_{pid}_path", "")
        enabled = cfg.get(f"audio_playlist_{pid}_enabled", True)
        print(f"[StudyCompanion] Playlist {pid}: {count} files, enabled={enabled}, path={path}")
    
    # Get cycle info
    cycle_info = get_cycle_info(cfg)
    
    # Check if we're on a break day
    if cycle_info.get("is_break", False):
        if cycle_info.get("before_start", False):
            print("[StudyCompanion] Date is before cycle start - no audio")
        else:
            cycle_day = cycle_info.get("cycle_day", 0)
            study_days = int(cfg.get("audio_cycle_study_days", 21) or 21)
            break_day_num = cycle_day - study_days
            print(f"[StudyCompanion] Break day {break_day_num}/5 - no audio today")
            
            if cfg.get("audio_show_notifications", True):
                send_macos_notification(
                    "StudyCompanion",
                    f"🎉 Break day {break_day_num}/5 - Enjoy your rest!"
                )
        return
    
    # Get effective day (considering override)
    effective_day = get_effective_day(cfg)
    print(f"[StudyCompanion] Study day: {effective_day} (Cycle {cycle_info.get('cycle_number', 1)}, Day {cycle_info.get('cycle_day', effective_day)})")
    
    # Get playlists for today
    _playback_queue = []
    for pid, loops in get_playlists_for_day(effective_day):
        # Only add if enabled and has files
        if cfg.get(f"audio_playlist_{pid}_enabled", True) and _playlists.get(pid, []):
            _playback_queue.append((pid, loops))
    
    if not _playback_queue:
        print("[StudyCompanion] No active playlists for today")
        return
    
    playlist_names = [f"P{pid}" + ("*" if loops else "") for pid, loops in _playback_queue]
    print(f"[StudyCompanion] Today's queue: {' -> '.join(playlist_names)} (* = loops)")
    
    # Start first playlist (only one at a time)
    _queue_index = 0
    first_pid, first_loops = _playback_queue[0]
    _start_playlist(first_pid, first_loops)


def stop_audio() -> None:
    """Stop the audio player."""
    if not _AUDIO_AVAILABLE:
        return
    _native_stop()


def get_current_playback_info() -> dict:
    """Get current playback information for UI display."""
    global _current_playlist_id, _current_track_index, _playlists, _playback_queue, _queue_index
    global _track_start_time, _track_duration, _track_paused, _track_paused_position
    
    playlist = _playlists.get(_current_playlist_id, [])
    track_name = ""
    track_path = ""
    if playlist and 0 <= _current_track_index < len(playlist):
        track_path = playlist[_current_track_index]
        track_name = os.path.basename(track_path)
    
    # Calculate current position
    if _track_paused:
        current_position = _track_paused_position
    elif _native_playing and _track_start_time > 0:
        current_position = _time.time() - _track_start_time
    else:
        current_position = 0.0
    
    # Clamp to duration
    if _track_duration > 0:
        current_position = min(current_position, _track_duration)
    
    return {
        "playing": _native_playing and not _track_paused,
        "paused": _track_paused,
        "playlist_id": _current_playlist_id,
        "track_index": _current_track_index,
        "track_count": len(playlist),
        "track_name": track_name,
        "track_path": track_path,
        "queue_position": _queue_index + 1,
        "queue_total": len(_playback_queue),
        "loops": _playlist_loops.get(_current_playlist_id, False),
        "position": current_position,
        "duration": _track_duration,
    }


def pause_audio() -> None:
    """Pause audio playback."""
    global _track_paused, _track_paused_position, _native_process, _native_playing
    
    if not _native_playing or _track_paused:
        return
    
    # Calculate current position before pausing
    _track_paused_position = _time.time() - _track_start_time
    _track_paused = True
    
    # Kill the current process
    if _native_process:
        try:
            _native_process.terminate()
            _native_process.wait(timeout=1)
        except Exception:
            try:
                _native_process.kill()
            except Exception:
                pass
        _native_process = None


def resume_audio() -> None:
    """Resume audio playback from paused position."""
    global _track_paused, _track_start_time, _native_process, _native_playing
    
    if not _track_paused or _current_playlist_id == 0:
        return
    
    playlist = _playlists.get(_current_playlist_id, [])
    if not playlist or _current_track_index >= len(playlist):
        return
    
    path = playlist[_current_track_index]
    if not os.path.exists(path):
        return
    
    # CRITICAL: Stop any existing playback before resuming
    _stop_current_process()
    
    # Note: afplay doesn't support seeking, so resume just restarts the track from beginning
    _track_paused = False
    _track_paused_position = 0
    _native_playing = True
    _native_play_current_track()


def toggle_pause() -> None:
    """Toggle between play and pause."""
    if _track_paused:
        resume_audio()
    elif _native_playing:
        pause_audio()


def seek_to_position(position: float) -> None:
    """Seek to a specific position in the current track."""
    global _track_paused_position, _track_paused
    
    if _current_playlist_id == 0:
        return
    
    playlist = _playlists.get(_current_playlist_id, [])
    if not playlist or _current_track_index >= len(playlist):
        return
    
    # Clamp position
    position = max(0.0, min(position, _track_duration if _track_duration > 0 else position))
    
    was_playing = _native_playing and not _track_paused
    
    # Stop current playback
    if _native_process:
        try:
            _native_process.terminate()
            _native_process.wait(timeout=1)
        except Exception:
            try:
                _native_process.kill()
            except Exception:
                pass
        _native_process = None
    
    # Set position and resume if was playing
    _track_paused_position = position
    _track_paused = True
    
    if was_playing:
        resume_audio()


def skip_to_next_track() -> None:
    """Skip to next track in current playlist."""
    global _current_track_index
    
    if not _native_playing or _current_playlist_id == 0:
        return
    
    _native_stop()
    _current_track_index += 1
    
    playlist = _playlists.get(_current_playlist_id, [])
    if _current_track_index >= len(playlist):
        if _playlist_loops.get(_current_playlist_id, False):
            _current_track_index = 0
        else:
            _advance_to_next_playlist()
            return
    
    _save_track_position(_current_playlist_id, _current_track_index)
    _native_play_current_track()


def skip_to_next_playlist() -> None:
    """Skip to next playlist in queue."""
    if not _native_playing:
        return
    
    _native_stop()
    _advance_to_next_playlist()
