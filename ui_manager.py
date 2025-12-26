"""
UI components for StudyCompanion add-on.
Contains settings dialog and configuration interface (General, Audio, Quotes).
"""

from aqt import mw
from aqt.qt import (
    QAction, QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QCheckBox, QLineEdit, QSpinBox, QPushButton, QComboBox,
    QDialogButtonBox, QLabel, QWidget, qconnect, QTabWidget,
    QListWidget, QListWidgetItem, QFileDialog, QInputDialog, QScrollArea, QTextEdit,
    QSlider, Qt,
)
from .config_manager import get_config, write_config, get_defaults
from .image_manager import open_images_folder, sanitize_folder_name
from .audio_manager import setup_audio_player
from .quotes import get_all_quotes, save_quotes
import os
import re
from typing import List

try:
    from aqt import mw as _mw
except Exception:
    _mw = None

SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}


def _natural_key(text: str):
    parts = re.split(r"(\d+)", text)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


def _folder_audio_files(folder: str) -> List[str]:
    try:
        entries = os.listdir(folder)
    except Exception:
        return []
    files = [os.path.join(folder, f) for f in entries if os.path.splitext(f)[1].lower() in SUPPORTED_AUDIO_EXTS]
    files.sort(key=lambda p: _natural_key(os.path.basename(p)))
    return files


