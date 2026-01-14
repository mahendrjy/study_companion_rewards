"""
Playlist Calendar Widget for StudyCompanion add-on.
Displays a monthly calendar showing which playlists are active on each day.

Features:
- Shows 21-day study cycles with 5-day breaks
- Hover over any day to see track names that play
- Color-coded days for playlist types and break days
- Shows current and future cycles
- Music player with progress bar, play/pause, seek

Shows as a popup dialog accessible from Tools menu (doesn't interfere with home screen).
Uses dark-mode compatible colors.
"""

from datetime import datetime, date, timedelta
import calendar
from typing import List, Tuple, Optional, Dict

from aqt import mw
from aqt.qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QFrame, Qt, QSizePolicy, QDialog, QAction, qconnect,
    QTimer
)

from .audio_manager import (
    get_playlists_for_day, get_current_day, get_effective_day,
    get_cycle_info, get_tracks_for_day, get_current_playback_info
)
from .config_manager import get_config


# Dark mode compatible colors (more visible, vibrant backgrounds)
COLOR_P1_ONLY = "#2E5C8A"      # Bright blue - days with P1 only
COLOR_P1_P2 = "#2E7D4A"        # Bright green - P1 + P2 days
COLOR_P1_P3 = "#8B5A2B"        # Bright brown/orange - P1 + P3 days
COLOR_BREAK = "#5C5C5C"        # Medium gray - break days
COLOR_BEFORE_START = "#3A3A3A" # Darker gray - before cycle starts
COLOR_CURRENT_DAY = "#FFD700"  # Gold border for current day
COLOR_TEXT = "#FFFFFF"         # White text
COLOR_TEXT_DIM = "#D0D0D0"     # Less dimmed text for better visibility
COLOR_HEADER = "#E0E0E0"       # Light gray for header


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    if seconds < 0:
        seconds = 0
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


class MusicProgressWidget(QFrame):
    """Simple widget showing current track progress for testing resume."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            MusicProgressWidget {
                background-color: #1A1A1A;
                border: 1px solid #444;
                border-radius: 6px;
            }
        """)
        
        self._init_ui()
        
        # Timer for updating progress
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_display)
        self.update_timer.start(500)
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        
        # Track info line
        self.track_label = QLabel("No track playing")
        self.track_label.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 11px;")
        self.track_label.setWordWrap(True)
        layout.addWidget(self.track_label)
        
        # Progress info line
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 10px;")
        layout.addWidget(self.progress_label)
        
        self._update_display()
    
    def _update_display(self):
        """Update the display with current playback info."""
        info = get_current_playback_info()
        
        if info["playlist_id"] == 0 or not info["track_name"]:
            self.track_label.setText("🔇 No track playing")
            self.progress_label.setText("")
            return
        
        # Track name (truncate if too long)
        track_name = info["track_name"]
        if len(track_name) > 40:
            track_name = track_name[:37] + "..."
        
        status = "▶" if info["playing"] else "⏸" if info["paused"] else "⏹"
        loop_text = " 🔁" if info["loops"] else ""
        
        self.track_label.setText(f"{status} P{info['playlist_id']}{loop_text}: {track_name}")
        
        # Progress: current / total
        self.progress_label.setText(
            f"⏱ {_format_time(info['position'])} / {_format_time(info['duration'])} • "
            f"Track {info['track_index'] + 1}/{info['track_count']}"
        )


