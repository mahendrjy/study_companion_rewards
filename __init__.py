"""
StudyCompanion - An extensible Anki add-on for enhanced study sessions.

Features:
- Display random images during reviews
- Show motivational quotes
- Optional website embedding (desktop/mobile modes)
- Background audio playback
- Flexible configuration

Main entry point that registers hooks and initializes the add-on.
"""

from aqt import gui_hooks, mw

from .config_manager import get_config
from .image_manager import (
    delete_image_file,
    increment_click_count,
    sanitize_folder_name,
    get_media_subfolder_path,
)
from urllib.parse import unquote as urlunquote
from .image_manager import _load_meta, _save_meta
from .ui_manager import register_config_action, register_tools_menu
from .audio_manager import setup_audio_player
from .features import inject_random_image, trigger_answer_submit_popup


def _handle_webview_message(handled, message, context):
    """Handle delete image command from JavaScript."""
    if isinstance(message, str) and message.startswith("scOpenImage:"):
        rel = message[len("scOpenImage:") :]
        try:
            col = getattr(mw, "col", None)
            if not col:
                return (True, None)
            media_dir = col.media.dir()
            rel_decoded = urlunquote(str(rel))
            rel_decoded = rel_decoded.lstrip("/\\")
            import os

            full_path = os.path.join(media_dir, rel_decoded)
            from .answer_popup import show_fullscreen_image

            show_fullscreen_image(full_path)
        except Exception:
            pass
        return (True, None)

    if isinstance(message, str) and message.startswith("randomImageDelete:"):
        filename = message[len("randomImageDelete:"):]
        cfg = get_config()
        if delete_image_file(filename, cfg):
            # Re-render the card without doing a full webview reload
            if hasattr(mw, "reviewer") and mw.reviewer:
                reviewer = mw.reviewer
                try:
                    if hasattr(reviewer, "card") and reviewer.card:
                        try:
                            reviewer._showQuestion()
                        except Exception:
                            try:
                                reviewer._showAnswer()
                            except Exception:
                                if hasattr(reviewer, "web") and reviewer.web:
                                    try:
                                        reviewer.web.eval("location.reload();")
                                    except Exception:
                                        pass
                    else:
                        if hasattr(reviewer, "web") and reviewer.web:
                            try:
                                reviewer.web.eval("location.reload();")
                            except Exception:
                                pass
                except Exception:
                    pass
        return (True, None)
    # favorite/blacklist features removed
    if isinstance(message, str) and message.startswith("randomImageClicked:"):
        filename = message[len("randomImageClicked:"):]
        cfg = get_config()
        folder_name = sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))
        image_folder = get_media_subfolder_path(folder_name)
        if image_folder:
            try:
                increment_click_count(image_folder, filename)
            except Exception:
                pass
        return (True, None)
    # video feature removed
    return handled


def _on_main_window_init():
    """Initialize StudyCompanion when main window is ready."""
    # Register config action
    register_config_action()
    
    # Add menu item to Tools menu
    register_tools_menu()

    # Setup background audio on startup
    try:
        setup_audio_player(get_config())
    except Exception as e:
        print(f"[StudyCompanion] Failed to setup audio: {e}")


def _on_reviewer_did_answer_card(reviewer, card, ease) -> None:
    """Queue a reaction image popup after the user answers a card."""
    try:
        trigger_answer_submit_popup(int(ease), get_config())
    except Exception:
        pass


def _install_answer_submit_hook() -> None:
    """Install a hook compatible with multiple Anki versions."""
    # Preferred hook (recent Anki)
    try:
        h = getattr(gui_hooks, "reviewer_did_answer_card", None)
        if h is not None:
            h.append(_on_reviewer_did_answer_card)
            return
    except Exception:
        pass

    # Fallback: wrap Reviewer._answerCard
    try:
        from aqt.reviewer import Reviewer

        old = getattr(Reviewer, "_answerCard", None)
        if old is None:
            return

        def _wrapped_answer(self, ease):
            try:
                trigger_answer_submit_popup(int(ease), get_config())
            except Exception:
                pass
            return old(self, ease)

        Reviewer._answerCard = _wrapped_answer
    except Exception as e:
        print(f"[StudyCompanion] Failed to install answer hook: {e}")


# ============================================================================
# Register Hooks
# ============================================================================

# Initialize when main window is ready
gui_hooks.main_window_did_init.append(_on_main_window_init)

# Inject images/quotes/website into card display
gui_hooks.card_will_show.append(inject_random_image)

# Queue answer-submit image popups
_install_answer_submit_hook()

# Handle delete image messages from JavaScript
gui_hooks.webview_did_receive_js_message.append(_handle_webview_message)

# Behavior/session hooks removed