class SettingsDialog(QDialog):
    """Settings dialog for StudyCompanion add-on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("StudyCompanion Settings")
        self.setMinimumWidth(720)
        self.resize(760, 620)

        self.cfg = get_config()

        root = QVBoxLayout(self)

        title = QLabel("<h2>StudyCompanion</h2>")
        title.setWordWrap(True)
        root.addWidget(title)

        desc = QLabel(
            "Settings are saved to config.json.<br>"
            "Changes apply next time a card is shown. Use tabs to find related options quickly."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # General tab
        tab_general = QWidget()
        tabs.addTab(tab_general, "General")
        gen_layout = QVBoxLayout(tab_general)
        gen_form = QFormLayout()
        gen_layout.addLayout(gen_form)

        self.cb_enabled = QCheckBox("Enable add-on")
        self.cb_enabled.setChecked(bool(self.cfg.get("enabled", True)))
        gen_form.addRow(self.cb_enabled)

        self.cb_q = QCheckBox("Show on Question side")
        self.cb_q.setChecked(bool(self.cfg.get("show_on_question", True)))
        gen_form.addRow(self.cb_q)

        self.cb_a = QCheckBox("Show on Answer side")
        self.cb_a.setChecked(bool(self.cfg.get("show_on_answer", True)))
        gen_form.addRow(self.cb_a)

        # Images tab
        tab_images = QWidget()
        tabs.addTab(tab_images, "Images")
        img_layout = QVBoxLayout(tab_images)
        img_form = QFormLayout()
        img_layout.addLayout(img_form)

        self.le_folder = QLineEdit(str(self.cfg.get("folder_name", "study_companion_images")))
        self.le_folder.setPlaceholderText("study_companion_images")
        btn_pick_img_folder = QPushButton("Select folder…")
        btn_open = QPushButton("Open folder")
        qconnect(btn_pick_img_folder.clicked, self._on_pick_image_folder)
        qconnect(btn_open.clicked, self._on_open_folder)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.le_folder, 1)
        folder_layout.addWidget(btn_pick_img_folder)
        folder_layout.addWidget(btn_open)
        img_form.addRow("Image folder (inside collection.media)", folder_row)

        self.sp_count = QSpinBox()
        self.sp_count.setRange(1, 12)
        self.sp_count.setValue(int(self.cfg.get("images_to_show", 1) or 1))
        img_form.addRow("Number of images to show", self.sp_count)

        self.cb_avoid = QCheckBox("Don't repeat an image until all images have been shown")
        self.cb_avoid.setChecked(bool(self.cfg.get("avoid_repeat", True)))
        img_form.addRow(self.cb_avoid)

        self.cb_quotes = QCheckBox("Show motivational quote below image")
        self.cb_quotes.setChecked(bool(self.cfg.get("show_motivation_quotes", True)))
        img_form.addRow(self.cb_quotes)

        self.cb_auto_orient = QCheckBox("Auto-orient single image (portrait vs landscape)")
        self.cb_auto_orient.setChecked(bool(self.cfg.get("auto_orient_single_image", True)))
        img_form.addRow(self.cb_auto_orient)

        self.cb_fullscreen = QCheckBox("Open image fullscreen on click (click to enlarge)")
        self.cb_fullscreen.setChecked(bool(self.cfg.get("click_open_fullscreen", True)))
        img_form.addRow(self.cb_fullscreen)

        self.cb_use_custom_w = QCheckBox("Use custom max width from settings")
        self.cb_use_custom_w.setChecked(bool(self.cfg.get("use_custom_width", False)))
        img_form.addRow(self.cb_use_custom_w)

        self.sp_w = QSpinBox()
        self.sp_w.setRange(0, 100)
        self.sp_w.setValue(int(self.cfg.get("max_width_percent", 80) or 0))
        self.sp_w.setSuffix(" %")
        img_form.addRow("Max width", self.sp_w)

        self.cb_use_custom_h = QCheckBox("Use custom max height from settings")
        self.cb_use_custom_h.setChecked(bool(self.cfg.get("use_custom_height", False)))
        img_form.addRow(self.cb_use_custom_h)

        self.sp_h = QSpinBox()
        self.sp_h.setRange(0, 200)
        self.sp_h.setValue(int(self.cfg.get("max_height_vh", 60) or 0))

        self.cb_h_unit = QComboBox()
        self.cb_h_unit.addItems(["vh", "%"])
        current_unit = str(self.cfg.get("max_height_unit", "vh")).lower()
        if current_unit not in ("vh", "%"):
            current_unit = "vh"
        self.cb_h_unit.setCurrentText(current_unit)
        self.sp_h.setSuffix(" vh" if current_unit == "vh" else " %")

        def _on_unit_changed(text: str):
            self.sp_h.setSuffix(" vh" if text == "vh" else " %")

        qconnect(self.cb_h_unit.currentTextChanged, _on_unit_changed)

        height_row = QWidget()
        height_layout = QHBoxLayout(height_row)
        height_layout.setContentsMargins(0, 0, 0, 0)
        height_layout.addWidget(self.sp_h, 1)
        height_layout.addWidget(self.cb_h_unit)
        img_form.addRow("Max height", height_row)

        self.sp_img_cols = QSpinBox()
        self.sp_img_cols.setRange(1, 6)
        self.sp_img_cols.setValue(int(self.cfg.get("images_max_columns", 3) or 3))
        img_form.addRow("Max columns (grid)", self.sp_img_cols)

        self.sp_img_gap = QSpinBox()
        self.sp_img_gap.setRange(0, 48)
        self.sp_img_gap.setValue(int(self.cfg.get("images_grid_gap_px", 8) or 8))
        self.sp_img_gap.setSuffix(" px")
        img_form.addRow("Grid gap", self.sp_img_gap)

        self.sp_img_radius = QSpinBox()
        self.sp_img_radius.setRange(0, 48)
        self.sp_img_radius.setValue(int(self.cfg.get("image_corner_radius_px", 8) or 8))
        self.sp_img_radius.setSuffix(" px")
        img_form.addRow("Image corner radius", self.sp_img_radius)

        # Website tab
        tab_website = QWidget()
        tabs.addTab(tab_website, "Website")
        website_layout = QVBoxLayout(tab_website)
        website_form = QFormLayout()
        website_layout.addLayout(website_form)

        self.le_website = QLineEdit(str(self.cfg.get("website_url", "")))
        self.le_website.setPlaceholderText("https://example.com (optional)")
        website_form.addRow("Website URL (optional)", self.le_website)

        self.sp_site_h = QSpinBox()
        self.sp_site_h.setRange(20, 180)
        self.sp_site_h.setValue(int(self.cfg.get("website_height_vh", 80) or 80))
        self.sp_site_h.setSuffix(" vh")
        website_form.addRow("Website height", self.sp_site_h)

        self.cb_website_mode = QCheckBox("Mobile mode (website in grid with images)")
        current_mode = str(self.cfg.get("website_display_mode", "mobile")).lower()
        self.cb_website_mode.setChecked(current_mode == "mobile")
        website_form.addRow(self.cb_website_mode)

        self.sp_site_w = QSpinBox()
        self.sp_site_w.setRange(10, 100)
        self.sp_site_w.setValue(int(self.cfg.get("website_width_percent", 100) or 100))
        self.sp_site_w.setSuffix(" %")
        website_form.addRow("Website width (mobile mode)", self.sp_site_w)

        self.sp_site_radius = QSpinBox()
        self.sp_site_radius.setRange(0, 48)
        self.sp_site_radius.setValue(int(self.cfg.get("website_border_radius_px", 4) or 4))
        self.sp_site_radius.setSuffix(" px")
        website_form.addRow("Website corner radius", self.sp_site_radius)

        # Audio tab
        tab_audio = QWidget()
        tabs.addTab(tab_audio, "Audio")

        # Audio can get tall; keep it usable by always allowing scroll.
        tab_audio_layout = QVBoxLayout(tab_audio)
        tab_audio_layout.setContentsMargins(0, 0, 0, 0)
        tab_audio_layout.setSpacing(0)

        audio_scroll = QScrollArea()
        audio_scroll.setWidgetResizable(True)
        tab_audio_layout.addWidget(audio_scroll)

        audio_container = QWidget()
        audio_scroll.setWidget(audio_container)

        audio_layout = QVBoxLayout(audio_container)
        audio_form = QFormLayout()
        audio_layout.addLayout(audio_form)

        # Volume
        self.sl_volume = QSlider(Qt.Orientation.Horizontal)
        self.sl_volume.setRange(0, 100)
        self.sl_volume.setValue(int(self.cfg.get("audio_volume", 50) or 50))
        self.lbl_volume = QLabel(f"{self.sl_volume.value()} %")

        qconnect(self.sl_volume.valueChanged, lambda v: self.lbl_volume.setText(f"{int(v)} %"))

        vol_row = QWidget()
        vol_row_l = QHBoxLayout(vol_row)
        vol_row_l.setContentsMargins(0, 0, 0, 0)
        vol_row_l.addWidget(self.sl_volume, 1)
        vol_row_l.addWidget(self.lbl_volume)
        audio_form.addRow("Audio volume", vol_row)

        self.le_audio_source = QLineEdit()
        self.btn_audio_folder = QPushButton("Folder…")
        self.cb_audio_loop = QCheckBox("Loop all day")

        src_row = QWidget()
        src_row_l = QHBoxLayout(src_row)
        src_row_l.setContentsMargins(0, 0, 0, 0)
        src_row_l.addWidget(self.le_audio_source, 1)
        src_row_l.addWidget(self.btn_audio_folder)
        audio_form.addRow("Playlist source", src_row)
        audio_form.addRow("Loop", self.cb_audio_loop)

        qconnect(self.btn_audio_folder.clicked, self._browse_audio_folder)

        # Quotes tab
        tab_quotes = QWidget()
        tabs.addTab(tab_quotes, "Quotes")
        quotes_layout = QVBoxLayout(tab_quotes)

        quotes_style_row = QWidget()
        quotes_style_l = QHBoxLayout(quotes_style_row)
        quotes_style_l.setContentsMargins(0, 0, 0, 0)

        self.sp_quote_size = QSpinBox()
        self.sp_quote_size.setRange(6, 20)
        self.sp_quote_size.setValue(int(round(float(self.cfg.get("quotes_font_size_em", 0.9) or 0.9) * 10)))
        self.sp_quote_size.setSuffix(" (0.1em)")

        self.cb_quote_italic = QCheckBox("Italic")
        self.cb_quote_italic.setChecked(bool(self.cfg.get("quotes_italic", True)))

        self.cb_quote_align = QComboBox()
        self.cb_quote_align.addItem("Left", "left")
        self.cb_quote_align.addItem("Center", "center")
        align = str(self.cfg.get("quotes_align", "left") or "left")
        for i in range(self.cb_quote_align.count()):
            if self.cb_quote_align.itemData(i) == align:
                self.cb_quote_align.setCurrentIndex(i)
                break

        quotes_style_l.addWidget(QLabel("Quote style:"))
        quotes_style_l.addWidget(QLabel("Size"))
        quotes_style_l.addWidget(self.sp_quote_size)
        quotes_style_l.addWidget(self.cb_quote_italic)
        quotes_style_l.addWidget(QLabel("Align"))
        quotes_style_l.addWidget(self.cb_quote_align)
        quotes_style_l.addStretch(1)
        quotes_layout.addWidget(quotes_style_row)

        # Quotes editor (one quote per line)
        self.te_quotes = QTextEdit()
        self.te_quotes.setPlaceholderText("One quote per line. You can paste a full file here.")
        quotes_layout.addWidget(self.te_quotes, 1)

        q_btn_row = QHBoxLayout()
        btn_save_quotes = QPushButton("Save Quotes")
        btn_reload_quotes = QPushButton("Reload From File")
        q_btn_row.addWidget(btn_save_quotes)
        q_btn_row.addWidget(btn_reload_quotes)
        quotes_layout.addLayout(q_btn_row)

        qconnect(btn_save_quotes.clicked, lambda: self._on_save_quotes())
        qconnect(btn_reload_quotes.clicked, lambda: self._on_reload_quotes())

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btn_reset = QPushButton("Reset to defaults")
        btns.addButton(btn_reset, QDialogButtonBox.ButtonRole.ResetRole)
        qconnect(btn_reset.clicked, self._on_reset)
        qconnect(btns.accepted, self._on_save)
        qconnect(btns.rejected, self.reject)
        root.addWidget(btns)

        # Initialize
        self._load_config_to_ui()
        self._load_quotes_ui()

    def _load_config_to_ui(self):
        cfg = self.cfg
        self.cb_enabled.setChecked(bool(cfg.get("enabled", True)))
        self.cb_q.setChecked(bool(cfg.get("show_on_question", True)))
        self.cb_a.setChecked(bool(cfg.get("show_on_answer", True)))

        self.le_folder.setText(str(cfg.get("folder_name", "study_companion_images")))
        self.sp_w.setValue(int(cfg.get("max_width_percent", 80) or 0))
        self.sp_h.setValue(int(cfg.get("max_height_vh", 60) or 0))
        unit = str(cfg.get("max_height_unit", "vh")).lower()
        if unit not in ("vh", "%"):
            unit = "vh"
        self.cb_h_unit.setCurrentText(unit)
        self.cb_use_custom_w.setChecked(bool(cfg.get("use_custom_width", False)))
        self.cb_use_custom_h.setChecked(bool(cfg.get("use_custom_height", False)))
        self.sp_count.setValue(int(cfg.get("images_to_show", 1) or 1))
        self.cb_avoid.setChecked(bool(cfg.get("avoid_repeat", True)))
        self.cb_quotes.setChecked(bool(cfg.get("show_motivation_quotes", True)))
        self.cb_auto_orient.setChecked(bool(cfg.get("auto_orient_single_image", True)))
        self.cb_fullscreen.setChecked(bool(cfg.get("click_open_fullscreen", True)))

        self.le_website.setText(str(cfg.get("website_url", "")))
        self.sp_site_h.setValue(int(cfg.get("website_height_vh", 80) or 80))
        self.cb_website_mode.setChecked(str(cfg.get("website_display_mode", "mobile")).lower() == "mobile")
        self.sp_site_w.setValue(int(cfg.get("website_width_percent", 100) or 100))

        self.sl_volume.setValue(int(cfg.get("audio_volume", 50) or 50))
        self.lbl_volume.setText(f"{int(self.sl_volume.value())} %")

        val = str(cfg.get("audio_playlist_1_path", "") or "").strip()
        if not val:
            val = str(cfg.get("audio_file_path", "") or "").strip()
        self.le_audio_source.setText(val)
        self.cb_audio_loop.setChecked(bool(cfg.get("audio_loop_1", False) or cfg.get("audio_loop_playlist", False)))

    def _browse_audio_folder(self) -> None:
        try:
            folder = QFileDialog.getExistingDirectory(
                self,
                "Select folder for playlist",
                os.path.expanduser("~"),
            )
            if folder:
                self.le_audio_source.setText(folder)
        except Exception:
            pass

    def _on_save(self):
        folder = sanitize_folder_name(self.le_folder.text())
        self.le_folder.setText(folder)

        cfg = self.cfg.copy()
        cfg.update(
            {
                "enabled": bool(self.cb_enabled.isChecked()),
                "show_on_question": bool(self.cb_q.isChecked()),
                "show_on_answer": bool(self.cb_a.isChecked()),
                "folder_name": folder,
                "images_to_show": int(self.sp_count.value()),
                "avoid_repeat": bool(self.cb_avoid.isChecked()),
                "show_motivation_quotes": bool(self.cb_quotes.isChecked()),
                "auto_orient_single_image": bool(self.cb_auto_orient.isChecked()),
                "click_open_fullscreen": bool(self.cb_fullscreen.isChecked()),
                "use_custom_width": bool(self.cb_use_custom_w.isChecked()),
                "use_custom_height": bool(self.cb_use_custom_h.isChecked()),
                "max_width_percent": int(self.sp_w.value()),
                "max_height_vh": int(self.sp_h.value()),
                "max_height_unit": str(self.cb_h_unit.currentText()),
                "images_max_columns": int(self.sp_img_cols.value()),
                "images_grid_gap_px": int(self.sp_img_gap.value()),
                "image_corner_radius_px": int(self.sp_img_radius.value()),
                "website_url": str(self.le_website.text()).strip(),
                "website_height_vh": int(self.sp_site_h.value()),
                "website_display_mode": "mobile" if self.cb_website_mode.isChecked() else "desktop",
                "website_width_percent": int(self.sp_site_w.value()),
                "website_border_radius_px": int(self.sp_site_radius.value()),
                "quotes_font_size_em": float(self.sp_quote_size.value()) / 10.0,
                "quotes_italic": bool(self.cb_quote_italic.isChecked()),
                "quotes_align": str(self.cb_quote_align.currentData() or "left"),
                "audio_volume": int(self.sl_volume.value()),
            }
        )

        cfg["audio_playlist_1_path"] = str(self.le_audio_source.text() or "").strip()
        cfg["audio_loop_1"] = bool(self.cb_audio_loop.isChecked())

        # Explicitly disable/clear removed Playlist 2 + schedule/cycle settings if they exist.
        cfg["audio_playlist_2_path"] = ""
        cfg["audio_loop_2"] = False
        cfg["audio_program_enabled"] = False
        cfg["audio_cycle_enabled"] = False
        cfg["audio_cycle_day"] = 1
        cfg["audio_cycle_count"] = 0
        cfg["audio_cycle_last_date"] = ""

        write_config(cfg)
        try:
            setup_audio_player(cfg)
        except Exception:
            pass
        self.accept()

    def _on_pick_image_folder(self) -> None:
        try:
            col = getattr(_mw, "col", None)
            if not col:
                return
            media_dir = col.media.dir()
            start = media_dir
            folder = QFileDialog.getExistingDirectory(self, "Select image folder inside collection.media", start)
            if not folder:
                return

            # Enforce selection inside collection.media
            media_dir_real = os.path.realpath(media_dir)
            folder_real = os.path.realpath(folder)
            if not folder_real.startswith(media_dir_real + os.sep) and folder_real != media_dir_real:
                return

            rel = os.path.relpath(folder_real, media_dir_real)
            rel = rel.replace("\\", "/")
            rel = sanitize_folder_name(rel)
            self.le_folder.setText(rel)
        except Exception:
            pass

    def _on_open_folder(self) -> None:
        folder = sanitize_folder_name(self.le_folder.text())
        self.le_folder.setText(folder)
        open_images_folder(folder)

    def _on_reset(self) -> None:
        d = get_defaults()
        # General
        self.cb_enabled.setChecked(bool(d.get("enabled", True)))
        self.cb_q.setChecked(bool(d.get("show_on_question", True)))
        self.cb_a.setChecked(bool(d.get("show_on_answer", True)))

        # Images
        self.le_folder.setText(str(d.get("folder_name", "study_companion_images")))
        self.sp_count.setValue(int(d.get("images_to_show", 1) or 1))
        self.cb_avoid.setChecked(bool(d.get("avoid_repeat", True)))
        self.cb_quotes.setChecked(bool(d.get("show_motivation_quotes", True)))
        self.cb_auto_orient.setChecked(bool(d.get("auto_orient_single_image", True)))
        self.cb_fullscreen.setChecked(bool(d.get("click_open_fullscreen", True)))
        self.cb_use_custom_w.setChecked(bool(d.get("use_custom_width", False)))
        self.cb_use_custom_h.setChecked(bool(d.get("use_custom_height", False)))
        self.sp_w.setValue(int(d.get("max_width_percent", 80) or 0))
        self.sp_h.setValue(int(d.get("max_height_vh", 60) or 0))
        unit = str(d.get("max_height_unit", "vh")).lower()
        if unit not in ("vh", "%"):
            unit = "vh"
        self.cb_h_unit.setCurrentText(unit)
        self.sp_img_cols.setValue(int(d.get("images_max_columns", 3) or 3))
        self.sp_img_gap.setValue(int(d.get("images_grid_gap_px", 8) or 8))
        self.sp_img_radius.setValue(int(d.get("image_corner_radius_px", 8) or 8))

        # Website
        self.le_website.setText(str(d.get("website_url", "")))
        self.sp_site_h.setValue(int(d.get("website_height_vh", 80) or 80))
        self.cb_website_mode.setChecked(str(d.get("website_display_mode", "mobile")).lower() == "mobile")
        self.sp_site_w.setValue(int(d.get("website_width_percent", 100) or 100))
        self.sp_site_radius.setValue(int(d.get("website_border_radius_px", 4) or 4))

        # Quotes style
        self.sp_quote_size.setValue(int(round(float(d.get("quotes_font_size_em", 0.9) or 0.9) * 10)))
        self.cb_quote_italic.setChecked(bool(d.get("quotes_italic", True)))
        align = str(d.get("quotes_align", "left") or "left")
        for i in range(self.cb_quote_align.count()):
            if self.cb_quote_align.itemData(i) == align:
                self.cb_quote_align.setCurrentIndex(i)
                break

        # Audio
        self.sl_volume.setValue(int(d.get("audio_volume", 50) or 50))
        self.lbl_volume.setText(f"{int(self.sl_volume.value())} %")
        self.le_audio_source.setText("")
        self.cb_audio_loop.setChecked(bool(d.get("audio_loop_1", False) or d.get("audio_loop_playlist", False)))

    # Quotes UI handlers
    def _load_quotes_ui(self):
        try:
            quotes = get_all_quotes() or []
            self.te_quotes.setPlainText("\n".join(quotes))
        except Exception:
            pass

    def _on_save_quotes(self):
        raw = str(self.te_quotes.toPlainText() or "")
        quotes = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        try:
            save_quotes(quotes)
        except Exception:
            pass

    def _on_reload_quotes(self):
        self._load_quotes_ui()


def show_settings():
    dlg = SettingsDialog(mw)
    # Qt6/PyQt6 removed exec_() in favor of exec().
    exec_fn = getattr(dlg, "exec", None) or getattr(dlg, "exec_", None)
    if exec_fn is not None:
        exec_fn()


def register_config_action() -> None:
    try:
        mw.addonManager.setConfigAction(__name__.split(".")[0], show_settings)
    except Exception:
        try:
            menu = getattr(mw.form, "menuTools", None) or getattr(mw.form, "toolsMenu", None)
            if menu is not None:
                act = QAction("StudyCompanion Settings…", mw)
                qconnect(act.triggered, show_settings)
                menu.addAction(act)
        except Exception:
            pass


def register_tools_menu() -> None:
    try:
        menu = getattr(mw.form, "menuTools", None)
        if menu:
            action = QAction("StudyCompanion Settings…", mw)
            qconnect(action.triggered, show_settings)
            menu.addAction(action)
    except Exception:
        pass


register_config_action()
register_tools_menu()
