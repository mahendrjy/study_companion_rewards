"""
Core features for StudyCompanion add-on.
Implements card rendering with images, quotes, and website embedding.
"""

import html
import os
import shutil
import hashlib
import random
from urllib.parse import quote as urlquote
from typing import Dict

from aqt import mw

from .config_manager import get_config
from .image_manager import (
    pick_random_image_filenames,
    sanitize_folder_name,
    ensure_optimized_copy,
    get_prioritized_files,
    increment_click_count,
    increment_view_count,
    copy_external_image_into_media,
    list_external_cached_media_files,
)
from .image_manager import get_media_subfolder_path, _load_meta, _save_meta
from .quotes import get_random_quote, get_unique_random_quotes


_VALID_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg")
_ANSWER_POPUP_MEDIA_FOLDER = "study_companion_answer_popup"


def _list_disk_images(folder_path: str) -> list[str]:
    try:
        files: list[str] = []
        for root, _dirs, names in os.walk(folder_path):
            for n in names:
                if n.lower().endswith(_VALID_IMG_EXT):
                    files.append(os.path.join(root, n))
        return files
    except Exception:
        return []


def _pick_from_disk_folder(folder_path: str, count: int) -> list[str]:
    files = _list_disk_images(folder_path)
    if not files:
        return []
    if count <= 1:
        return [random.choice(files)]
    if count >= len(files):
        random.shuffle(files)
        return files[:count]
    return random.sample(files, count)


def _resolve_side_source(cfg: dict, side: str) -> tuple[str, str]:
    """Return (source_type, value). source_type: 'disk' or 'media'."""
    side_l = str(side or "").lower()
    key = "question_image_folder" if side_l.startswith("q") else "answer_image_folder"
    other_key = "answer_image_folder" if side_l.startswith("q") else "question_image_folder"
    raw = str(cfg.get(key, "") or "").strip()
    if not raw:
        # If one side isn't configured, reuse the other side.
        raw = str(cfg.get(other_key, "") or "").strip()
    if raw:
        disk_folder = _resolve_existing_folder(raw)
        if disk_folder:
            return "disk", disk_folder
        # otherwise treat it as a media subfolder name
        return "media", sanitize_folder_name(raw)

    # Fallback: legacy per-side media-only keys
    legacy_key = "folder_name_question" if side_l.startswith("q") else "folder_name_answer"
    legacy = str(cfg.get(legacy_key, "") or "").strip()
    if legacy:
        return "media", sanitize_folder_name(legacy)

    # Final fallback: the legacy single media folder
    return "media", sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))


def trigger_answer_submit_popup(ease: int, cfg: dict | None = None) -> None:
    """Show a centered Qt popup immediately after answering a card."""
    try:
        if cfg is None:
            cfg = get_config()
        if not bool(cfg.get("enabled", True)):
            return
        if not bool(cfg.get("answer_image_enabled", False)):
            return

        ease_i = int(ease)
        if ease_i in (1, 2):
            folder = str(cfg.get("answer_image_angry_folder", "") or "").strip()
        elif ease_i in (3, 4):
            folder = str(cfg.get("answer_image_happy_folder", "") or "").strip()
        else:
            return

        # If the user didn't set angry/happy folders, reuse the Answer-side source.
        if not folder:
            src_type, src_val = _resolve_side_source(cfg, "answer")
            folder = src_val if src_type == "disk" else sanitize_folder_name(src_val)

        duration_s = int(cfg.get("answer_image_duration_seconds", 3) or 3)
        if duration_s < 1:
            duration_s = 1
        if duration_s > 30:
            duration_s = 30

        image_path = _pick_answer_popup_image_file(folder, cfg)
        if not image_path:
            return

        # Quote + delete button in the Qt popup
        quote_text = ""
        try:
            quote_text = get_random_quote() or ""
        except Exception:
            quote_text = ""

        # Show Qt popup (centered, click-to-zoom)
        from .answer_popup import show_answer_popup_with_quote

        show_answer_popup_with_quote(image_path, int(duration_s * 1000), cfg, quote_text=quote_text, delete_path=image_path)
    except Exception:
        return


def _pick_answer_popup_image_file(folder: str, cfg: dict) -> str | None:
    """Pick an image file path from either an absolute folder or a media subfolder."""
    disk_folder = _resolve_existing_folder(folder)
    if disk_folder:
        return _pick_random_image_path_from_folder(disk_folder)

    folder_media = sanitize_folder_name(folder)
    image_folder_path = get_media_subfolder_path(folder_media)
    if not image_folder_path:
        return None

    # Reuse existing picker by temporarily overriding folder_name
    cfg2 = dict(cfg)
    cfg2["folder_name"] = folder_media
    filenames = pick_random_image_filenames(cfg2, 1)
    if not filenames:
        return None

    fname = filenames[0]
    full = os.path.join(image_folder_path, fname)
    return full if os.path.exists(full) else None


