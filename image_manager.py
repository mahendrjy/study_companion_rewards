"""
Image management for StudyCompanion add-on.
Handles image file selection, deletion, and cycle state.
"""

import os
import json
import random
import hashlib
from aqt import mw
from aqt.utils import showInfo


# Supported image extensions
VALID_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg")

# Cycle state: file set from last scan and remaining list
_cycle_known_set: set[str] = set()
_cycle_remaining: list[str] = []
_cycle_state_path: str | None = None
_last_filename: str | None = None
_meta_filename = ".study_companion_meta.json"
_cache_dirname = ".study_companion_cache"

# External/system-folder images are copied into collection.media so they can be shown on cards.
# For reliability, cache copies are stored at the media root using a stable hashed name.
# We also support per-side caches by tag (e.g. 'q' or 'a').
_external_prefix = "sc_ext_"  # legacy
_external_map_filename = ".study_companion_external_map.json"


def list_external_cached_media_files(tag: str | None = None) -> list[str]:
    """Return cached external-image filenames in collection.media root.

    If tag is provided (e.g. 'q' or 'a'), return only those cached with that tag.
    """
    try:
        col = getattr(mw, "col", None)
        if not col:
            return []
        media_dir = col.media.dir()
        try:
            entries = os.listdir(media_dir)
        except Exception:
            return []
        out: list[str] = []
        tag_s = str(tag or "").strip().lower()
        wanted_prefix = f"sc_ext_{tag_s}_" if tag_s else ""
        for n in entries:
            if not n:
                continue
            ns = str(n)
            if wanted_prefix:
                if not ns.startswith(wanted_prefix):
                    continue
            else:
                # any cached external file (legacy or tagged)
                if not (ns.startswith(_external_prefix) or ns.startswith("sc_ext_q_") or ns.startswith("sc_ext_a_")):
                    continue
            if ns.lower().endswith(VALID_EXT):
                out.append(ns)
        return out
    except Exception:
        return []


def _external_map_path(media_dir: str) -> str:
    return os.path.join(media_dir, _external_map_filename)


def _load_external_map(media_dir: str) -> dict:
    try:
        path = _external_map_path(media_dir)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # Backwards-compat: older versions stored the map inside a subfolder.
        try:
            legacy_path = os.path.join(media_dir, "study_companion_external_images", _external_map_filename)
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _save_external_map(media_dir: str, data: dict) -> None:
    try:
        path = _external_map_path(media_dir)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[StudyCompanion] Failed to save external map: {e}")


def copy_external_image_into_media(src_path: str, tag: str | None = None) -> str | None:
    """Copy a system-folder image into collection.media; return media filename.

    We store copies in the media root (not a subfolder) because it's the most
    compatible way to display images inside Anki's reviewer webview.
    """
    try:
        col = getattr(mw, "col", None)
        if not col:
            return None
        if not src_path or not os.path.exists(src_path):
            return None

        media_dir = col.media.dir()
        st = os.stat(src_path)
        ext = os.path.splitext(src_path)[1].lower() or ".png"

        h = hashlib.sha1()
        h.update(os.path.abspath(src_path).encode("utf-8", errors="ignore"))
        h.update(str(int(st.st_mtime)).encode("utf-8"))
        h.update(str(int(st.st_size)).encode("utf-8"))
        tag_s = str(tag or "").strip().lower()
        prefix = f"sc_ext_{tag_s}_" if tag_s else _external_prefix
        name = prefix + h.hexdigest() + ext

        dest_path = os.path.join(media_dir, name)
        if not os.path.exists(dest_path):
            # copy into media cache
            import shutil

            shutil.copy2(src_path, dest_path)

        rel = os.path.basename(dest_path)

        # Persist mapping so delete can remove original too.
        data = _load_external_map(media_dir)
        data[rel] = os.path.abspath(src_path)
        _save_external_map(media_dir, data)

        return rel
    except Exception as e:
        print(f"[StudyCompanion] copy_external_image_into_media error: {e}")
        return None


def delete_external_cached_image(rel_media_path: str) -> bool:
    """Delete a cached external image and (best-effort) its original source file."""
    try:
        col = getattr(mw, "col", None)
        if not col:
            return False
        media_dir = col.media.dir()

        rel = str(rel_media_path or "").lstrip("/\\")
        if not rel:
            return False

        data = _load_external_map(media_dir)
        original = data.get(rel)

        # Delete cached copy
        try:
            cached_full = os.path.join(media_dir, rel)
            if os.path.exists(cached_full):
                os.remove(cached_full)
        except Exception:
            pass

        # Delete original (if still exists)
        try:
            if isinstance(original, str) and original and os.path.exists(original):
                os.remove(original)
        except Exception:
            pass

        # Remove mapping entry
        if rel in data:
            try:
                del data[rel]
                _save_external_map(media_dir, data)
            except Exception:
                pass

        return True
    except Exception as e:
        print(f"[StudyCompanion] delete_external_cached_image error: {e}")
        return False


