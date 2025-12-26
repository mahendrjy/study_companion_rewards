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
        # Two playlists (file or folder source)
        "audio_playlist_1": [],
        "audio_playlist_2": [],
        "audio_playlist_1_path": "",
        "audio_playlist_2_path": "",
        "audio_loop_1": False,
        "audio_loop_2": False,

        # Program schedule (more customizable play/rest + active/break + pattern)
        # When enabled, the add-on uses the cycle counters to track calendar days in the program.
        "audio_program_enabled": False,
        "audio_program_active_days": 21,
        "audio_program_break_days": 5,

        # 21-day + 5-day break cycle tracking (optional)
        "audio_cycle_enabled": False,
        "audio_cycle_day": 1,
        "audio_cycle_count": 0,
        "audio_cycle_last_date": "",
        "audio_last_played_date": "",
        "audio_volume": 50,
        # Orientation-aware single-image display
        "auto_orient_single_image": True,
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