_current_card_id: int | None = None
_website_iframe_injected: bool = False

# Answer-submit popup state (queued on answer, injected on next question render)
_pending_answer_popup: dict | None = None

# (Behavior/emotion/session features removed)


def inject_random_image(text: str, card, kind: str) -> str:
    """
    Hook for card_will_show.
    Injects images, quotes, and website into card display.
    kind: "reviewQuestion", "reviewAnswer", etc.
    """
    global _current_card_id, _website_iframe_injected
    
    cfg = get_config()

    # behavior/emotion/session features removed

    if not cfg.get("enabled", True):
        return text

    # If the user disabled regular question-side injection, still allow the
    # answer-submit popup to render on the next question.
    if kind.endswith("Question") and not cfg.get("show_on_question", True):
        popup_only = _build_answer_submit_popup_html(kind)
        return text + popup_only if popup_only else text

    if kind.endswith("Answer") and not cfg.get("show_on_answer", True):
        return text

    card_id = card.id if card else None
    is_new_card = (card_id != _current_card_id)
    if is_new_card:
        _current_card_id = card_id

    # Prepare website settings early so it can be used even when images list is empty
    website_url = str(cfg.get("website_url", "")).strip()
    website_display_mode = str(cfg.get("website_display_mode", "mobile")).lower()

    images_count = int(cfg.get("images_to_show", 1) or 1)

    kind_s = str(kind or "")
    if kind_s.endswith("Question"):
        side = "question"
    elif kind_s.endswith("Answer"):
        side = "answer"
    else:
        side = "question"

    def _pick_for(side_name: str) -> tuple[str, str, str, list[str], str]:
        st, sv = _resolve_side_source(cfg, side_name)
        if st == "disk":
            tag = "q" if str(side_name).lower().startswith("q") else "a"
            # Cache-first: prefer already cached external files for this side.
            cached = list_external_cached_media_files(tag=tag)
            if cached:
                if images_count <= 1:
                    files = [random.choice(cached)]
                else:
                    if images_count >= len(cached):
                        random.shuffle(cached)
                        files = cached[:images_count]
                    else:
                        files = random.sample(cached, images_count)
                return "disk", sv, "disk", files, tag

            # No cache yet: read from the system folder and copy into media now,
            # then render using the cached media filenames.
            picked_paths = _pick_from_disk_folder(sv, images_count)
            cached_names: list[str] = []
            for p in picked_paths:
                try:
                    rel = copy_external_image_into_media(p, tag=tag)
                    if rel:
                        cached_names.append(rel)
                except Exception:
                    pass
            return "disk", sv, "disk", cached_names, tag

        folder = sanitize_folder_name(sv)
        cfg_side = dict(cfg)
        cfg_side["folder_name"] = folder
        files = pick_random_image_filenames(cfg_side, images_count) or []
        return st, sv, folder, files, ""

    src_type, src_val, folder_name, filenames, disk_tag = _pick_for(side)

    # If empty, try the other side as a fallback (common when only one folder is configured)
    if not filenames:
        other_side = "answer" if side == "question" else "question"
        src_type, src_val, folder_name, filenames, disk_tag = _pick_for(other_side)

    # Final fallback: legacy shared media folder
    if not filenames:
        try:
            folder_name = sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))
            cfg_side = dict(cfg)
            cfg_side["folder_name"] = folder_name
            src_type = "media"
            src_val = folder_name
            filenames = pick_random_image_filenames(cfg_side, images_count) or []
        except Exception:
            filenames = []

    # behavior/emotion features removed

    # folder_name already resolved above based on card side

    max_w = cfg.get("max_width_percent", 80)
    max_h_value = cfg.get("max_height_vh", 60)
    max_h_unit = str(cfg.get("max_height_unit", "vh")).lower()

    website_url = str(cfg.get("website_url", "")).strip()
    website_display_mode = str(cfg.get("website_display_mode", "mobile")).lower()
    show_quotes = cfg.get("show_motivation_quotes", True)

    max_columns = int(cfg.get("images_max_columns", 3) or 3)
    if max_columns < 1:
        max_columns = 1
    if max_columns > 6:
        max_columns = 6

    gap_px = int(cfg.get("images_grid_gap_px", 8) or 8)
    if gap_px < 0:
        gap_px = 0
    if gap_px > 48:
        gap_px = 48

    radius_px = int(cfg.get("image_corner_radius_px", 8) or 8)
    if radius_px < 0:
        radius_px = 0
    if radius_px > 48:
        radius_px = 48
    
    total_items_needing_quotes = images_count
    if website_url and website_display_mode == "mobile":
        total_items_needing_quotes += 1
    
    unique_quotes = get_unique_random_quotes(total_items_needing_quotes) if show_quotes else []
    quote_index = 0

    images_cells = []
    columns = min(max_columns, max(1, images_count))
    cell_width_css = f"calc({100/columns:.4f}% - 12px)"
    
    # increment view counts for selected filenames (media only)
    image_folder_path = ""
    if src_type != "disk":
        try:
            image_folder_path = get_media_subfolder_path(folder_name) or ""
            if image_folder_path:
                for fn in filenames:
                    try:
                        increment_view_count(image_folder_path, fn)
                    except Exception:
                        pass
        except Exception:
            image_folder_path = ""

    for idx, fname in enumerate(filenames):
        # Insert website in mobile mode after first image
        if website_url and website_display_mode == "mobile" and idx == 0:
            website_cell = _create_website_cell(cfg, quote_index, unique_quotes if show_quotes else [])
            if website_cell:
                images_cells.append(website_cell)
                quote_index += 1

        if src_type == "disk":
            # Disk sources are rendered via cached media filenames.
            rel_media = str(fname)
            if not rel_media:
                continue
            title_attr_i = html.escape(rel_media, quote=True)
            img_src_i = urlquote(rel_media, safe='/')
            data_folder = "disk"
            data_fname_raw = rel_media
            filename_escaped_i = html.escape(rel_media, quote=True)
            folder_attr = "disk"
        else:
            # prefer optimized cached copy if available
            rel_src = fname
            try:
                if image_folder_path:
                    rel_src = ensure_optimized_copy(image_folder_path, fname) or fname
            except Exception:
                rel_src = fname

            img_src_i = f"{folder_name}/{urlquote(rel_src, safe='/')}"
            title_attr_i = html.escape(fname, quote=True)
            data_folder = folder_name
            data_fname_raw = fname
            filename_escaped_i = html.escape(fname, quote=True)
            folder_attr = html.escape(folder_name, quote=True)

        # Image styling
        use_custom_w = bool(cfg.get("use_custom_width", False))
        use_custom_h = bool(cfg.get("use_custom_height", False))
        img_style_parts = []
        if images_count == 1:
            # Single-image display: prefer contain + max constraints to avoid cropping
            # Respect separate custom width/height flags
            if use_custom_w:
                if isinstance(max_w, (int, float)) and max_w > 0:
                    img_style_parts.append(f"max-width:{int(max_w)}%")
                else:
                    img_style_parts.append("max-width:100%")
            else:
                img_style_parts.append("max-width:95%")

            if use_custom_h:
                if isinstance(max_h_value, (int, float)) and max_h_value > 0:
                    unit = "vh" if max_h_unit == "vh" else "%"
                    img_style_parts.append(f"max-height:{int(max_h_value)}{unit}")
                else:
                    img_style_parts.append("max-height:100%")
            else:
                img_style_parts.append("max-height:90vh")

            img_style_parts.append("width:auto")
            img_style_parts.append("height:auto")
            img_style_parts.append("object-fit:contain")
        else:
            # Multi-image grid: fill width and crop with cover for consistent thumbnails
            img_style_parts.append("width:100%")
            img_style_parts.append((f"height:{max_h_value}vh" if max_h_unit == "vh" else f"height:{max_h_value}%") if isinstance(max_h_value, (int, float)) and max_h_value > 0 else "height:auto")
            img_style_parts.append("object-fit:cover")

        img_style_parts.append("object-position:center")
        img_style_parts.append(f"border-radius:{radius_px}px")
        img_style_parts.append("display:block")
        img_style = "; ".join(img_style_parts)

        # Quote and delete button row
        quote_delete_row = _build_quote_delete_row(
            show_quotes, quote_index, unique_quotes, data_folder, filename_escaped_i
        )
        quote_index += 1 if show_quotes and quote_index < len(unique_quotes) else 0

        # Include data-fullsrc and data-filename attributes so JS can open the image in fullscreen
        data_fullsrc = html.escape(img_src_i, quote=True)
        data_fname = html.escape(str(data_fname_raw), quote=True)
        cell_html = (
            f"<div style=\"flex:0 0 {cell_width_css}; max-width:{cell_width_css}; display:flex; align-items:center; justify-content:center; flex-direction:column; text-align:center;\">"
            f"<img src=\"{img_src_i}\" data-fullsrc=\"{data_fullsrc}\" data-filename=\"{html.escape(data_fname_raw, quote=True)}\" data-folder=\"{folder_attr}\" style=\"{img_style}\" title=\"{title_attr_i}\">"
            f"{quote_delete_row}"
            f"</div>"
        )
        images_cells.append(cell_html)

    # If there were no images, provide mobile-mode fallback for website
    if not filenames:
        # mobile website cell
        if website_url and website_display_mode == "mobile":
            website_cell = _create_website_cell(cfg, quote_index, unique_quotes if show_quotes else [])
            if website_cell:
                images_cells.append(website_cell)
                quote_index += 1

    # Desktop mode: inject website above images
    website_html = ""
    if website_url and website_display_mode == "desktop":
        website_html = _build_desktop_website(cfg, show_quotes)

    # whether click-to-fullscreen is enabled
    click_open = bool(cfg.get("click_open_fullscreen", True))

    # Only join actual string cells; skip stray non-string values (avoid rendering 'False')
    imgs_html = ''.join(x for x in images_cells if isinstance(x, str) and x)
    click_js_bool = "true" if click_open else "false"

    extra_html = (
        website_html
        + "\n" +
        "<div style=\"text-align:center; margin-top:15px;\" id=\"random-image-container\">\n"
        "  <div style=\"display:flex; flex-wrap:wrap; justify-content:center; gap:" + str(gap_px) + "px;\">\n"
        + imgs_html +
        "\n  </div>\n</div>\n"
        + "<script>\n(function() {\n"
        "  var clickOpen = " + click_js_bool + ";\n"
        "  function send(msg) {\n"
        "    try {\n"
        "      if (typeof pycmd !== 'undefined') { pycmd(msg); return; }\n"
        "      if (typeof window.pycmd !== 'undefined') { window.pycmd(msg); return; }\n"
        "    } catch (e) {}\n"
        "  }\n"
        "  window.deleteRandomImage = function(folder, fname) {\n"
        "    try {\n"
        "      var f1 = encodeURIComponent(String(folder || ''));\n"
        "      var f2 = encodeURIComponent(String(fname || ''));\n"
        "      send('randomImageDelete:' + f1 + '|' + f2);\n"
        "    } catch (e) {}\n"
        "  };\n"
        "  function attachHandlers() {\n"
        "    var imgs = document.querySelectorAll('#random-image-container img[data-fullsrc]');\n"
        "    imgs.forEach(function(i) {\n"
        "      try { i.style.cursor = clickOpen ? 'zoom-in' : 'default'; } catch (e) {}\n"
        "      if (i._scListenerAdded) return;\n"
        "      i.addEventListener('click', function(ev) {\n"
        "        try { ev.stopPropagation(); } catch (e) {}\n"
        "        try {\n"
        "          var folder = this.getAttribute('data-folder') || '';\n"
        "          var fname = this.getAttribute('data-filename') || '';\n"
        "          send('randomImageClicked:' + encodeURIComponent(folder) + '|' + encodeURIComponent(fname));\n"
        "        } catch (e) {}\n"
        "        if (clickOpen) {\n"
        "          try { var src = this.getAttribute('data-fullsrc'); if (src) send('scOpenImage:' + src); } catch (e) {}\n"
        "        }\n"
        "      });\n"
        "      i._scListenerAdded = true;\n"
        "    });\n"
        "  }\n"
        "  attachHandlers();\n"
        "  var container = document.getElementById('random-image-container');\n"
        "  if (container && window.MutationObserver) {\n"
        "    try { var mo = new MutationObserver(attachHandlers); mo.observe(container, { childList: true, subtree: true }); } catch (e) {}\n"
        "  }\n"
        "})();\n</script>\n"
    )

    # Inject answer-submit popup (if queued) on the next question render
    extra_html += _build_answer_submit_popup_html(kind)

    return text + extra_html


