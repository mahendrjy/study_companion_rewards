"""
StudyCompanion - An extensible Anki add-on for enhanced study sessions.

Features:
- Display random images during reviews
- Show motivational quotes
- Optional website embedding (desktop/mobile modes)
- Background audio playback with 3-playlist day-based rotation
- Playlist calendar widget
- Flexible configuration

Main entry point that registers hooks and initializes the add-on.
"""

from aqt import gui_hooks, mw

from .config_manager import get_config
from .image_manager import (
    delete_image_file,
    delete_external_cached_image,
    increment_click_count,
    sanitize_folder_name,
    get_media_subfolder_path,
)
from urllib.parse import unquote as urlunquote
from .image_manager import _load_meta, _save_meta
from .ui_manager import register_config_action, register_tools_menu
from .audio_manager import setup_audio_player, cleanup_audio_on_quit
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
        payload = message[len("randomImageDelete:"):]
        folder_part = ""
        filename_part = payload
        if "|" in payload:
            folder_part, filename_part = payload.split("|", 1)
        folder_part = urlunquote(str(folder_part or ""))
        filename_part = urlunquote(str(filename_part or ""))
        cfg = get_config()
        # Special: 'disk' means the file shown came from a system folder and was cached into media.
        if str(folder_part).strip().lower() == "disk":
            try:
                delete_external_cached_image(filename_part)
            except Exception:
                pass
        else:
            folder_override = None
            try:
                folder_override = sanitize_folder_name(folder_part) if folder_part.strip() else None
            except Exception:
                folder_override = None
            delete_image_file(filename_part, cfg, folder_name_override=folder_override)

        # Re-render the card without doing a full webview reload, staying on the same side.
        if hasattr(mw, "reviewer") and mw.reviewer:
            reviewer = mw.reviewer
            try:
                state = None
                try:
                    state = getattr(reviewer, "state", None)
                except Exception:
                    state = None
                if state is None:
                    try:
                        state = getattr(reviewer, "_state", None)
                    except Exception:
                        state = None

                state_s = str(state or "").lower()
                want_answer = state_s.startswith("answer") or state_s == "a"

                if hasattr(reviewer, "card") and reviewer.card:
                    if want_answer:
                        try:
                            reviewer._showAnswer()
                        except Exception:
                            try:
                                reviewer._showQuestion()
                            except Exception:
                                if hasattr(reviewer, "web") and reviewer.web:
                                    try:
                                        reviewer.web.eval("location.reload();")
                                    except Exception:
                                        pass
                    else:
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
        payload = message[len("randomImageClicked:"):]
        folder_part = ""
        filename_part = payload
        if "|" in payload:
            folder_part, filename_part = payload.split("|", 1)
        folder_part = urlunquote(str(folder_part or ""))
        filename_part = urlunquote(str(filename_part or ""))
        cfg = get_config()
        if str(folder_part).strip().lower() != "disk":
            folder_name = sanitize_folder_name(folder_part) if folder_part.strip() else sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))
            image_folder = get_media_subfolder_path(folder_name)
            if image_folder:
                try:
                    increment_click_count(image_folder, filename_part)
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

# Cleanup audio when Anki quits (CRITICAL: prevent orphaned processes)
gui_hooks.profile_will_close.append(cleanup_audio_on_quit)

# Inject images/quotes/website into card display
gui_hooks.card_will_show.append(inject_random_image)

# Queue answer-submit image popups
_install_answer_submit_hook()

# Handle delete image messages from JavaScript
gui_hooks.webview_did_receive_js_message.append(_handle_webview_message)

# Behavior/session hooks removed


# ============================================================================
# Override Browser to open card's actual deck (subdeck) instead of parent deck
# ============================================================================

def _on_browser_will_search(context) -> None:
    """Hook called when browser is about to search - modify search if from reviewer."""
    try:
        # Check if feature is enabled
        cfg = get_config()
        if not cfg.get("browser_open_card_deck", True):
            return
        
        # Only apply when reviewing
        if mw.state != "review" or not mw.reviewer or not mw.reviewer.card:
            return
        
        card = mw.reviewer.card
        
        # Get the actual deck name from card.did (this is the subdeck, not parent)
        deck_name = mw.col.decks.name(card.did)
        
        # Modify the search context to use our deck
        context.search = f'deck:"{deck_name}"'
    except Exception:
        pass


