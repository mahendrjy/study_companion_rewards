"""
Core features for StudyCompanion add-on.
Implements card rendering with images, quotes, and website embedding.
"""

import html
from urllib.parse import quote as urlquote
from typing import Dict

from .config_manager import get_config
from .image_manager import (
    pick_random_image_filenames,
    sanitize_folder_name,
    ensure_optimized_copy,
    get_prioritized_files,
    increment_click_count,
    increment_view_count,
)
from .image_manager import get_media_subfolder_path, _load_meta, _save_meta
from .quotes import get_random_quote, get_unique_random_quotes


_current_card_id: int | None = None
_website_iframe_injected: bool = False

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

    if kind.endswith("Question") and not cfg.get("show_on_question", True):
        return text
    if kind.endswith("Answer") and not cfg.get("show_on_answer", True):
        return text

    card_id = card.id if card else None
    is_new_card = (card_id != _current_card_id)
    if is_new_card:
        _current_card_id = card_id

    # Prepare website and video settings early so they can be used even when images list is empty
    website_url = str(cfg.get("website_url", "")).strip()
    website_display_mode = str(cfg.get("website_display_mode", "mobile")).lower()

    # video feature removed

    images_count = int(cfg.get("images_to_show", 1) or 1)
    filenames = pick_random_image_filenames(cfg, images_count)
    # Ensure filenames is iterable even if picker returned None
    if not filenames:
        filenames = []

    # video feature removed

    # behavior/emotion features removed

    folder_name = sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))

    max_w = cfg.get("max_width_percent", 80)
    max_h_value = cfg.get("max_height_vh", 60)
    max_h_unit = str(cfg.get("max_height_unit", "vh")).lower()

    website_url = str(cfg.get("website_url", "")).strip()
    website_display_mode = str(cfg.get("website_display_mode", "mobile")).lower()
    show_quotes = cfg.get("show_motivation_quotes", True)
    
    total_items_needing_quotes = images_count
    if website_url and website_display_mode == "mobile":
        total_items_needing_quotes += 1
    
    unique_quotes = get_unique_random_quotes(total_items_needing_quotes) if show_quotes else []
    quote_index = 0

    images_cells = []
    columns = min(3, max(1, images_count))
    cell_width_css = f"calc({100/columns:.4f}% - 12px)"
    
    # increment view counts for selected filenames
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

    # video feature removed

    for idx, fname in enumerate(filenames):
        # Insert website in mobile mode after first image
        if website_url and website_display_mode == "mobile" and idx == 0:
            website_cell = _create_website_cell(cfg, quote_index, unique_quotes if show_quotes else [])
            if website_cell:
                images_cells.append(website_cell)
                quote_index += 1

        # video feature removed

        # prefer optimized cached copy if available
        rel_src = fname
        try:
            if image_folder_path:
                rel_src = ensure_optimized_copy(image_folder_path, fname) or fname
        except Exception:
            rel_src = fname

        img_src_i = f"{folder_name}/{urlquote(rel_src, safe='/')}"
        title_attr_i = html.escape(fname, quote=True)
        filename_escaped_i = html.escape(fname, quote=True)

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
        img_style_parts.append("border-radius:8px")
        img_style_parts.append("display:block")
        img_style = "; ".join(img_style_parts)

        # Quote and delete button row
        quote_delete_row = _build_quote_delete_row(
            show_quotes, quote_index, unique_quotes, filename_escaped_i
        )
        quote_index += 1 if show_quotes and quote_index < len(unique_quotes) else 0

        # Include data-fullsrc and data-filename attributes so JS can open the image in fullscreen
        data_fullsrc = html.escape(img_src_i, quote=True)
        data_fname = html.escape(fname, quote=True)
        cell_html = (
            f"<div style=\"flex:0 0 {cell_width_css}; max-width:{cell_width_css}; display:flex; align-items:center; justify-content:center; flex-direction:column; text-align:center;\">"
            f"<img src=\"{img_src_i}\" data-fullsrc=\"{data_fullsrc}\" data-filename=\"{data_fname}\" style=\"{img_style}\" title=\"{title_attr_i}\">"
            f"{quote_delete_row}"
            f"</div>"
        )
        images_cells.append(cell_html)

    # If there were no images, provide mobile-mode fallbacks for website/video
    if not filenames:
        # mobile website cell
        if website_url and website_display_mode == "mobile":
            website_cell = _create_website_cell(cfg, quote_index, unique_quotes if show_quotes else [])
            if website_cell:
                images_cells.append(website_cell)
                quote_index += 1

        # video feature removed

    # Desktop mode: inject website above images
    website_html = ""
    if website_url and website_display_mode == "desktop":
        website_html = _build_desktop_website(cfg, show_quotes)
    # Desktop video: inject video above images alongside website
    # video feature removed
    video_html = ""
    # place video_html before website_html
    website_html = video_html + website_html

    # whether click-to-fullscreen is enabled
    click_open = bool(cfg.get("click_open_fullscreen", True))

    # Only join actual string cells; skip stray non-string values (avoid rendering 'False')
    imgs_html = ''.join(x for x in images_cells if isinstance(x, str) and x)
    click_js_bool = "true" if click_open else "false"

    extra_html = (
        website_html
        + "\n" +
        "<div style=\"text-align:center; margin-top:15px;\" id=\"random-image-container\">\n"
        "  <div style=\"display:flex; flex-wrap:wrap; justify-content:center; gap:8px;\">\n"
        + imgs_html +
        "\n  </div>\n</div>\n"
        + "<script>\n(function() {\n"
        "  function deleteRandomImage(filename) {\n"
        "    if (typeof pycmd !== 'undefined') {\n"
        "      pycmd('randomImageDelete:' + filename);\n"
        "    } else if (typeof window.pycmd !== 'undefined') {\n"
        "      window.pycmd('randomImageDelete:' + filename);\n"
        "    }\n"
        "  }\n"
        "  window.deleteRandomImage = deleteRandomImage;\n"
        ""
            "  (function() {\n"
        "    var clickOpen = " + click_js_bool + ";\n"
        "    if (!clickOpen) return;\n"
        "    function openImageFullscreen(src) {\n"
        "      if (!src) return;\n"
        "      if (document.getElementById('scf-overlay')) return;\n"
        "      var overlay = document.createElement('div');\n"
        "      overlay.id = 'scf-overlay';\n"
        "      overlay.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center;z-index:99999;padding:20px;';\n"
        "      var img = document.createElement('img');\n"
        "      img.src = src;\n"
        "      img.style.cssText = 'max-width:95%;max-height:95%;border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,0.5);cursor:zoom-out;';\n"
        "      overlay.appendChild(img);\n"
        "      function removeOverlay() { try { if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay); document.removeEventListener('keydown', onKey); } catch (e) {} }\n"
        "      function onKey(ev) { if (ev.key === 'Escape') removeOverlay(); }\n"
        "      overlay.addEventListener('click', function(e) { if (e.target === overlay) removeOverlay(); });\n"
        "      img.addEventListener('click', removeOverlay);\n"
        "      document.addEventListener('keydown', onKey);\n"
        "      document.body.appendChild(overlay);\n"
        "    }\n"
        "    function attachHandlers() {\n"
        "      var imgs = document.querySelectorAll('#random-image-container img[data-fullsrc]');\n"
        "      imgs.forEach(function(i) {\n"
        "        i.style.cursor = 'zoom-in';\n"
        "        if (!i._scListenerAdded) {\n"
        "          i.addEventListener('click', function(ev) {\n"
        "            ev.stopPropagation();\n"
        "            try {\n"
        "              var fname = this.getAttribute('data-filename');\n"
        "              if (typeof pycmd !== 'undefined') { pycmd('randomImageClicked:' + fname); }\n"
        "              else if (typeof window.pycmd !== 'undefined') { window.pycmd('randomImageClicked:' + fname); }\n"
        "            } catch (e) {}\n"
        "            openImageFullscreen(this.getAttribute('data-fullsrc'));\n"
        "          });\n"
        "          i._scListenerAdded = true;\n"
        "        }\n"
        "      });\n"
        "    }\n"
        "    attachHandlers();\n"
        "    function preloadAll() {\n"
        "      var imgs = document.querySelectorAll('#random-image-container img[data-fullsrc]');\n"
        "      imgs.forEach(function(i) { try { var src = i.getAttribute('data-fullsrc'); if (src) { var p = new Image(); p.src = src; } } catch (e) {} });\n"
        "    }\n"
        "    preloadAll();\n"
        "    var container = document.getElementById('random-image-container');\n"
        "    if (container && window.MutationObserver) { var mo = new MutationObserver(attachHandlers); mo.observe(container, { childList: true, subtree: true }); }\n"
        "    window.openImageFullscreen = openImageFullscreen;\n"
        "  })();\n"
        # orientation-aware single image: apply appropriate sizing for portrait vs landscape
        + (
            "\n    var autoOrient = "
            + ("true" if bool(cfg.get("auto_orient_single_image", True)) else "false")
            + ";\n    var maxHVal = " + str(int(max_h_value)) + ";\n    var maxHUnit = '" + max_h_unit + "';\n"
            "    if (autoOrient) {\n"
            "      var imgs = document.querySelectorAll('#random-image-container img[data-fullsrc]');\n"
            "      if (imgs.length === 1) { var i = imgs[0]; function adjustOrient() { try { var w = i.naturalWidth || i.width; var h = i.naturalHeight || i.height; if (h > w) { i.style.width = 'auto'; i.style.maxHeight = maxHVal + (maxHUnit==='vh' ? 'vh' : '%'); i.style.height = 'auto'; i.style.objectFit = 'contain'; i.style.objectPosition = 'center center'; } else { i.style.width = '100%'; i.style.height = 'auto'; i.style.objectFit = 'contain'; i.style.objectPosition = 'center center'; } } catch(e){} } if (i.complete) adjustOrient(); else i.addEventListener('load', adjustOrient); }\n    }\n"
        )
        + "})();\n</script>\n"
    )
    return text + extra_html