def queue_answer_submit_popup(ease: int, cfg: dict | None = None) -> None:
    """Queue a happy/angry image popup to be shown on the next question render."""
    global _pending_answer_popup

    try:
        if cfg is None:
            cfg = get_config()
        if not bool(cfg.get("enabled", True)):
            return
        if not bool(cfg.get("answer_image_enabled", False)):
            return

        ease_i = int(ease)
        if ease_i in (1, 2):
            folder = str(cfg.get("answer_image_angry_folder", "") or "").strip()
        elif ease_i in (3, 4):
            folder = str(cfg.get("answer_image_happy_folder", "") or "").strip()
        else:
            return

        if not folder:
            return

        # Folder can be either:
        # - absolute path on disk (recommended)
        # - OR a collection.media subfolder name (legacy)
        disk_folder = _resolve_existing_folder(folder)

        duration_s = int(cfg.get("answer_image_duration_seconds", 3) or 3)
        if duration_s < 1:
            duration_s = 1
        if duration_s > 30:
            duration_s = 30

        if disk_folder:
            picked_path = _pick_random_image_path_from_folder(disk_folder)
            if not picked_path:
                return
            rel_media = _copy_answer_popup_image_into_media(picked_path)
            if not rel_media:
                return
            src = urlquote(rel_media, safe='/')
        else:
            folder_media = sanitize_folder_name(folder)

            # Reuse existing picker by temporarily overriding folder_name
            cfg2 = dict(cfg)
            cfg2["folder_name"] = folder_media
            filenames = pick_random_image_filenames(cfg2, 1)
            if not filenames:
                return

            fname = filenames[0]
            rel_src = fname

            try:
                image_folder_path = get_media_subfolder_path(folder_media) or ""
                if image_folder_path:
                    rel_src = ensure_optimized_copy(image_folder_path, fname) or fname
            except Exception:
                rel_src = fname

            src = f"{folder_media}/{urlquote(rel_src, safe='/')}"

        _pending_answer_popup = {
            "src": src,
            "duration_ms": int(duration_s * 1000),
        }
    except Exception:
        # Non-fatal
        return


