"""
Audio management for StudyCompanion add-on.
Handles background audio playback, looping, and volume control.
"""

import os
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl as QtCoreQUrl



_audio_player: QMediaPlayer | None = None
_audio_output: QAudioOutput | None = None

# Playlist support
_audio_playlist: list[str] = []
_audio_index: int = 0

# sections: list of dict {"pid": int, "start": int, "end": int, "loop": bool, "is_last": bool}
_audio_sections: list[dict] = []

SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}


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


def setup_audio_player(cfg: dict) -> None:
    """Setup audio player with looping and volume control."""
    global _audio_player, _audio_output
    global _audio_playlist, _audio_index, _audio_sections
    try:
        audio_volume = int(cfg.get("audio_volume", 50) or 50)

        # Single-playlist behavior:
        # - One playlist source (file or folder)
        # - Optional loop-all-day
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

        # Create player and audio output if not exists
        if _audio_player is None:
            _audio_player = QMediaPlayer()
            _audio_output = QAudioOutput()
            _audio_player.setAudioOutput(_audio_output)
            # Connect to end of media to loop
            try:
                from PyQt6.QtMultimedia import QMediaPlayer as _QMP

                def _section_for_index(i: int) -> tuple[int, dict | None]:
                    for si, s in enumerate(_audio_sections):
                        if s.get("start", 0) <= i <= s.get("end", -1):
                            return si, s
                    return -1, None

                def _set_and_play_index(next_index: int) -> None:
                    global _audio_index
                    if not _audio_player or not _audio_playlist:
                        return

                    # Skip missing/unreadable paths safely
                    tries = 0
                    i = next_index
                    while tries < len(_audio_playlist):
                        path = _audio_playlist[i]
                        if os.path.exists(path):
                            _audio_index = i
                            _audio_player.setSource(QtCoreQUrl.fromLocalFile(path))
                            _audio_player.play()
                            return
                        i = (i + 1) % len(_audio_playlist)
                        tries += 1

                    try:
                        _audio_player.stop()
                    except Exception:
                        pass

                def _on_status_change(status):
                    try:
                        if status == _QMP.MediaStatus.EndOfMedia and _audio_player:
                            if not _audio_playlist:
                                return

                            # Determine which section we're currently in
                            cur_index = _audio_index
                            sec_idx, sec = _section_for_index(cur_index)
                            if sec is None:
                                # fallback: simple advance
                                nxt = cur_index + 1
                                if nxt >= len(_audio_playlist):
                                    try:
                                        _audio_player.stop()
                                    except Exception:
                                        pass
                                    return
                                _set_and_play_index(nxt)
                                return

                            # If we're at the end of the current section
                            if cur_index >= int(sec.get("end", cur_index)):
                                # Loop this playlist indefinitely if enabled
                                if bool(sec.get("loop_forever", False)):
                                    _set_and_play_index(int(sec.get("start", 0)))
                                    return

                                # Otherwise continue into next section (or stop)
                                next_sec = None
                                if sec_idx >= 0 and sec_idx + 1 < len(_audio_sections):
                                    next_sec = _audio_sections[sec_idx + 1]
                                if next_sec is None:
                                    try:
                                        _audio_player.stop()
                                    except Exception:
                                        pass
                                    return
                                _set_and_play_index(int(next_sec.get("start", 0)))
                                return

                            # Within a section: advance by 1
                            _set_and_play_index(cur_index + 1)
                    except Exception:
                        pass
                _audio_player.mediaStatusChanged.connect(_on_status_change)
            except Exception:
                pass

        if _audio_playlist:
            # start at first existing track
            start_index = 0
            for i, p in enumerate(_audio_playlist):
                if os.path.exists(p):
                    start_index = i
                    break
            _audio_index = start_index
            _audio_player.setSource(QtCoreQUrl.fromLocalFile(_audio_playlist[_audio_index]))
            _audio_output.setVolume(max(0.0, min(1.0, audio_volume / 100.0)))
            _audio_player.play()
        else:
            if _audio_player:
                try:
                    _audio_player.stop()
                except Exception:
                    pass
    except Exception as e:
        print(f"[StudyCompanion] Error setting up audio player: {e}")


def stop_audio() -> None:
    """Stop the audio player."""
    global _audio_player
    try:
        if _audio_player:
            _audio_player.stop()
    except Exception as e:
        print(f"[StudyCompanion] Error stopping audio: {e}")
