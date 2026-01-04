"""
Audio management for StudyCompanion add-on.
Handles background audio playback, looping, and volume control.

IMPORTANT: Due to Qt's FFmpeg audio renderer crashing on Bluetooth disconnect,
this module uses macOS's native afplay command for audio playback instead of
QMediaPlayer. This avoids the crash entirely while providing reliable audio.
"""

import os
import sys
import subprocess
import threading

# Flag to control which audio backend to use
# Set to True to use native macOS audio (recommended), False for Qt audio
USE_NATIVE_AUDIO = True

# Safely import Qt multimedia - may not be available (only used if USE_NATIVE_AUDIO=False)
_AUDIO_AVAILABLE = False
QMediaPlayer = None
QAudioOutput = None
QtCoreQUrl = None
QTimer = None
QMediaDevices = None

if not USE_NATIVE_AUDIO:
    try:
        from PyQt6.QtMultimedia import QMediaPlayer as _QMP, QAudioOutput as _QAO
        from PyQt6.QtMultimedia import QMediaDevices as _QMD
        from PyQt6.QtCore import QUrl as _QUrl, QTimer as _QT
        QMediaPlayer = _QMP
        QAudioOutput = _QAO
        QtCoreQUrl = _QUrl
        QTimer = _QT
        QMediaDevices = _QMD
        _AUDIO_AVAILABLE = True
    except ImportError:
        pass
    except Exception:
        pass
else:
    # Native audio is always available on macOS
    _AUDIO_AVAILABLE = True


# Global state
_audio_player = None
_audio_output = None
_audio_volume: int = 50
_audio_playlist: list[str] = []
_audio_index: int = 0
_audio_sections: list[dict] = []
_audio_is_recovering: bool = False
_recovery_timer = None
_device_watcher = None
_last_device_id = None
_player_destroyed = False
_recreate_timer = None

# Native audio state (for macOS afplay)
_native_process = None
_native_thread = None
_native_playing = False
_native_loop = False

SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}


def _safe_call(func, *args, **kwargs):
    """Safely call a function, catching all exceptions."""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


# ============== Native macOS Audio Implementation ==============