def _consume_answer_submit_popup() -> dict | None:
    global _pending_answer_popup
    data = _pending_answer_popup
    _pending_answer_popup = None
    return data


def _build_answer_submit_popup_html(kind: str) -> str:
    # Show it on the *next* question render after the user answers a card.
    if not str(kind or "").endswith("Question"):
        return ""

    data = _consume_answer_submit_popup()
    if not data:
        return ""

    src = html.escape(str(data.get("src", "")), quote=True)
    duration_ms = int(data.get("duration_ms", 3000) or 3000)
    if duration_ms < 250:
        duration_ms = 250

    return (
        "\n"
        "<script>\n"
        "(function() {\n"
        "  try {\n"
        "    var src = '" + src.replace("'", "\\'") + "';\n"
        "    var durationMs = " + str(duration_ms) + ";\n"
        "    var popup = document.getElementById('sc-answer-img-popup');\n"
        "    var img;\n"
        "    if (!popup) {\n"
        "      popup = document.createElement('div');\n"
        "      popup.id = 'sc-answer-img-popup';\n"
        "      popup.style.cssText = 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:99998;display:none;';\n"
        "      img = document.createElement('img');\n"
        "      img.id = 'sc-answer-img-popup-img';\n"
        "      img.style.cssText = 'max-width:min(70vw,420px);max-height:min(60vh,420px);border-radius:10px;cursor:zoom-in;display:block;';\n"
        "      popup.appendChild(img);\n"
        "      document.body.appendChild(popup);\n"
        "    }\n"
        "    img = document.getElementById('sc-answer-img-popup-img') || popup.querySelector('img');\n"
        "    if (!img) return;\n"
        "    img.src = src;\n"
        "    popup.style.display = 'block';\n"
        "\n"
        "    var expireAt = Date.now() + durationMs;\n"
        "    var remainingMs = durationMs;\n"
        "    var timer = null;\n"
        "\n"
        "    function hidePopup() {\n"
        "      try {\n"
        "        var zoom = document.getElementById('sc-answer-zoom-overlay');\n"
        "        if (zoom && zoom.parentNode) zoom.parentNode.removeChild(zoom);\n"
        "      } catch (e) {}\n"
        "      try { popup.style.display = 'none'; } catch (e) {}\n"
        "    }\n"
        "\n"
        "    function startTimer(ms) {\n"
        "      try { if (timer) { clearTimeout(timer); timer = null; } } catch (e) {}\n"
        "      if (ms <= 0) { hidePopup(); return; }\n"
        "      timer = setTimeout(hidePopup, ms);\n"
        "    }\n"
        "\n"
        "    function openZoom() {\n"
        "      if (document.getElementById('sc-answer-zoom-overlay')) return;\n"
        "      var overlay = document.createElement('div');\n"
        "      overlay.id = 'sc-answer-zoom-overlay';\n"
        "      overlay.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.9);z-index:99999;';\n"
        "      var wrap = document.createElement('div');\n"
        "      wrap.style.cssText = 'position:absolute;left:0;top:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;padding:20px;overflow:auto;';\n"
        "      var big = document.createElement('img');\n"
        "      big.src = src;\n"
        "      big.style.cssText = 'display:block;border-radius:10px;';\n"
        "      wrap.appendChild(big);\n"
        "      overlay.appendChild(wrap);\n"
        "      document.body.appendChild(overlay);\n"
        "      // Close on click (no ✕)\n"
        "      overlay.addEventListener('click', function() { closeZoomAndResume(); });\n"
        "      big.addEventListener('click', function(ev) { try { ev.stopPropagation(); } catch(e) {} closeZoomAndResume(); });\n"
        "    }\n"
        "\n"
        "    function closeZoom() {\n"
        "      var overlay = document.getElementById('sc-answer-zoom-overlay');\n"
        "      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);\n"
        "    }\n"
        "\n"
        "    var zoomed = false;\n"
        "    function applyZoom() {\n"
        "      try {\n"
        "        var overlay = document.getElementById('sc-answer-zoom-overlay');\n"
        "        if (!overlay) return;\n"
        "        var wrap = overlay.firstChild;\n"
        "        var big = wrap ? wrap.querySelector('img') : null;\n"
        "        if (!big) return;\n"
        "        var nw = big.naturalWidth || 0;\n"
        "        var nh = big.naturalHeight || 0;\n"
        "        var v = 0;\n"
        "        if (v <= 0 || !nw || !nh) {\n"
        "          wrap.style.alignItems = 'center';\n"
        "          wrap.style.justifyContent = 'center';\n"
        "          big.style.maxWidth = '95%';\n"
        "          big.style.maxHeight = '95%';\n"
        "          big.style.width = 'auto';\n"
        "          big.style.height = 'auto';\n"
        "          big.style.cursor = 'default';\n"
        "          try { } catch(e) {}\n"
        "          return;\n"
        "        }\n"
        "        var z = v / 100.0;\n"
        "        wrap.style.alignItems = 'flex-start';\n"
        "        wrap.style.justifyContent = 'flex-start';\n"
        "        big.style.maxWidth = 'none';\n"
        "        big.style.maxHeight = 'none';\n"
        "        big.style.width = Math.round(nw * z) + 'px';\n"
        "        big.style.height = Math.round(nh * z) + 'px';\n"
        "        big.style.cursor = 'default';\n"
        "        try { } catch(e) {}\n"
        "      } catch (e) {}\n"
        "    }\n"
        "    function closeZoomAndResume() {\n"
        "      closeZoom();\n"
        "      zoomed = false;\n"
        "      if (remainingMs <= 0) { hidePopup(); } else { expireAt = Date.now() + remainingMs; startTimer(remainingMs); }\n"
        "    }\n"
        "    function toggleZoom() {\n"
        "      if (!zoomed) {\n"
        "        remainingMs = Math.max(0, expireAt - Date.now());\n"
        "        try { if (timer) { clearTimeout(timer); timer = null; } } catch (e) {}\n"
        "        openZoom();\n"
        "        zoomed = true;\n"
        "        applyZoom();\n"
        "      } else {\n"
        "        closeZoomAndResume();\n"
        "      }\n"
        "    }\n"
        "\n"
        "    img.onclick = function(ev) { try { ev.stopPropagation(); } catch (e) {} toggleZoom(); };\n"
        "    startTimer(durationMs);\n"
        "  } catch (e) {}\n"
        "})();\n"
        "</script>\n"
    )


