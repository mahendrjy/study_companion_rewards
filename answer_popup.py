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
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QTimer,
    QPixmap,
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet(
            "QLabel { background: rgba(0,0,0,0.15); border-radius: 10px; padding: 8px; }"
        )
        root.addWidget(self._img)

    def show_image(self, image_path: str, duration_ms: int, cfg: dict) -> None:
        if not image_path:
            return
        if not os.path.exists(image_path):
            return

        self._current_image_path = image_path

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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._bg = QWidget()
        self._bg.setStyleSheet("background: rgba(0,0,0,0.90);")
        bg_layout = QVBoxLayout(self._bg)
        bg_layout.setContentsMargins(20, 20, 20, 20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = _ClickableLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)

        pix = QPixmap(image_path)
        if not pix.isNull():
            # Original resolution (no scaling). If larger than the screen, user can scroll.
            lbl.setPixmap(pix)

        c_layout.addWidget(lbl)
        scroll.setWidget(container)
        bg_layout.addWidget(scroll, 1)
        root.addWidget(self._bg, 1)

    def mousePressEvent(self, event):  # noqa: N802
        try:
            event.accept()
        except Exception:
            pass
        self.close()

    def closeEvent(self, event):  # noqa: N802
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)


_popup_singleton: _ImagePopup | None = None


def show_answer_popup(image_path: str, duration_ms: int, cfg: dict) -> None:
    global _popup_singleton
    if _popup_singleton is None:
        _popup_singleton = _ImagePopup()
    _popup_singleton.show_image(image_path, duration_ms, cfg)