def _setup_browser_override():
    """Set up browser override after main window is ready."""
    try:
        # Hook into browser search - this is called when browser opens
        from aqt.browser import Browser
        
        # Store the original show method
        _original_show = Browser._setup_search
        
        def _patched_setup_search(browser_self, *args, **kwargs):
            """Intercept browser search setup to use card's deck."""
            result = _original_show(browser_self, *args, **kwargs)
            
            try:
                # Check if feature is enabled
                cfg = get_config()
                if not cfg.get("browser_open_card_deck", True):
                    return result
                
                # Only apply when reviewing
                if mw.state != "review" or not mw.reviewer or not mw.reviewer.card:
                    return result
                
                card = mw.reviewer.card
                
                # Get the actual deck name from card.did (this is the subdeck, not parent)
                deck_name = mw.col.decks.name(card.did)
                
                # Update the search
                browser_self.search_for(f'deck:"{deck_name}"')
            except Exception:
                pass
            
            return result
        
        Browser._setup_search = _patched_setup_search
    except Exception as e:
        print(f"[StudyCompanion] Failed to setup browser override: {e}")


# Override browser opening to use card's subdeck
def _custom_browse_for_card():
    """Open browser showing the current card's subdeck."""
    import aqt
    
    try:
        # Check if feature is enabled
        cfg = get_config()
        if not cfg.get("browser_open_card_deck", True):
            return False  # Let original handler run
        
        # Only apply when reviewing
        if mw.state != "review" or not mw.reviewer or not mw.reviewer.card:
            return False
        
        card = mw.reviewer.card
        
        # Get the actual deck name from card.did
        deck_name = mw.col.decks.name(card.did)
        
        # Open browser and search for the deck
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(f'deck:"{deck_name}"')
        return True  # Handled
    except Exception as e:
        print(f"[StudyCompanion] Error in custom browse: {e}")
        return False


def _patch_reviewer_shortcut():
    """Patch the reviewer to intercept 'b' key for custom browse."""
    try:
        from aqt.reviewer import Reviewer
        
        # Patch the _linkHandler which handles all shortcuts including 'b'
        _original_linkHandler = Reviewer._linkHandler
        
        def _patched_linkHandler(self, url):
            # 'ans' with browse triggers browser - intercept it
            if url == "ans" or url.startswith("ease"):
                return _original_linkHandler(self, url)
            
            # For other links, check original
            return _original_linkHandler(self, url)
        
        # Alternative: Patch _onBrowse directly on Reviewer if it exists
        if hasattr(Reviewer, 'onBrowse'):
            _orig_reviewer_browse = Reviewer.onBrowse
            def _new_reviewer_browse(self):
                if not _custom_browse_for_card():
                    return _orig_reviewer_browse(self)
            Reviewer.onBrowse = _new_reviewer_browse
            print("[StudyCompanion] Reviewer.onBrowse patched")
        
        print("[StudyCompanion] Browser shortcut override installed")
    except Exception as e:
        print(f"[StudyCompanion] Failed to patch reviewer shortcut: {e}")


def _patch_mw_onBrowse():
    """Patch browser opening at multiple levels."""
    try:
        import aqt
        from aqt import dialogs
        
        # Patch mw.onBrowse
        _original_onBrowse = mw.onBrowse
        
        def _patched_onBrowse():
            if _custom_browse_for_card():
                return  # Our handler opened the browser
            return _original_onBrowse()
        
        mw.onBrowse = _patched_onBrowse
        print("[StudyCompanion] mw.onBrowse patched")
        
        # Patch dialogs.open to intercept Browser opening
        _original_dialogs_open = dialogs.open
        
        def _patched_dialogs_open(name, *args, **kwargs):
            if name == "Browser":
                # Check if we're reviewing and should use custom search
                try:
                    cfg = get_config()
                    if cfg.get("browser_open_card_deck", True):
                        if mw.state == "review" and mw.reviewer and mw.reviewer.card:
                            card = mw.reviewer.card
                            deck_name = mw.col.decks.name(card.did)
                            # Open browser normally first
                            browser = _original_dialogs_open(name, *args, **kwargs)
                            # Then search for the deck
                            browser.search_for(f'deck:"{deck_name}"')
                            return browser
                except Exception as e:
                    print(f"[StudyCompanion] dialogs.open patch error: {e}")
            return _original_dialogs_open(name, *args, **kwargs)
        
        dialogs.open = _patched_dialogs_open
        print("[StudyCompanion] dialogs.open patched")
        
    except Exception as e:
        print(f"[StudyCompanion] Failed to patch onBrowse: {e}")


# Register to patch after main window init
gui_hooks.main_window_did_init.append(_patch_mw_onBrowse)

# Setup browser override
_setup_browser_override()