def _resolve_existing_folder(folder: str) -> str | None:
    try:
        if not folder:
            return None
        expanded = os.path.expanduser(folder)
        if os.path.isdir(expanded):
            return expanded

        # allow relative to this add-on folder
        base = os.path.dirname(__file__)
        candidate = os.path.join(base, folder)
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        return None
    return None


def _pick_random_image_path_from_folder(folder_path: str) -> str | None:
    try:
        files: list[str] = []
        for root, _dirs, names in os.walk(folder_path):
            for n in names:
                if n.lower().endswith(_VALID_IMG_EXT):
                    files.append(os.path.join(root, n))
        if not files:
            return None
        return random.choice(files)
    except Exception:
        return None


def _copy_answer_popup_image_into_media(src_path: str) -> str | None:
    """Copy a disk image into collection.media/study_companion_answer_popup and return its media-relative path."""
    try:
        col = getattr(mw, "col", None)
        if not col:
            return None
        media_dir = col.media.dir()
        dest_folder = os.path.join(media_dir, _ANSWER_POPUP_MEDIA_FOLDER)
        os.makedirs(dest_folder, exist_ok=True)

        st = os.stat(src_path)
        ext = os.path.splitext(src_path)[1].lower() or ".png"
        h = hashlib.sha1()
        h.update(os.path.abspath(src_path).encode("utf-8", errors="ignore"))
        h.update(str(int(st.st_mtime)).encode("utf-8"))
        h.update(str(int(st.st_size)).encode("utf-8"))
        name = h.hexdigest() + ext
        dest_path = os.path.join(dest_folder, name)
        if not os.path.exists(dest_path):
            shutil.copy2(src_path, dest_path)

        rel = os.path.relpath(dest_path, media_dir).replace("\\", "/")
        return rel
    except Exception:
        return None


