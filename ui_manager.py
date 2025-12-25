"""
UI components for StudyCompanion add-on.
Contains settings dialog and configuration interface.
"""

from aqt import mw
from aqt.qt import (
    QAction, QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QCheckBox, QLineEdit, QSpinBox, QPushButton, QComboBox,
    QDialogButtonBox, QLabel, QWidget, qconnect, QTabWidget,
)
from .config_manager import get_config, write_config, get_defaults
from .image_manager import open_images_folder, sanitize_folder_name
from .audio_manager import setup_audio_player
import os
import shutil
from aqt.qt import QFileDialog


class SettingsDialog(QDialog):
    """Settings dialog for StudyCompanion add-on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("StudyCompanion Settings")
        self.setMinimumWidth(480)

        cfg = get_config()

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

        # Images tab
        tab_images = QWidget()
        tabs.addTab(tab_images, "Images")
        img_layout = QVBoxLayout(tab_images)
        img_form = QFormLayout()
        img_layout.addLayout(img_form)

        # Website tab
        tab_website = QWidget()
        tabs.addTab(tab_website, "Website")
        website_layout = QVBoxLayout(tab_website)
        website_form = QFormLayout()
        website_layout.addLayout(website_form)

        # Audio tab
        tab_audio = QWidget()
        tabs.addTab(tab_audio, "Audio")
        audio_layout = QVBoxLayout(tab_audio)
        audio_form = QFormLayout()
        audio_layout.addLayout(audio_form)

        # enabled
        self.cb_enabled = QCheckBox("Enable add-on")
        self.cb_enabled.setChecked(bool(cfg.get("enabled", True)))
        gen_form.addRow(self.cb_enabled)

        # show_on_question / answer
        self.cb_q = QCheckBox("Show on Question side")
        self.cb_q.setChecked(bool(cfg.get("show_on_question", True)))
        gen_form.addRow(self.cb_q)

        self.cb_a = QCheckBox("Show on Answer side")
        self.cb_a.setChecked(bool(cfg.get("show_on_answer", True)))
        gen_form.addRow(self.cb_a)

        # folder_name + open button
        self.le_folder = QLineEdit(str(cfg.get("folder_name", "study_companion_images")))
        self.le_folder.setPlaceholderText("study_companion_images")

        btn_open = QPushButton("Open folder")
        qconnect(btn_open.clicked, self._on_open_folder)

        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.le_folder, 1)
        folder_layout.addWidget(btn_open)

        img_form.addRow("Image folder (inside collection.media)", folder_row)

        # max_width_percent
        self.sp_w = QSpinBox()
        self.sp_w.setRange(0, 100)
        self.sp_w.setValue(int(cfg.get("max_width_percent", 100) or 0))
        self.sp_w.setSuffix(" %")
        # option to use custom width/height values separately
        self.cb_use_custom_w = QCheckBox("Use custom max width from settings")
        self.cb_use_custom_w.setChecked(bool(cfg.get("use_custom_width", False)))
        img_form.addRow(self.cb_use_custom_w)
        self.cb_use_custom_h = QCheckBox("Use custom max height from settings")
        self.cb_use_custom_h.setChecked(bool(cfg.get("use_custom_height", False)))
        img_form.addRow(self.cb_use_custom_h)
        img_form.addRow("Max width", self.sp_w)

        # max_height (value + unit) with explanation for 'vh'
        self.sp_h = QSpinBox()
        self.sp_h.setRange(0, 200)
        self.sp_h.setValue(int(cfg.get("max_height_vh", 80) or 0))

        self.cb_h_unit = QComboBox()
        self.cb_h_unit.addItems(["vh", "%"])
        current_unit = str(cfg.get("max_height_unit", "vh")).lower()
        if current_unit not in ("vh", "%"):
            current_unit = "vh"
        self.cb_h_unit.setCurrentText(current_unit)
        # apply initial suffix
        self.sp_h.setSuffix(" vh" if current_unit == "vh" else " %")

        # update suffix when unit changes
        def _on_unit_changed(text):
            self.sp_h.setSuffix(" vh" if text == "vh" else " %")

        qconnect(self.cb_h_unit.currentTextChanged, _on_unit_changed)

        height_row = QWidget()
        height_layout = QHBoxLayout(height_row)
        height_layout.setContentsMargins(0, 0, 0, 0)
        height_layout.addWidget(self.sp_h, 1)
        height_layout.addWidget(self.cb_h_unit)
        img_form.addRow("Max height", height_row)

        # short explanation for 'vh'
        vh_explain = QLabel("Note: 'vh' = 1% of the viewport height (browser/window). Use '%' to size relative to the containing element.")
        vh_explain.setWordWrap(True)
        img_form.addRow(vh_explain)

        # images_to_show
        self.sp_count = QSpinBox()
        self.sp_count.setRange(1, 12)
        self.sp_count.setValue(int(cfg.get("images_to_show", 1) or 1))
        img_form.addRow("Number of images to show", self.sp_count)

        # avoid_repeat
        self.cb_avoid = QCheckBox("Don't repeat an image until all images have been shown")
        self.cb_avoid.setChecked(bool(cfg.get("avoid_repeat", True)))
        img_form.addRow(self.cb_avoid)


        # show motivational quotes
        self.cb_quotes = QCheckBox("Show motivational quote below image")
        self.cb_quotes.setChecked(bool(cfg.get("show_motivation_quotes", True)))
        img_form.addRow(self.cb_quotes)

        # orientation-aware single image display
        self.cb_auto_orient = QCheckBox("Auto-orient single image (portrait vs landscape)")
        self.cb_auto_orient.setChecked(bool(cfg.get("auto_orient_single_image", True)))
        img_form.addRow(self.cb_auto_orient)

        # click to open fullscreen
        self.cb_fullscreen = QCheckBox("Open image fullscreen on click (click to enlarge)")
        self.cb_fullscreen.setChecked(bool(cfg.get("click_open_fullscreen", True)))
        img_form.addRow(self.cb_fullscreen)

        # Website settings
        self.le_website = QLineEdit(str(cfg.get("website_url", "")))
        self.le_website.setPlaceholderText("https://example.com (optional)")
        website_form.addRow("Website URL (optional)", self.le_website)

        self.sp_site_h = QSpinBox()
        self.sp_site_h.setRange(20, 180)
        self.sp_site_h.setValue(int(cfg.get("website_height_vh", 50) or 50))
        self.sp_site_h.setSuffix(" vh")
        website_form.addRow("Website height", self.sp_site_h)

        # Website display mode
        self.cb_website_mode = QCheckBox("Mobile mode (website in grid with images)")
        current_mode = str(cfg.get("website_display_mode", "mobile")).lower()
        self.cb_website_mode.setChecked(current_mode == "mobile")
        website_form.addRow(self.cb_website_mode)

        self.sp_site_w = QSpinBox()
        self.sp_site_w.setRange(10, 100)
        self.sp_site_w.setValue(int(cfg.get("website_width_percent", 100) or 100))
        self.sp_site_w.setSuffix(" %")
        website_form.addRow("Website width (mobile mode)", self.sp_site_w)

        # Audio settings (separate tab)
        self.le_audio = QLineEdit(str(cfg.get("audio_file_path", "")))
        self.le_audio.setPlaceholderText("Path to mp3 file (optional)")
        btn_audio = QPushButton("Browse…")
        def _on_browse_audio():
            try:
                from aqt.qt import QFileDialog
                file, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select audio file",
                    "",
                    "Audio Files (*.mp3 *.wav *.flac *.aac *.ogg);;All Files (*)"
                )
                if file:
                    self.le_audio.setText(file)
            except Exception:
                pass
        qconnect(btn_audio.clicked, _on_browse_audio)

        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.le_audio, 1)
        audio_layout.addWidget(btn_audio)
        audio_form.addRow("Background audio (optional)", audio_row)

        # (Video tab removed)

        self.sp_audio_vol = QSpinBox()
        self.sp_audio_vol.setRange(0, 100)
        self.sp_audio_vol.setValue(int(cfg.get("audio_volume", 50) or 50))
        self.sp_audio_vol.setSuffix(" %")
        audio_form.addRow("Audio volume", self.sp_audio_vol)

        # (Behavior tab removed)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        btn_reset = QPushButton("Reset to defaults")
        buttons.addButton(btn_reset, QDialogButtonBox.ButtonRole.ResetRole)
        qconnect(btn_reset.clicked, self._on_reset)

        qconnect(buttons.accepted, self._on_ok)
        qconnect(buttons.rejected, self.reject)
        root.addWidget(buttons)

    def _on_open_folder(self):
        folder = sanitize_folder_name(self.le_folder.text())
        self.le_folder.setText(folder)
        open_images_folder(folder)

    def _on_ok(self):
        folder = sanitize_folder_name(self.le_folder.text())
        self.le_folder.setText(folder)

        new_cfg = {
            "enabled": bool(self.cb_enabled.isChecked()),
            "show_on_question": bool(self.cb_q.isChecked()),
            "show_on_answer": bool(self.cb_a.isChecked()),
            "folder_name": folder,
            "max_width_percent": int(self.sp_w.value()),
            "max_height_vh": int(self.sp_h.value()),
            "use_custom_width": bool(self.cb_use_custom_w.isChecked()),
            "use_custom_height": bool(self.cb_use_custom_h.isChecked()),
            "max_height_unit": str(self.cb_h_unit.currentText()),
            "website_url": str(self.le_website.text()).strip(),
            "website_height_vh": int(self.sp_site_h.value()),
            "website_display_mode": "mobile" if self.cb_website_mode.isChecked() else "desktop",
            "website_width_percent": int(self.sp_site_w.value()),
            "audio_file_path": str(self.le_audio.text()).strip(),
            "audio_volume": int(self.sp_audio_vol.value()),
            "images_to_show": int(self.sp_count.value()),
            "avoid_repeat": bool(self.cb_avoid.isChecked()),
            "show_motivation_quotes": bool(self.cb_quotes.isChecked()),
            "click_open_fullscreen": bool(self.cb_fullscreen.isChecked()),
            "auto_orient_single_image": bool(self.cb_auto_orient.isChecked()),
        }
        write_config(new_cfg)
        try:
            setup_audio_player(new_cfg)
        except Exception:
            pass
        self.accept()

    def _on_reset(self):
        d = get_defaults()

        self.cb_enabled.setChecked(bool(d.get("enabled", True)))
        self.cb_q.setChecked(bool(d.get("show_on_question", True)))
        self.cb_a.setChecked(bool(d.get("show_on_answer", True)))

        self.le_folder.setText(str(d.get("folder_name", "study_companion_images")))

        self.sp_w.setValue(int(d.get("max_width_percent", 80) or 0))
        self.sp_h.setValue(int(d.get("max_height_vh", 60) or 0))
        self.cb_h_unit.setCurrentText(str(d.get("max_height_unit", "vh")))
        # ensure suffix matches
        self.sp_h.setSuffix(" vh" if str(d.get("max_height_unit", "vh")) == "vh" else " %")

        self.le_website.setText(str(d.get("website_url", "")))
        self.sp_site_h.setValue(int(d.get("website_height_vh", 50) or 50))
        self.cb_website_mode.setChecked(str(d.get("website_display_mode", "mobile")).lower() == "mobile")
        self.sp_site_w.setValue(int(d.get("website_width_percent", 100) or 100))
        self.le_audio.setText(str(d.get("audio_file_path", "")))
        self.sp_audio_vol.setValue(int(d.get("audio_volume", 50) or 50))

        self.sp_count.setValue(int(d.get("images_to_show", 1) or 1))
        self.cb_avoid.setChecked(bool(d.get("avoid_repeat", True)))
        self.cb_quotes.setChecked(bool(d.get("show_motivation_quotes", True)))
        self.cb_fullscreen.setChecked(bool(d.get("click_open_fullscreen", True)))
        self.cb_auto_orient.setChecked(bool(d.get("auto_orient_single_image", True)))
        self.cb_use_custom_w.setChecked(bool(d.get("use_custom_width", False)))
        self.cb_use_custom_h.setChecked(bool(d.get("use_custom_height", False)))
        # video settings removed from UI


def open_settings_dialog(*args, **kwargs):
    """
    Open settings dialog. Expected from the Add-ons "Config" button.
    Accepts *args/**kwargs for different call styles.
    """
    parent = kwargs.get("parent", None)
    if parent is None and args:
        parent = args[0]
    parent = parent or mw

    dlg = SettingsDialog(parent=parent)
    dlg.exec()


def register_config_action() -> None:
    """
    Wire the Add-ons "Config" button to open the settings dialog.
    """
    try:
        mw.addonManager.setConfigAction(__name__.split(".")[0], open_settings_dialog)
        print("[StudyCompanion] Config action registered.")
    except Exception as e:
        print(f"[StudyCompanion] setConfigAction not available: {e}")
        try:
            menu = getattr(mw.form, "menuTools", None) or getattr(mw.form, "toolsMenu", None)
            if menu is not None:
                act = QAction("StudyCompanion Settings…", mw)
                qconnect(act.triggered, open_settings_dialog)
                menu.addAction(act)
        except Exception as e2:
            print(f"[StudyCompanion] Fallback menu failed: {e2}")


def register_tools_menu() -> None:
    """Add settings action to Tools menu."""
    try:
        menu = getattr(mw.form, "menuTools", None)
        if menu:
            action = QAction("StudyCompanion Settings…", mw)
            qconnect(action.triggered, open_settings_dialog)
            menu.addAction(action)
    except Exception as e:
        print(f"[StudyCompanion] Failed to add Tools menu item: {e}")