def _load_cycle_state(state_path: str):
    """Load persisted cycle state; if missing/corrupt, return empty."""
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        known = set(data.get("known", []))
        remaining = data.get("remaining", [])
        return known, remaining
    except Exception:
        return set(), []


def _save_cycle_state(state_path: str, known: set[str], remaining: list[str]):
    """Persist cycle state (failure is non-fatal)."""
    try:
        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"known": sorted(list(known)), "remaining": remaining}, f, ensure_ascii=False)
        os.replace(tmp_path, state_path)
    except Exception as e:
        print(f"[StudyCompanion] Failed to save cycle state: {e}")


def sanitize_folder_name(name: str) -> str:
    """
    Normalize a collection.media subfolder name.
    - Empty => study_companion_images
    - Reject absolute/parent-like references
    """
    s = (name or "").strip()
    if not s:
        return "study_companion_images"

    s = s.replace("\\", "/")

    if s.startswith(("/", "~")) or ":" in s or ".." in s:
        showInfo("Invalid folder name. Please use a simple subfolder name, e.g. study_companion_images")
        return "study_companion_images"

    s = s.strip("/")

    if not s:
        return "study_companion_images"
    return s


def get_media_subfolder_path(folder_name: str) -> str | None:
    """Get the full path to a media subfolder."""
    col = getattr(mw, "col", None)
    if not col:
        return None
    media_dir = col.media.dir()
    return os.path.join(media_dir, folder_name)


def open_images_folder(folder_name: str | None = None) -> None:
    """Ensure collection.media/<folder_name> exists and open it."""
    from aqt.utils import openFolder
    
    if folder_name is None:
        from .config_manager import get_config
        cfg = get_config()
        folder_name = cfg.get("folder_name", "study_companion_images")

    folder_name = sanitize_folder_name(str(folder_name))
    path = get_media_subfolder_path(folder_name)
    if not path:
        showInfo("No collection is open.")
        return

    os.makedirs(path, exist_ok=True)
    openFolder(path)