def _build_quote_delete_row(show_quotes: bool, quote_index: int, quotes: list[str], folder_name: str, filename_escaped: str) -> str:
    """Build the quote and delete button row for an image.

    This function avoids using Python f-strings that contain JS braces
    by concatenating strings and escaping single quotes for safe
    insertion into JS string literals.
    """
    # escape backslashes and single quotes for safe JS single-quoted literals
    js_folder = str(folder_name or "").replace("\\", "\\\\").replace("'", "\\'")
    js_fname = filename_escaped.replace("\\", "\\\\").replace("'", "\\'")
    # common buttons HTML (delete) only
    delete_btn = (
        "<button onclick=\"deleteRandomImage('{}','{}')\" "
        "style=\"background:transparent; border:none; cursor:pointer; padding:0 6px; font-size:0.9em; color:#ff6b6b;\" "
        "title=\"Delete\">🗑️</button>".format(js_folder, js_fname)
    )
    fav_btn = ""
    bl_btn = ""

    if show_quotes and quote_index < len(quotes):
        quote_text = html.escape(quotes[quote_index])
        cfg = get_config()
        fs = float(cfg.get("quotes_font_size_em", 0.9) or 0.9)
        if fs < 0.6:
            fs = 0.6
        if fs > 2.0:
            fs = 2.0
        italic = "italic" if bool(cfg.get("quotes_italic", True)) else "normal"
        align = str(cfg.get("quotes_align", "left") or "left")
        if align not in ("left", "center"):
            align = "left"
        return (
            '<div style="display:flex; align-items:flex-start; margin-top:8px; gap:4px;">'
            '<div style="flex:1; font-size:' + str(fs) + 'em; color:#fff; font-style:' + italic + '; text-align:' + align + '; line-height:1.3;">'
            + quote_text +
            '</div>'
            + delete_btn + fav_btn + bl_btn +
            '</div>'
        )
    else:
        return (
            '<div style="text-align:center; margin-top:8px;">'
            + delete_btn + fav_btn + bl_btn +
            '</div>'
        )