class DayCell(QFrame):
    """Individual day cell in the calendar."""
    
    def __init__(self, day: int, month: int, year: int, is_current: bool = False, 
                 cycle_info: Dict = None, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.day = day
        self.month = month
        self.year = year
        self.is_current = is_current
        self.cycle_info = cycle_info or {}
        self.cfg = cfg or get_config()
        
        self.setFrameShape(QFrame.Shape.Box)
        self.setMinimumSize(70, 52)  # Wider and taller cells
        self.setMaximumSize(90, 65)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(0)
        
        # Row 1: Day number label
        self.day_label = QLabel(str(day))
        self.day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.day_label)
        
        # Row 2: Cycle day (D1, D2, etc.)
        self.cycle_label = QLabel("")
        self.cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cycle_label)
        
        # Row 3: Playlists (P2+P1, P1, etc.)
        self.playlist_label = QLabel("")
        self.playlist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.playlist_label)
        
        self._update_style()
    
    def _update_style(self):
        """Update cell style based on cycle info and playlists."""
        is_break = self.cycle_info.get("is_break", False)
        before_start = self.cycle_info.get("before_start", False)
        study_day = self.cycle_info.get("study_day", self.day)
        cycle_day = self.cycle_info.get("cycle_day", self.day)
        no_cycle = self.cycle_info.get("no_cycle_configured", False)
        
        cycle_text = ""
        playlist_text = ""
        
        if before_start:
            bg_color = COLOR_BEFORE_START
            cycle_text = "—"
            playlist_text = ""
        elif is_break:
            bg_color = COLOR_BREAK
            study_days = int(self.cfg.get("audio_cycle_study_days", 21) or 21)
            break_day = cycle_day - study_days
            cycle_text = f"B{break_day}"
            playlist_text = "Break"
        else:
            # Study day - get playlists
            playlists = get_playlists_for_day(study_day)
            
            bg_color = COLOR_P1_ONLY  # default
            cycle_text = f"D{cycle_day}"
            
            # Build playlist string like "P2+P1" or "P1"
            if playlists:
                playlist_names = [f"P{pid}" for pid, _ in playlists]
                playlist_text = '+'.join(playlist_names)
            else:
                playlist_text = "—"
            
            if len(playlists) > 1:
                for pid, loops in playlists:
                    if pid == 2:
                        bg_color = COLOR_P1_P2
                        break
                    elif pid == 3:
                        bg_color = COLOR_P1_P3
                        break
            elif len(playlists) == 0:
                bg_color = COLOR_BREAK
                cycle_text = "—"
                playlist_text = ""
        
        # Current day gets a gold/yellow background tint
        if self.is_current:
            bg_color = "#4A4000"  # Dark gold/yellow tint
        
        font_weight = "bold" if self.is_current else "normal"
        border = "1px solid #555"
        
        self.setStyleSheet(f"""
            DayCell {{
                background-color: {bg_color};
                border: {border};
                border-radius: 4px;
            }}
        """)
        
        # Current day text in gold color
        day_color = COLOR_CURRENT_DAY if self.is_current else COLOR_TEXT
        self.day_label.setStyleSheet(f"font-weight: {font_weight}; font-size: 13px; color: {day_color};")
        self.cycle_label.setStyleSheet(f"font-size: 10px; color: {COLOR_TEXT_DIM};")
        self.cycle_label.setText(cycle_text)
        self.playlist_label.setStyleSheet(f"font-size: 10px; color: {COLOR_TEXT}; font-weight: bold;")
        self.playlist_label.setText(playlist_text)
    
    def set_tooltip(self):
        """Set detailed tooltip showing tracks that play on this day."""
        is_break = self.cycle_info.get("is_break", False)
        before_start = self.cycle_info.get("before_start", False)
        study_day = self.cycle_info.get("study_day", self.day)
        cycle_day = self.cycle_info.get("cycle_day", self.day)
        cycle_num = self.cycle_info.get("cycle_number", 1)
        
        lines = [f"📅 {self.month}/{self.day}/{self.year}"]
        lines.append(f"Cycle {cycle_num}, Day {cycle_day}")
        lines.append("")
        
        if before_start:
            lines.append("⏳ Before cycle start")
            lines.append("No audio scheduled")
        elif is_break:
            study_days = int(self.cfg.get("audio_cycle_study_days", 21) or 21)
            break_day = cycle_day - study_days
            break_days = int(self.cfg.get("audio_cycle_break_days", 5) or 5)
            lines.append(f"🎉 BREAK DAY {break_day}/{break_days}")
            lines.append("Enjoy your rest!")
        else:
            lines.append(f"📚 Study Day {study_day}")
            lines.append("")
            
            # Get playlists and tracks for this study day
            playlists = get_playlists_for_day(study_day)
            tracks = get_tracks_for_day(self.cfg, study_day)
            
            for pid, loops in playlists:
                loop_text = " 🔁" if loops else ""
                lines.append(f"🎵 Playlist {pid}{loop_text}:")
                
                track_list = tracks.get(pid, [])
                if track_list:
                    for i, track in enumerate(track_list[:10], 1):  # Show max 10 tracks
                        # Truncate long names
                        display_name = track if len(track) <= 40 else track[:37] + "..."
                        lines.append(f"   {i}. {display_name}")
                    if len(track_list) > 10:
                        lines.append(f"   ... and {len(track_list) - 10} more")
                else:
                    lines.append("   (no files configured)")
        
        self.setToolTip("\n".join(lines))