def delete_image_file(filename: str, cfg: dict, folder_name_override: str | None = None) -> bool:
    """Delete an image file and remove it from cycle state.

    If folder_name_override is provided, delete from that media subfolder
    (sanitized) instead of cfg['folder_name'].

    Returns True if successful.
    """
    global _cycle_known_set, _cycle_remaining, _cycle_state_path
    try:
        col = getattr(mw, "col", None)
        if not col:
            return False

        folder_raw = folder_name_override if folder_name_override is not None else cfg.get("folder_name", "study_companion_images")
        folder_name = sanitize_folder_name(folder_raw)
        image_folder = get_media_subfolder_path(folder_name)
        if not image_folder:
            return False

        file_path = os.path.join(image_folder, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        if filename in _cycle_known_set:
            _cycle_known_set.discard(filename)
            if filename in _cycle_remaining:
                _cycle_remaining.remove(filename)

        if _cycle_state_path:
            _save_cycle_state(_cycle_state_path, _cycle_known_set, _cycle_remaining)

        return True
    except Exception as e:
        print(f"[StudyCompanion] Error deleting image: {e}")
        return False


def pick_random_image_filenames(cfg: dict, count: int) -> list[str] | None:
    """Return a list of up to `count` filenames from the media folder."""
    global _last_filename, _cycle_known_set, _cycle_remaining, _cycle_state_path
    try:
        col = getattr(mw, "col", None)
        if not col:
            return None

        folder_name = sanitize_folder_name(cfg.get("folder_name", "study_companion_images"))
        image_folder = get_media_subfolder_path(folder_name)
        if not image_folder:
            return None

        if not os.path.isdir(image_folder):
            return None

        # Collect image files recursively
        files = []
        for root, dirs, filenames in os.walk(image_folder):
            for filename in filenames:
                if filename.lower().endswith(VALID_EXT):
                    rel_path = os.path.relpath(os.path.join(root, filename), image_folder)
                    rel_path = rel_path.replace("\\", "/")
                    files.append(rel_path)

        if not files:
            return None

        result = []

        if cfg.get("avoid_repeat", True):
            files_set = set(files)
            state_path = os.path.join(image_folder, ".study_companion_cycle.json")

            if _cycle_state_path != state_path:
                _cycle_known_set, _cycle_remaining = _load_cycle_state(state_path)
                _cycle_state_path = state_path

            files_set = set(files)
            state_path = os.path.join(image_folder, ".study_companion_cycle.json")

            # Load persisted state if folder changed
            if _cycle_state_path != state_path:
                _cycle_known_set, _cycle_remaining = _load_cycle_state(state_path)
                _cycle_state_path = state_path

            # If file set changed or we have no remaining, (re)initialize remaining as a shuffled list
            if files_set != _cycle_known_set or not _cycle_remaining:
                _cycle_known_set = files_set
                _cycle_remaining = list(files_set)
                random.shuffle(_cycle_remaining)

            # Pop items from remaining until we have enough; when remaining empties,
            # reshuffle a fresh cycle (duplicates only after full cycle completed)
            while len(result) < count:
                if not _cycle_remaining:
                    _cycle_remaining = list(_cycle_known_set)
                    random.shuffle(_cycle_remaining)
                result.append(_cycle_remaining.pop())

            _save_cycle_state(state_path, _cycle_known_set, _cycle_remaining)
        else:
            if count <= len(files):
                result = random.sample(files, count)
            else:
                result = files[:]
                random.shuffle(result)
                while len(result) < count:
                    result.append(random.choice(files))

        if result:
            _last_filename = result[-1]
        return result
    except Exception as e:
        print(f"[StudyCompanion] Error while picking images: {e}")
        return None


def _meta_path(image_folder: str) -> str:
    return os.path.join(image_folder, _meta_filename)


def _cache_path(image_folder: str) -> str:
    return os.path.join(image_folder, _cache_dirname)


def _load_meta(image_folder: str) -> dict:
    path = _meta_path(image_folder)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    # ensure keys
    data.setdefault("favorites", [])
    data.setdefault("blacklist", [])
    data.setdefault("view_counts", {})
    data.setdefault("click_counts", {})
    return data


def _save_meta(image_folder: str, data: dict) -> None:
    path = _meta_path(image_folder)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[StudyCompanion] Failed to save meta: {e}")


def mark_favorite(image_folder: str, filename: str, favorite: bool) -> bool:
    try:
        meta = _load_meta(image_folder)
        fav = set(meta.get("favorites", []))
        if favorite:
            fav.add(filename)
        else:
            fav.discard(filename)
        meta["favorites"] = list(fav)
        _save_meta(image_folder, meta)
        return True
    except Exception as e:
        print(f"[StudyCompanion] mark_favorite error: {e}")
        return False


def mark_blacklist(image_folder: str, filename: str, blacklisted: bool) -> bool:
    try:
        meta = _load_meta(image_folder)
        bl = set(meta.get("blacklist", []))
        if blacklisted:
            bl.add(filename)
        else:
            bl.discard(filename)
        meta["blacklist"] = list(bl)
        _save_meta(image_folder, meta)
        return True
    except Exception as e:
        print(f"[StudyCompanion] mark_blacklist error: {e}")
        return False


def increment_view_count(image_folder: str, filename: str, delta: int = 1) -> None:
    try:
        meta = _load_meta(image_folder)
        vc = meta.get("view_counts", {})
        vc[filename] = int(vc.get(filename, 0)) + int(delta)
        meta["view_counts"] = vc
        _save_meta(image_folder, meta)
    except Exception as e:
        print(f"[StudyCompanion] increment_view_count error: {e}")


def increment_click_count(image_folder: str, filename: str, delta: int = 1) -> None:
    try:
        meta = _load_meta(image_folder)
        cc = meta.get("click_counts", {})
        cc[filename] = int(cc.get(filename, 0)) + int(delta)
        meta["click_counts"] = cc
        _save_meta(image_folder, meta)
    except Exception as e:
        print(f"[StudyCompanion] increment_click_count error: {e}")


def get_prioritized_files(image_folder: str, files: list[str]) -> list[str]:
    """Return files filtered (remove blacklisted) and with favorites prioritized.
    Favorites are moved to the front; within groups order is preserved.
    """
    try:
        meta = _load_meta(image_folder)
        fav = set(meta.get("favorites", []))
        bl = set(meta.get("blacklist", []))
        filtered = [f for f in files if f not in bl]
        favorites = [f for f in filtered if f in fav]
        others = [f for f in filtered if f not in fav]
        return favorites + others
    except Exception as e:
        print(f"[StudyCompanion] get_prioritized_files error: {e}")
        return files


def ensure_optimized_copy(image_folder: str, filename: str) -> str:
    """Return a relative path to an optimized copy (in cache) if created, otherwise return original filename.
    Attempts to create a scaled WebP copy (if Pillow available) to reduce size. Falls back to original.
    """
    try:
        src_path = os.path.join(image_folder, filename)
        cache_dir = _cache_path(image_folder)
        os.makedirs(cache_dir, exist_ok=True)
        # create safe cache name
        safe_name = filename.replace("/", "__") + ".webp"
        cache_path = os.path.join(cache_dir, safe_name)
        rel_cache = os.path.relpath(cache_path, image_folder).replace("\\", "/")
        if os.path.exists(cache_path):
            return rel_cache
        try:
            from PIL import Image as PILImage
        except Exception:
            return filename

        with PILImage.open(src_path) as im:
            # convert/resize: limit max dimension to 1600px
            max_dim = 1600
            w, h = im.size
            scale = min(1.0, float(max_dim) / max(w, h))
            if scale < 1.0:
                new_size = (int(w * scale), int(h * scale))
                im = im.resize(new_size, PILImage.LANCZOS)
            im.save(cache_path, format="WEBP", quality=75)
        return rel_cache
    except Exception as e:
        print(f"[StudyCompanion] ensure_optimized_copy error: {e}")
        return filename