def _create_website_cell(cfg: dict, quote_index: int, quotes: list[str]) -> str:
    """Create a website cell for mobile mode grid layout."""
    global _website_iframe_injected
    
    website_url = str(cfg.get("website_url", "")).strip()
    if not website_url:
        return ""
    
    website_height_vh = int(cfg.get("website_height_vh", 50) or 50)
    website_width_percent = int(cfg.get("website_width_percent", 100) or 100)
    website_radius_px = int(cfg.get("website_border_radius_px", 4) or 4)
    if website_radius_px < 0:
        website_radius_px = 0
    if website_radius_px > 48:
        website_radius_px = 48
    cell_width_css = f"calc(33.33% - 12px)"
    
    quote_text = ""
    if quote_index < len(quotes):
        quote_text = html.escape(quotes[quote_index])
    
    quote_delete_row = f"""
    <div style="display:flex; align-items:flex-start; margin-top:8px; gap:4px;">
        <div style="flex:1; font-size:{float(cfg.get('quotes_font_size_em', 0.9) or 0.9)}em; color:#fff; font-style:{'italic' if bool(cfg.get('quotes_italic', True)) else 'normal'}; text-align:{str(cfg.get('quotes_align', 'left') or 'left') if str(cfg.get('quotes_align', 'left') or 'left') in ('left','center') else 'left'}; line-height:1.3;">
            {quote_text}
        </div>
    </div>
    """
    
    if not _website_iframe_injected:
        website_cell = f"""
<div style="flex:0 0 {cell_width_css}; max-width:{cell_width_css}; text-align:center;">
    <div id="persistent-website-container" style="width:{website_width_percent}%; margin:0 auto;">
        <iframe id="persistent-website-iframe" 
                src="{html.escape(website_url, quote=True)}" 
            style="width:100%; height:{website_height_vh}vh; border-radius:{website_radius_px}px; display:block;"
                frameborder="0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
        </iframe>
    </div>
    {quote_delete_row}
    <script>
    (function() {{
        var container = document.getElementById('persistent-website-container');
        if (container) {{
            window._persistentWebsiteContainer = container;
        }}
    }})();
    </script>
</div>
"""
        _website_iframe_injected = True
    else:
        website_cell = f"""
<div style="flex:0 0 {cell_width_css}; max-width:{cell_width_css}; text-align:center;">
    <div id="persistent-website-container-placeholder"></div>
    {quote_delete_row}
    <script>
    (function() {{
        var placeholder = document.getElementById('persistent-website-container-placeholder');
        if (placeholder) {{
            if (window._persistentWebsiteContainer) {{
                placeholder.parentNode.replaceChild(window._persistentWebsiteContainer, placeholder);
            }} else {{
                var container = document.createElement('div');
                container.id = 'persistent-website-container';
                container.style.cssText = 'width:{website_width_percent}%; margin:0 auto;';
                
                var iframe = document.createElement('iframe');
                iframe.id = 'persistent-website-iframe';
                iframe.src = '{html.escape(website_url, quote=True).replace("'", "&#39;")}';
                iframe.style.cssText = 'width:100%; height:{website_height_vh}vh; border-radius:{website_radius_px}px; display:block;';
                iframe.setAttribute('frameborder', '0');
                iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture');
                iframe.setAttribute('allowfullscreen', '');
                
                container.appendChild(iframe);
                placeholder.parentNode.replaceChild(container, placeholder);
                window._persistentWebsiteContainer = container;
            }}
        }}
    }})();
    </script>
</div>
"""
    return website_cell


