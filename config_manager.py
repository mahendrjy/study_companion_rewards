"""
Configuration management for StudyCompanion add-on.
Handles config loading, validation, and persistence.
"""

import os
import json
from aqt import mw


def get_defaults() -> dict:
    """Return default configuration values."""
    return {
        "enabled": True,
        "show_on_question": True,
        "show_on_answer": True,
        "folder_name": "study_companion_images",
        # Question/Answer image sources.
        # These may be absolute system folders OR collection.media subfolder names.
        # If empty, the add-on falls back to folder_name inside collection.media.
        "question_image_folder": "",
        "answer_image_folder": "",
        # Legacy per-side media-only keys (kept for backward compatibility; not shown in UI)
        "folder_name_question": "",
        "folder_name_answer": "",
        "max_width_percent": 80,
        "max_height_vh": 60,
        "max_height_unit": "vh",
        # Whether to use custom width and/or height values from settings
        "use_custom_width": False,
        "use_custom_height": False,
        "click_open_fullscreen": True,
        # Image appearance
        "images_max_columns": 3,
        "images_grid_gap_px": 8,
        "image_corner_radius_px": 8,
        "avoid_repeat": True,
        "show_motivation_quotes": True,
        "images_to_show": 1,
        # Website embed (optional)
        "website_url": "",
        "website_height_vh": 80,
        "website_display_mode": "mobile",  # "desktop" or "mobile"
        "website_width_percent": 100,  # width for mobile mode
        "website_border_radius_px": 4,
        # Quote appearance
        "quotes_font_size_em": 0.9,
        "quotes_italic": True,
        "quotes_align": "left",  # left|center
        # Background audio (optional)
        "audio_file_path": "",
        "audio_playlist": [],
        "audio_loop_playlist": False,
        "audio_volume": 50,
        
        # Multi-playlist system (3 playlists with day-based rotation)
        # Playlist 1: plays every day (loops forever)
        # Playlist 2: plays on odd days 1,5,9,13,17,21,25,29 (no loop)
        # Playlist 3: plays on odd days 3,7,11,15,19,23,27 (no loop)
        # Even days: only Playlist 1
        "audio_playlist_1_path": "",
        "audio_playlist_2_path": "",
        "audio_playlist_3_path": "",
        "audio_loop_1": True,  # Playlist 1 loops forever (default)
        "audio_loop_2": False,  # Playlist 2 does not loop
        "audio_loop_3": False,  # Playlist 3 does not loop
        "audio_playlist_1_enabled": True,
        "audio_playlist_2_enabled": True,
        "audio_playlist_3_enabled": True,
        # Track position for resume (index within each playlist)
        "audio_track_position_1": 0,
        "audio_track_position_2": 0,
        "audio_track_position_3": 0,
        # Manual override (persistent until changed)
        "audio_playlist_override_enabled": False,
        "audio_playlist_override_day": 1,  # 1-31
        # Show notifications when playlist changes
        "audio_show_notifications": True,
        # 21-day study cycle with 5-day break
        # Format: "YYYY-MM-DD" or empty string
        "audio_cycle_start_date": "",
        "audio_cycle_study_days": 21,  # Days of study in each cycle
        "audio_cycle_break_days": 5,   # Days of break after study
        # Orientation-aware single-image display
        "auto_orient_single_image": True,

        # Answer-submit reaction image popup
        "answer_image_enabled": False,
        "answer_image_angry_folder": "",
        "answer_image_happy_folder": "",
        "answer_image_duration_seconds": 3,
        # Popup sizing: defaults to auto (based on image dimensions)
        "answer_image_popup_use_custom_width": False,
        "answer_image_popup_max_width_percent": 70,
        "answer_image_popup_use_custom_height": False,
        "answer_image_popup_max_height_vh": 60,
        "answer_image_popup_max_height_unit": "vh",
        # Legacy (no longer shown in UI)
        "answer_image_popup_max_width_px": 420,
        "answer_image_popup_max_height_px": 420,
    }


def get_config() -> dict:
    """Load config.json; fall back to defaults on failure."""
    default = get_defaults()
    try:
        cfg = mw.addonManager.getConfig(__name__.split(".")[0])
        if not isinstance(cfg, dict):
            return default
        # Backwards-compat: map old keys if present
        if "show_motivation_quotes" not in cfg and "show_filename" in cfg:
            try:
                cfg["show_motivation_quotes"] = bool(cfg.get("show_filename"))
            except Exception:
                cfg["show_motivation_quotes"] = True

        # Backwards-compat: if new Question/Answer keys are unset but old per-side keys exist,
        # reuse those values.
        try:
            if not str(cfg.get("question_image_folder", "") or "").strip():
                old_q = str(cfg.get("folder_name_question", "") or "").strip()
                if old_q:
                    cfg["question_image_folder"] = old_q
            if not str(cfg.get("answer_image_folder", "") or "").strip():
                old_a = str(cfg.get("folder_name_answer", "") or "").strip()
                if old_a:
                    cfg["answer_image_folder"] = old_a
        except Exception:
            pass
        return {**default, **cfg}
    except Exception as e:
        print(f"[StudyCompanion] Failed to load config: {e}")
        return default


def write_config(new_cfg: dict) -> None:
    """Save config while keeping unknown keys untouched."""
    try:
        addon_name = __name__.split(".")[0]
        old = mw.addonManager.getConfig(addon_name)
        if not isinstance(old, dict):
            old = {}
        merged = {**old, **new_cfg}
        mw.addonManager.writeConfig(addon_name, merged)
    except Exception as e:
        print(f"[StudyCompanion] Failed to write config: {e}")