def _native_play_track():
    """Play current track using macOS afplay command."""
    global _native_process, _native_playing
    
    if not _audio_playlist or _audio_index >= len(_audio_playlist):
        _native_playing = False
        return
    
    path = _audio_playlist[_audio_index]
    if not os.path.exists(path):
        _native_playing = False
        return
    
    try:
        # Calculate volume (afplay uses 0-1 scale, we use 0-100)
        vol = max(0.0, min(1.0, _audio_volume / 100.0))
        
        # Start afplay process
        _native_process = subprocess.Popen(
            ["afplay", "-v", str(vol), path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        _native_playing = True
        
        # Wait for completion in background
        def _wait_and_next():
            global _native_playing, _audio_index
            try:
                if _native_process:
                    _native_process.wait()
                
                if not _native_playing:
                    return  # Was stopped manually
                
                # Handle looping/next track
                cur_index = _audio_index
                sec = _get_section_for_index(cur_index)
                
                if sec is None:
                    # No section, just advance
                    nxt = cur_index + 1
                    if nxt >= len(_audio_playlist):
                        _native_playing = False
                        return
                    _audio_index = nxt
                    _native_play_track()
                    return
                
                # Check if at end of section
                if cur_index >= int(sec.get("end", cur_index)):
                    if bool(sec.get("loop_forever", False)):
                        _audio_index = int(sec.get("start", 0))
                        _native_play_track()
                        return
                    _native_playing = False
                    return
                
                # Not at end, advance to next track
                _audio_index = cur_index + 1
                _native_play_track()
                
            except Exception as e:
                print(f"[StudyCompanion] Native audio error: {e}")
                _native_playing = False
        
        thread = threading.Thread(target=_wait_and_next, daemon=True)
        thread.start()
        
    except Exception as e:
        print(f"[StudyCompanion] Failed to start native audio: {e}")
        _native_playing = False


def _native_stop():
    """Stop native audio playback."""
    global _native_process, _native_playing
    
    _native_playing = False
    if _native_process:
        try:
            _native_process.terminate()
            _native_process = None
        except Exception:
            pass


def _get_section_for_index(i: int) -> dict | None:
    """Get the section containing the given index."""
    for s in _audio_sections:
        if s.get("start", 0) <= i <= s.get("end", -1):
            return s
    return None


# ============== Qt Audio Implementation (fallback) ==============


def _destroy_player():
    """Completely destroy the audio player and output to prevent crashes."""
    global _audio_player, _audio_output, _player_destroyed
    
    _player_destroyed = True
    
    if _audio_player is not None:
        try:
            _audio_player.stop()
        except Exception:
            pass
        try:
            _audio_player.setSource(QtCoreQUrl())  # Clear source
        except Exception:
            pass
        try:
            _audio_player.setAudioOutput(None)
        except Exception:
            pass
        try:
            _audio_player.deleteLater()
        except Exception:
            pass
        _audio_player = None
    
    if _audio_output is not None:
        try:
            _audio_output.deleteLater()
        except Exception:
            pass
        _audio_output = None


def _recreate_player():
    """Recreate the audio player after destruction."""
    global _audio_player, _audio_output, _audio_is_recovering, _player_destroyed
    
    try:
        # Create fresh player and output
        _audio_player = QMediaPlayer()
        _audio_output = QAudioOutput()
        _audio_output.setVolume(max(0.0, min(1.0, _audio_volume / 100.0)))
        _audio_player.setAudioOutput(_audio_output)
        
        # Reconnect signals
        _connect_player_signals()
        
        _player_destroyed = False
        
        # Resume playback if we have a playlist
        if _audio_playlist and 0 <= _audio_index < len(_audio_playlist):
            path = _audio_playlist[_audio_index]
            if os.path.exists(path):
                _audio_player.setSource(QtCoreQUrl.fromLocalFile(path))
                _audio_player.play()
        
        print("[StudyCompanion] Audio recovered successfully")
    except Exception as e:
        print(f"[StudyCompanion] Audio recovery failed: {e}")
    finally:
        _audio_is_recovering = False


def _try_recover_audio():
    """Try to recover audio after device change."""
    global _audio_is_recovering, _recreate_timer
    
    if not _AUDIO_AVAILABLE or _audio_is_recovering:
        return
    
    _audio_is_recovering = True
    
    try:
        # Destroy any existing player first
        _destroy_player()
        
        # Use timer to delay recreation
        if _recreate_timer is None:
            _recreate_timer = QTimer()
            _recreate_timer.setSingleShot(True)
            _recreate_timer.timeout.connect(_recreate_player)
        
        _recreate_timer.start(300)  # 300ms delay before recreating
        
    except Exception as e:
        print(f"[StudyCompanion] Audio recovery error: {e}")
        _audio_is_recovering = False


def _schedule_recovery():
    """Schedule audio recovery with a delay."""
    global _recovery_timer
    
    if not _AUDIO_AVAILABLE:
        return
    
    try:
        # Immediately destroy player to prevent crash
        _destroy_player()
        
        # Use QTimer to delay recovery
        if _recovery_timer is None:
            _recovery_timer = QTimer()
            _recovery_timer.setSingleShot(True)
            _recovery_timer.timeout.connect(_try_recover_audio)
        
        # Start/restart timer with 500ms delay
        _recovery_timer.start(500)
    except Exception:
        pass


def _on_audio_device_changed():
    """Called when audio output device changes (Bluetooth connect/disconnect)."""
    global _last_device_id
    
    try:
        if QMediaDevices is None:
            return
        
        new_device = QMediaDevices.defaultAudioOutput()
        new_id = new_device.id() if new_device and not new_device.isNull() else None
        
        # Check if device actually changed
        if new_id != _last_device_id:
            print(f"[StudyCompanion] Audio device changed, scheduling recovery...")
            _last_device_id = new_id
            _schedule_recovery()
    except Exception as e:
        print(f"[StudyCompanion] Device change detection error: {e}")
        _schedule_recovery()


def _setup_device_watcher():
    """Set up audio device change monitoring."""
    global _device_watcher, _last_device_id
    
    if not _AUDIO_AVAILABLE or QMediaDevices is None:
        return
    
    try:
        # Store current device ID
        current_device = QMediaDevices.defaultAudioOutput()
        _last_device_id = current_device.id() if current_device and not current_device.isNull() else None
        
        # Connect to device change signal
        _device_watcher = QMediaDevices()
        _device_watcher.audioOutputsChanged.connect(_on_audio_device_changed)
        print("[StudyCompanion] Audio device monitoring enabled")
    except Exception as e:
        print(f"[StudyCompanion] Failed to setup device watcher: {e}")


def _natural_key(text: str):
    import re

    parts = re.split(r"(\d+)", text)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


def _folder_audio_files(folder: str) -> list[str]:
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


def _expand_source(path: str) -> list[str]:
    p = str(path or "").strip()
    if not p:
        return []
    if os.path.isdir(p):
        return _folder_audio_files(p)
    if os.path.isfile(p) and os.path.splitext(p)[1].lower() in SUPPORTED_AUDIO_EXTS:
        return [p]
    return []


def _playlist_items(cfg: dict, pid: int) -> list[str]:
    # New source path (file or folder)
    items = _expand_source(cfg.get(f"audio_playlist_{pid}_path", ""))
    if items:
        return items

    # Backwards compat: explicit list of files
    raw_list = cfg.get(f"audio_playlist_{pid}", []) or []
    if isinstance(raw_list, list):
        out = []
        for x in raw_list:
            s = str(x or "").strip()
            if s and os.path.isfile(s):
                out.append(s)
        if out:
            return out

    # Backwards compat: single-file key / legacy playlist
    if pid == 1:
        legacy_list = cfg.get("audio_playlist", []) or []
        if isinstance(legacy_list, list):
            out = []
            for x in legacy_list:
                s = str(x or "").strip()
                if s and os.path.isfile(s):
                    out.append(s)
            if out:
                return out

        legacy_file = str(cfg.get("audio_file_path", "") or "").strip()
        if legacy_file and os.path.isfile(legacy_file):
            return [legacy_file]

    return []


def _loop_forever(cfg: dict) -> bool:
    # Backwards compat: previous per-playlist checkbox.
    if "audio_loop_1" in cfg:
        return bool(cfg.get("audio_loop_1", False))
    return bool(cfg.get("audio_loop_playlist", False))


# Store signal handlers so they can be reconnected after recovery
_status_handler = None
_error_handler = None


def _connect_player_signals():
    """Connect signals to the audio player. Used both in setup and recovery."""
    global _status_handler, _error_handler
    
    if not _audio_player:
        return
    
    try:
        if _status_handler:
            _audio_player.mediaStatusChanged.connect(_status_handler)
        if _error_handler:
            _audio_player.errorOccurred.connect(_error_handler)
    except Exception as e:
        print(f"[StudyCompanion] Error connecting audio signals: {e}")


def setup_audio_player(cfg: dict) -> None:
    """Setup audio player with looping and volume control."""
    global _audio_player, _audio_output, _audio_volume
    global _audio_playlist, _audio_index, _audio_sections
    global _status_handler, _error_handler
    
    if not _AUDIO_AVAILABLE:
        print("[StudyCompanion] Audio not available")
        return
    
    try:
        _audio_volume = int(cfg.get("audio_volume", 50) or 50)
        audio_volume = _audio_volume

        # Single-playlist behavior
        items = _playlist_items(cfg, 1)
        _audio_playlist = items
        if items:
            _audio_sections = [
                {
                    "pid": 1,
                    "start": 0,
                    "end": len(items) - 1,
                    "loop_forever": bool(_loop_forever(cfg)),
                }
            ]
        else:
            _audio_sections = []

        # Use native macOS audio if enabled (default)
        if USE_NATIVE_AUDIO:
            print("[StudyCompanion] Using native macOS audio (crash-safe)")
            if _audio_playlist:
                _audio_index = 0
                _native_play_track()
            return

        # Fallback: Qt audio (may crash on Bluetooth disconnect)
        print("[StudyCompanion] Using Qt audio (fallback)")
        
        # Set up device watcher for Bluetooth connect/disconnect
        _setup_device_watcher()

        # Create player and audio output if not exists
        if _audio_player is None:
            try:
                _audio_player = QMediaPlayer()
                _audio_output = QAudioOutput()
                _audio_player.setAudioOutput(_audio_output)
            except Exception as e:
                print(f"[StudyCompanion] Failed to create audio player: {e}")
                _audio_player = None
                _audio_output = None
                return
            
            # Connect to end of media to loop
            try:
                def _section_for_index(i: int) -> tuple[int, dict | None]:
                    for si, s in enumerate(_audio_sections):
                        if s.get("start", 0) <= i <= s.get("end", -1):
                            return si, s
                    return -1, None

                def _set_and_play_index(next_index: int) -> None:
                    global _audio_index
                    if not _audio_player or not _audio_playlist:
                        return

                    tries = 0
                    i = next_index
                    while tries < len(_audio_playlist):
                        path = _audio_playlist[i]
                        if os.path.exists(path):
                            _audio_index = i
                            try:
                                _audio_player.setSource(QtCoreQUrl.fromLocalFile(path))
                                _audio_player.play()
                            except Exception:
                                _schedule_recovery()
                            return
                        i = (i + 1) % len(_audio_playlist)
                        tries += 1
                    _safe_call(_audio_player.stop)

                def _on_status_change(status):
                    try:
                        if status == QMediaPlayer.MediaStatus.EndOfMedia and _audio_player:
                            if not _audio_playlist:
                                return

                            cur_index = _audio_index
                            sec_idx, sec = _section_for_index(cur_index)
                            if sec is None:
                                nxt = cur_index + 1
                                if nxt >= len(_audio_playlist):
                                    _safe_call(_audio_player.stop)
                                    return
                                _set_and_play_index(nxt)
                                return

                            if cur_index >= int(sec.get("end", cur_index)):
                                if bool(sec.get("loop_forever", False)):
                                    _set_and_play_index(int(sec.get("start", 0)))
                                    return
                                next_sec = None
                                if sec_idx >= 0 and sec_idx + 1 < len(_audio_sections):
                                    next_sec = _audio_sections[sec_idx + 1]
                                if next_sec is None:
                                    _safe_call(_audio_player.stop)
                                    return
                                _set_and_play_index(int(next_sec.get("start", 0)))
                                return
                            _set_and_play_index(cur_index + 1)
                    except Exception:
                        pass
                
                def _on_error(error, error_string=""):
                    """Handle audio errors - schedule recovery instead of crashing."""
                    print(f"[StudyCompanion] Audio error: {error} - {error_string}")
                    _schedule_recovery()
                
                # Store handlers for reconnection after recovery
                _status_handler = _on_status_change
                _error_handler = _on_error
                
                _audio_player.mediaStatusChanged.connect(_on_status_change)
                _audio_player.errorOccurred.connect(_on_error)
            except Exception as e:
                print(f"[StudyCompanion] Error connecting audio signals: {e}")

        if _audio_playlist and _audio_player:
            start_index = 0
            for i, p in enumerate(_audio_playlist):
                if os.path.exists(p):
                    start_index = i
                    break
            _audio_index = start_index
            try:
                _audio_player.setSource(QtCoreQUrl.fromLocalFile(_audio_playlist[_audio_index]))
                if _audio_output:
                    _audio_output.setVolume(max(0.0, min(1.0, audio_volume / 100.0)))
                _audio_player.play()
            except Exception as e:
                print(f"[StudyCompanion] Error starting audio playback: {e}")
        else:
            _safe_call(lambda: _audio_player.stop() if _audio_player else None)
    except Exception as e:
        print(f"[StudyCompanion] Error setting up audio player: {e}")


def stop_audio() -> None:
    """Stop the audio player."""
    global _audio_player
    if not _AUDIO_AVAILABLE:
        return
    
    # Stop native audio if using it
    if USE_NATIVE_AUDIO:
        _native_stop()
        return
    
    # Stop Qt audio
    _safe_call(lambda: _audio_player.stop() if _audio_player else None)