def _build_quote_delete_row(show_quotes: bool, quote_index: int, quotes: list[str], filename_escaped: str) -> str:
    """Build the quote and delete button row for an image.

    This function avoids using Python f-strings that contain JS braces
    by concatenating strings and escaping single quotes for safe
    insertion into JS string literals.
    """
    # escape backslashes and single quotes for safe JS single-quoted literals
    js_fname = filename_escaped.replace("\\", "\\\\").replace("'", "\\'")
    # common buttons HTML (delete) only
    delete_btn = (
        "<button onclick=\"deleteRandomImage('{}')\" "
        "style=\"background:transparent; border:none; cursor:pointer; padding:0 6px; font-size:0.9em; color:#ff6b6b;\" "
        "title=\"Delete\">🗑️</button>".format(js_fname)
    )
    fav_btn = ""
    bl_btn = ""

    if show_quotes and quote_index < len(quotes):
        quote_text = html.escape(quotes[quote_index])
        return (
            '<div style="display:flex; align-items:flex-start; margin-top:8px; gap:4px;">'
            '<div style="flex:1; font-size:0.9em; color:#fff; font-style:italic; text-align:left; line-height:1.3;">'
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
    cell_width_css = f"calc(33.33% - 12px)"
    
    quote_text = ""
    if quote_index < len(quotes):
        quote_text = html.escape(quotes[quote_index])
    
    quote_delete_row = f"""
    <div style="display:flex; align-items:flex-start; margin-top:8px; gap:4px;">
        <div style="flex:1; font-size:0.9em; color:#fff; font-style:italic; text-align:left; line-height:1.3;">
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
                style="width:100%; height:{website_height_vh}vh; border-radius:4px; display:block;"
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
                iframe.style.cssText = 'width:100%; height:{website_height_vh}vh; border-radius:4px; display:block;';
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
    
    desktop_website_quote = get_random_quote() if show_quotes else ""
    desktop_quote_html = ""
    if show_quotes and desktop_website_quote:
        desktop_quote_html = f"""
            <div style="margin-top:8px; font-size:0.9em; color:#fff; font-style:italic; text-align:left;">
                {html.escape(desktop_website_quote)}
            </div>
            """
    
    if not _website_iframe_injected:
        website_html = f"""
<div id="persistent-website-container" style="width:100%; margin-top:20px; margin-bottom:20px;">
    <iframe id="persistent-website-iframe" 
            src="{html.escape(website_url, quote=True)}" 
            style="width:100%; height:{website_height_vh}vh; border:1px solid #ccc; border-radius:4px; display:block;"
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
            iframe.style.cssText = 'width:100%; height:{website_height_vh}vh; border:1px solid #ccc; border-radius:4px; display:block;';
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