def _build_desktop_website(cfg: dict, show_quotes: bool) -> str:
    """Build desktop website HTML (full-width above images)."""
    global _website_iframe_injected
    
    website_url = str(cfg.get("website_url", "")).strip()
    website_height_vh = int(cfg.get("website_height_vh", 50) or 50)
    website_radius_px = int(cfg.get("website_border_radius_px", 4) or 4)
    if website_radius_px < 0:
        website_radius_px = 0
    if website_radius_px > 48:
        website_radius_px = 48
    
    desktop_website_quote = get_random_quote() if show_quotes else ""
    desktop_quote_html = ""
    if show_quotes and desktop_website_quote:
        fs = float(cfg.get("quotes_font_size_em", 0.9) or 0.9)
        if fs < 0.6:
            fs = 0.6
        if fs > 2.0:
            fs = 2.0
        italic = "italic" if bool(cfg.get("quotes_italic", True)) else "normal"
        align = str(cfg.get("quotes_align", "left") or "left")
        if align not in ("left", "center"):
            align = "left"
        desktop_quote_html = f"""
            <div style="margin-top:8px; font-size:{fs}em; color:#fff; font-style:{italic}; text-align:{align};">
                {html.escape(desktop_website_quote)}
            </div>
            """
    
    if not _website_iframe_injected:
        website_html = f"""
<div id="persistent-website-container" style="width:100%; margin-top:20px; margin-bottom:20px;">
    <iframe id="persistent-website-iframe" 
            src="{html.escape(website_url, quote=True)}" 
            style="width:100%; height:{website_height_vh}vh; border:1px solid #ccc; border-radius:{website_radius_px}px; display:block;"
            frameborder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen>
    </iframe>
</div>
{desktop_quote_html}
<script>
(function() {{
    var container = document.getElementById('persistent-website-container');
    if (container) {{
        window._persistentWebsiteContainer = container;
    }}
}})();
</script>
"""
        _website_iframe_injected = True
    else:
        website_html = f"""
<div id="persistent-website-container-placeholder"></div>
{desktop_quote_html}
<script>
(function() {{
    var placeholder = document.getElementById('persistent-website-container-placeholder');
    if (placeholder) {{
        if (window._persistentWebsiteContainer) {{
            placeholder.parentNode.replaceChild(window._persistentWebsiteContainer, placeholder);
        }} else {{
            var container = document.createElement('div');
            container.id = 'persistent-website-container';
            container.style.cssText = 'width:100%; margin-top:20px; margin-bottom:20px;';
            
            var iframe = document.createElement('iframe');
            iframe.id = 'persistent-website-iframe';
            iframe.src = '{html.escape(website_url, quote=True).replace("'", "&#39;")}';
            iframe.style.cssText = 'width:100%; height:{website_height_vh}vh; border:1px solid #ccc; border-radius:{website_radius_px}px; display:block;';
            iframe.setAttribute('frameborder', '0');
            iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture');
            iframe.setAttribute('allowfullscreen', '');
            
            container.appendChild(iframe);
            placeholder.parentNode.replaceChild(container, placeholder);
            window._persistentWebsiteContainer = container;
        }}
    }}
}})();
</script>
"""
    
    return website_html


# Behavior/session features removed