class PlaylistCalendarWidget(QWidget):
    """Monthly calendar widget showing playlist schedule with cycle tracking."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_month = datetime.now().month
        self.current_year = datetime.now().year
        self.display_month = self.current_month
        self.display_year = self.current_year
        
        self._init_ui()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(4)
        
        # Header with title
        title = QLabel("🎵 <b>Playlist Calendar</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 16px;")
        main_layout.addWidget(title)
        
        # Month navigation
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(8)
        
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setMaximumWidth(40)
        self.btn_prev.clicked.connect(self._prev_month)
        nav_layout.addWidget(self.btn_prev)
        
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {COLOR_TEXT};")
        nav_layout.addWidget(self.month_label, 1)
        
        self.btn_next = QPushButton("▶")
        self.btn_next.setMaximumWidth(40)
        self.btn_next.clicked.connect(self._next_month)
        nav_layout.addWidget(self.btn_next)
        
        main_layout.addLayout(nav_layout)
        
        # Legend (dark mode friendly)
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(8)
        legend_layout.addStretch()
        
        for color, text in [
            (COLOR_P1_ONLY, "P1"),
            (COLOR_P1_P2, "P2→P1"),
            (COLOR_P1_P3, "P3→P1"),
            (COLOR_BREAK, "Break"),
        ]:
            legend_item = QLabel(f"<span style='background-color:{color}; color:{COLOR_TEXT}; padding:2px 6px; border-radius:3px;'>{text}</span>")
            legend_layout.addWidget(legend_item)
        
        legend_layout.addStretch()
        main_layout.addLayout(legend_layout)
        
        # Cycle info label
        self.cycle_info_label = QLabel()
        self.cycle_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cycle_info_label.setStyleSheet(f"color: {COLOR_TEXT}; font-size: 11px;")
        main_layout.addWidget(self.cycle_info_label)
        
        # Calendar grid container
        self.calendar_container = QWidget()
        self.calendar_layout = QGridLayout(self.calendar_container)
        self.calendar_layout.setSpacing(2)
        main_layout.addWidget(self.calendar_container)
        
        # Today's info
        self.today_info = QLabel()
        self.today_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_info.setWordWrap(True)
        self.today_info.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px; margin-top: 4px;")
        main_layout.addWidget(self.today_info)
        
        self._update_calendar()
    
    def _update_calendar(self):
        """Rebuild the calendar grid for the current display month."""
        cfg = get_config()
        
        # Clear existing cells
        while self.calendar_layout.count():
            item = self.calendar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Update month label
        month_name = calendar.month_name[self.display_month]
        self.month_label.setText(f"{month_name} {self.display_year}")
        
        # Update cycle info
        today_cycle = get_cycle_info(cfg)
        start_date = cfg.get("audio_cycle_start_date", "")
        if start_date:
            cycle_num = today_cycle.get("cycle_number", 1)
            cycle_start = today_cycle.get("cycle_start")
            cycle_end = today_cycle.get("cycle_end")
            if cycle_start and cycle_end:
                self.cycle_info_label.setText(
                    f"📆 Cycle {cycle_num}: {cycle_start.strftime('%b %d')} - {cycle_end.strftime('%b %d, %Y')}"
                )
            else:
                self.cycle_info_label.setText(f"📆 Cycle {cycle_num}")
        else:
            self.cycle_info_label.setText("📆 No cycle configured (using calendar day)")
        
        # Day headers (Mon-Sun)
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for col, day_name in enumerate(days):
            lbl = QLabel(day_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"font-weight: bold; color: {COLOR_HEADER}; font-size: 10px;")
            self.calendar_layout.addWidget(lbl, 0, col)
        
        # Get calendar data
        cal = calendar.Calendar(firstweekday=0)  # Monday first
        month_days = cal.monthdayscalendar(self.display_year, self.display_month)
        
        today = date.today()
        
        # Create day cells
        for row, week in enumerate(month_days):
            for col, day in enumerate(week):
                if day == 0:
                    # Empty cell for days outside the month
                    empty = QLabel("")
                    self.calendar_layout.addWidget(empty, row + 1, col)
                else:
                    # Get cycle info for this specific date
                    cell_date = date(self.display_year, self.display_month, day)
                    cell_cycle_info = get_cycle_info(cfg, cell_date)
                    is_today = (cell_date == today)
                    
                    cell = DayCell(day, self.display_month, self.display_year, 
                                   is_today, cell_cycle_info, cfg)
                    cell.set_tooltip()
                    self.calendar_layout.addWidget(cell, row + 1, col)
        
        # Update today's info
        effective = get_effective_day(cfg)
        override = cfg.get("audio_playlist_override_enabled", False)
        
        if today_cycle.get("is_break", False):
            study_days = int(cfg.get("audio_cycle_study_days", 21) or 21)
            break_day = today_cycle.get("cycle_day", 0) - study_days
            self.today_info.setText(f"🎉 Today is Break Day {break_day}/5 - No audio")
        elif override:
            override_day = cfg.get("audio_playlist_override_day", 1)
            playlists = get_playlists_for_day(override_day)
            playlist_text = " → ".join([f"P{pid}" + ("*" if loops else "") for pid, loops in playlists])
            self.today_info.setText(f"📍 Override active: Day {override_day} | {playlist_text}")
        else:
            playlists = get_playlists_for_day(effective)
            playlist_text = " → ".join([f"P{pid}" + ("*" if loops else "") for pid, loops in playlists]) if playlists else "None"
            cycle_day = today_cycle.get("cycle_day", effective)
            self.today_info.setText(f"📍 Today: Cycle Day {cycle_day} | {playlist_text}")
    
    def _prev_month(self):
        """Navigate to previous month."""
        if self.display_month == 1:
            self.display_month = 12
            self.display_year -= 1
        else:
            self.display_month -= 1
        self._update_calendar()
    
    def _next_month(self):
        """Navigate to next month."""
        if self.display_month == 12:
            self.display_month = 1
            self.display_year += 1
        else:
            self.display_month += 1
        self._update_calendar()
    
    def refresh(self):
        """Refresh the calendar display."""
        self._update_calendar()


# Global widget reference
_calendar_dialog: Optional[QDialog] = None


class PlaylistCalendarDialog(QDialog):
    """Popup dialog containing the playlist calendar and music player."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Playlist Calendar")
        self.setMinimumSize(380, 580)
        self.setStyleSheet("background-color: #2D2D2D;")  # Dark background
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Add calendar widget
        self.calendar_widget = PlaylistCalendarWidget(self)
        layout.addWidget(self.calendar_widget)
        
        # Add simple progress widget for testing
        self.music_player = MusicProgressWidget(self)
        layout.addWidget(self.music_player)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #404040;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def closeEvent(self, event):
        """Stop the timer when dialog is closed."""
        if hasattr(self, 'music_player') and self.music_player.update_timer:
            self.music_player.update_timer.stop()
        super().closeEvent(event)
    
    def showEvent(self, event):
        """Restart timer when dialog is shown."""
        if hasattr(self, 'music_player'):
            self.music_player.update_timer.start(500)
            self.music_player._update_display()
        super().showEvent(event)


def show_calendar_dialog():
    """Show the playlist calendar as a popup dialog."""
    global _calendar_dialog
    
    if _calendar_dialog is None:
        _calendar_dialog = PlaylistCalendarDialog(mw)
    else:
        # Refresh the calendar data
        _calendar_dialog.calendar_widget.refresh()
    
    _calendar_dialog.show()
    _calendar_dialog.raise_()
    _calendar_dialog.activateWindow()


def get_calendar_widget() -> PlaylistCalendarWidget:
    """Get or create the calendar widget."""
    global _calendar_dialog
    if _calendar_dialog is None:
        _calendar_dialog = PlaylistCalendarDialog(mw)
    return _calendar_dialog.calendar_widget


def inject_calendar_into_main_window():
    """Legacy function - now does nothing. Use show_calendar_dialog() instead."""
    # This function is kept for backward compatibility but does nothing
    # The calendar is now shown as a popup dialog from Tools menu
    pass


def remove_calendar_from_main_window():
    """Remove the calendar dialog."""
    global _calendar_dialog
    try:
        if _calendar_dialog:
            _calendar_dialog.close()
            _calendar_dialog = None
    except Exception:
        pass
