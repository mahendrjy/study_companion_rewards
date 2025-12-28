"""Qt popup for answer-submit reaction images.

This is intentionally independent of card HTML injection so it can show
reliably on answer submit.
"""

from __future__ import annotations

import os

from aqt import mw
from aqt.qt import (
    Qt,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QTimer,
    QPixmap,
    QSlider,
)


class _ImagePopup(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)  # type: ignore[attr-defined]

        self._zoom_overlay: _ZoomOverlay | None = None
        self._current_image_path: str | None = None
        self._delete_path: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.15); border-radius: 10px; padding: 8px; }"
        )
        root.addWidget(self._img)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 8, 10, 10)

        self._quote = QLabel("")
        self._quote.setWordWrap(True)
        self._quote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._quote.setStyleSheet("QLabel { color: rgba(255,255,255,0.92); font-style: italic; }")
        footer_layout.addWidget(self._quote, 1)

        self._delete_btn = QPushButton("🗑️ Delete")
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setStyleSheet(
            "QPushButton { background: rgba(255,107,107,0.20); color: rgba(255,255,255,0.95); border: 1px solid rgba(255,107,107,0.40); border-radius: 8px; padding: 6px 10px; }"
            "QPushButton:hover { background: rgba(255,107,107,0.28); }"
            "QPushButton:pressed { background: rgba(255,107,107,0.34); }"
        )
        self._delete_btn.clicked.connect(self._on_delete_clicked)  # type: ignore[attr-defined]
        footer_layout.addWidget(self._delete_btn, 0)

        root.addWidget(footer)

    def show_image(self, image_path: str, duration_ms: int, cfg: dict, quote_text: str | None = None, delete_path: str | None = None) -> None:
        if not image_path:
            return
        if not os.path.exists(image_path):
            return

        self._current_image_path = image_path
        self._delete_path = delete_path or image_path

        qt = (quote_text or "").strip()
        try:
            self._quote.setText(qt)
            self._quote.setVisible(bool(qt))
        except Exception:
            pass

        try:
            self._delete_btn.setVisible(bool(self._delete_path))
        except Exception:
            pass

        pix = QPixmap(image_path)
        if pix.isNull():
            return

        # Scale for a centered popup preview.
        # Default behavior: show at 1:1 if possible (based on image dimensions),
        # only shrinking to fit screen. Optional caps can be enabled via settings.
        screen = mw.screen() if mw else None
        if screen is not None:
            geo = screen.availableGeometry()
            screen_w = int(geo.width())
            screen_h = int(geo.height())
        else:
            screen_w, screen_h = 1400, 900

        # Screen safety caps
        hard_max_w = int(screen_w * 0.90)
        hard_max_h = int(screen_h * 0.85)

        max_w = hard_max_w
        max_h = hard_max_h

        # Optional custom caps
        try:
            if bool(cfg.get("answer_image_popup_use_custom_width", False)):
                pct = int(cfg.get("answer_image_popup_max_width_percent", 70) or 70)
                if pct < 5:
                    pct = 5
                if pct > 100:
                    pct = 100
                max_w = min(max_w, int(screen_w * pct / 100.0))
        except Exception:
            pass

        try:
            if bool(cfg.get("answer_image_popup_use_custom_height", False)):
                val = int(cfg.get("answer_image_popup_max_height_vh", 60) or 60)
                unit = str(cfg.get("answer_image_popup_max_height_unit", "vh")).lower()
                if val < 5:
                    val = 5
                if val > 200:
                    val = 200
                # Treat both 'vh' and '%' as percentage of available height
                max_h = min(max_h, int(screen_h * val / 100.0))
                if unit not in ("vh", "%"):
                    pass
        except Exception:
            pass

        # Keep original size if it fits inside caps; otherwise scale down.
        if pix.width() <= max_w and pix.height() <= max_h:
            self._img.setPixmap(pix)
        else:
            scaled = pix.scaled(
                max_w,
                max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img.setPixmap(scaled)
        self._img.setCursor(Qt.CursorShape.PointingHandCursor)

        # Size to content and center on main window
        self.adjustSize()
        self._center_on_main()
        self.show()
        self.raise_()

        try:
            self._timer.stop()
        except Exception:
            pass

        if duration_ms > 0:
            self._timer.start(int(duration_ms))

    def _on_delete_clicked(self) -> None:
        # Delete the underlying image file (best-effort), then close the popup.
        try:
            path = self._delete_path
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        try:
            if self._zoom_overlay and self._zoom_overlay.isVisible():
                self._zoom_overlay.close()
                self._zoom_overlay = None
        except Exception:
            pass
        try:
            self.hide()
        except Exception:
            pass

    def _center_on_main(self) -> None:
        try:
            if not mw:
                return
            g = mw.frameGeometry()
            my = self.frameGeometry()
            x = g.x() + int((g.width() - my.width()) / 2)
            y = g.y() + int((g.height() - my.height()) / 2)
            self.move(x, y)
        except Exception:
            pass

    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass
        self._toggle_zoom()

    def _toggle_zoom(self) -> None:
        # Clicking the popup should zoom and keep until clicked again.
        if self._zoom_overlay and self._zoom_overlay.isVisible():
            self._zoom_overlay.close()
            self._zoom_overlay = None
            self.hide()
            return

        # Pause auto-hide and open zoom overlay
        try:
            self._timer.stop()
        except Exception:
            pass

        path = self._current_image_path
        if not path:
            return

        self._zoom_overlay = _ZoomOverlay(path)
        self._zoom_overlay.closed.connect(self._on_zoom_closed)  # type: ignore[attr-defined]
        self._zoom_overlay.show()
        self._zoom_overlay.raise_()

    def _on_zoom_closed(self) -> None:
        # After closing zoom, hide the popup immediately
        self.hide()


class _ClickableLabel(QLabel):
    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass


class _CloseLabel(QLabel):
    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass
        try:
            w = self.window()
            if w is not None:
                w.close()
        except Exception:
            pass


class _ZoomImageLabel(QLabel):
    def __init__(self, overlay: "_ZoomOverlay"):
        super().__init__()
        self._overlay = overlay

    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass
        # Do not close or toggle on image clicks.
        try:
            w = self.window()
            if w is not None:
                w.close()
        except Exception:
            pass


class _ZoomOverlay(QWidget):
    """Fullscreen-ish overlay with original-resolution image (scrollable)."""

    from aqt.qt import pyqtSignal

    closed = pyqtSignal()

    def __init__(self, image_path: str):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        screen = mw.screen() if mw else None
        if screen is not None:
            geo = screen.availableGeometry()
            self.setGeometry(geo)

        self._pix = QPixmap(image_path)
        self._zoom_pct: int = 0  # 0 = fit, else percent of natural size
        self._scroll: QScrollArea | None = None
        self._img: QLabel | None = None
        self._slider: QSlider | None = None
        self._slider_label: QLabel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._bg = QWidget()
        self._bg.setStyleSheet("background: rgba(0,0,0,0.90);")
        bg_layout = QVBoxLayout(self._bg)
        bg_layout.setContentsMargins(20, 20, 20, 20)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 8)

        self._slider_label = QLabel("Fit")
        self._slider_label.setStyleSheet("QLabel { color: white; }")
        header_layout.addWidget(self._slider_label)

        slider = QSlider(Qt.Orientation.Horizontal)
        self._slider = slider
        slider.setRange(0, 300)
        slider.setSingleStep(25)
        slider.setPageStep(25)
        slider.setValue(0)
        slider.valueChanged.connect(self._on_zoom_slider_changed)  # type: ignore[attr-defined]
        header_layout.addWidget(slider, 1)

        header_layout.addStretch(1)
        bg_layout.addWidget(header, 0)

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = _ZoomImageLabel(self)
        self._img = lbl
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)

        c_layout.addWidget(lbl)
        scroll.setWidget(container)
        bg_layout.addWidget(scroll, 1)
        root.addWidget(self._bg, 1)

        self._apply_mode()


    def _on_zoom_slider_changed(self, value: int) -> None:
        try:
            self._zoom_pct = int(value)
        except Exception:
            self._zoom_pct = 0
        self._apply_mode()


    def _apply_mode(self) -> None:
        if not self._img:
            return
        if self._pix.isNull():
            return

        try:
            if self._zoom_pct <= 0:
                # Fit to the current scroll viewport (leaving a bit of margin)
                vp = self._scroll.viewport().size() if self._scroll else self.size()
                w = max(50, int(vp.width()) - 10)
                h = max(50, int(vp.height()) - 10)
                scaled = self._pix.scaled(
                    w,
                    h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._img.setPixmap(scaled)
                self._img.setCursor(Qt.CursorShape.PointingHandCursor)
                if self._slider_label is not None:
                    self._slider_label.setText("Fit")
                return

            z = float(self._zoom_pct) / 100.0
            w = max(1, int(self._pix.width() * z))
            h = max(1, int(self._pix.height() * z))
            scaled = self._pix.scaled(
                w,
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img.setPixmap(scaled)
            self._img.setCursor(Qt.CursorShape.PointingHandCursor)
            if self._slider_label is not None:
                self._slider_label.setText(f"{int(self._zoom_pct)}%")
        except Exception:
            # As a safe fallback, show original
            try:
                self._img.setPixmap(self._pix)
            except Exception:
                pass


    def resizeEvent(self, event):  # noqa: N802
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        # Keep fit mode responsive to window/viewport changes
        if self._zoom_pct == 0:
            try:
                self._apply_mode()
            except Exception:
                pass

    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass
        # Close on click anywhere (no ✕ button)
        try:
            self.close()
        except Exception:
            pass

    def closeEvent(self, event):  # noqa: N802
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)


_popup_singleton: _ImagePopup | None = None
_fullscreen_singleton: _ZoomOverlay | None = None


def show_answer_popup(image_path: str, duration_ms: int, cfg: dict) -> None:
    global _popup_singleton
    if _popup_singleton is None:
        _popup_singleton = _ImagePopup()
    _popup_singleton.show_image(image_path, duration_ms, cfg)


def show_answer_popup_with_quote(image_path: str, duration_ms: int, cfg: dict, quote_text: str, delete_path: str | None = None) -> None:
    """Backward-compatible helper for callers that want quote + delete support."""
    global _popup_singleton
    if _popup_singleton is None:
        _popup_singleton = _ImagePopup()
    _popup_singleton.show_image(image_path, duration_ms, cfg, quote_text=quote_text, delete_path=delete_path)


def show_fullscreen_image(image_path: str) -> None:
    """Show an image in a fullscreen-ish viewer with zoom slider and ✕ close."""
    global _fullscreen_singleton
    try:
        if _fullscreen_singleton is not None:
            try:
                _fullscreen_singleton.close()
            except Exception:
                pass
            _fullscreen_singleton = None

        if not image_path or not os.path.exists(image_path):
            return

        w = _ZoomOverlay(image_path)
        _fullscreen_singleton = w
        w.show()
        w.raise_()
    except Exception:
        return
