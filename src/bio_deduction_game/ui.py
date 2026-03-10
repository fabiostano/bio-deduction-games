from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .data import (
    DataProvider,
    LiveHubProvider,
    MockProvider,
    OpenSignalsLSLDebugProvider,
    OpenSignalsLSLProvider,
    build_assignments,
    discover_connected_hubs,
)

WINDOW_SECONDS = 60.0
MAX_POINTS = 1200


@dataclass
class PlayerBuffer:
    ts: Deque[float]
    hrs: Deque[float]
    edas: Deque[float]


class PlayerCard(QFrame):
    clicked = Signal(str)

    def __init__(self, player_id: str, accent: str, show_eda: bool = True) -> None:
        super().__init__()
        self.player_id = player_id
        self.accent = accent
        self.show_eda = show_eda
        self.setObjectName("playerCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        self.name_lbl = QLabel(player_id)
        self.name_lbl.setObjectName("nameLabel")
        self.name_lbl.setStyleSheet(f"color: {accent};")

        self.heart_lbl = QLabel("♥")
        self.heart_lbl.setObjectName("heartLabel")
        self.heart_lbl.setStyleSheet(f"color: {accent};")

        self.hr_lbl = QLabel("-- bpm")
        self.hr_lbl.setObjectName("hrLabel")
        self.hr_lbl.setStyleSheet(f"color: {accent};")

        bpm_box = QHBoxLayout()
        bpm_box.setSpacing(5)
        bpm_box.addWidget(self.heart_lbl)
        bpm_box.addWidget(self.hr_lbl)

        top.addWidget(self.name_lbl)
        top.addStretch(1)
        top.addLayout(bpm_box)
        root.addLayout(top)

        self.hr_plot = pg.PlotWidget()
        self._style_plot(self.hr_plot, "HR")

        hr_color = QColor(accent)
        hr_color.setAlphaF(0.8)
        self.hr_curve = self.hr_plot.plot(pen=pg.mkPen(color=hr_color, width=2))

        root.addWidget(self.hr_plot)

        self.eda_plot = None
        self.eda_curve = None
        if self.show_eda:
            self.eda_plot = pg.PlotWidget()
            self._style_plot(self.eda_plot, "EDA")
            eda_color = QColor(accent)
            eda_color.setAlphaF(0.6)
            self.eda_curve = self.eda_plot.plot(pen=pg.mkPen(color=eda_color, width=2))
            root.addWidget(self.eda_plot)

        self._pulse_on = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start(800)

        self.overlay = QLabel("💔", self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setStyleSheet(
            "background-color: rgba(7, 10, 18, 0.62);"
            "color: #ff6b81; font-size: 56px; font-weight: 800;"
            "border-radius: 12px;"
        )
        self.overlay.hide()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.player_id)
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def _pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self.heart_lbl.setText("♥" if self._pulse_on else "♡")

    def _style_plot(self, plot: pg.PlotWidget, title: str) -> None:
        plot.setBackground("#101424")
        plot.showGrid(x=True, y=True, alpha=0.16)
        plot.setLabel("left", title)
        plot.setLabel("bottom", "-60s … now")
        plot.getAxis("left").setTextPen("#C9D1E5")
        plot.getAxis("bottom").setTextPen("#C9D1E5")
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=False, y=False)

    def set_eliminated(self, eliminated: bool) -> None:
        self.overlay.setVisible(eliminated)

    def update_data(self, x_sec: List[float], hrs: List[float], edas: List[float]) -> None:
        if hrs:
            bpm = hrs[-1]
            self.hr_lbl.setText(f"{bpm:.0f} bpm")
            interval = int(max(350, min(1300, 60000 / max(bpm, 1.0))))
            self._pulse_timer.setInterval(interval)

        self.hr_curve.setData(x_sec, hrs)
        if self.show_eda and self.eda_curve is not None:
            self.eda_curve.setData(x_sec, edas)


class StartScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("BIO DEDUCTION GAMES")
        title.setObjectName("title")
        subtitle = QLabel("Setup • Generic social-deduction companion")
        subtitle.setObjectName("subtitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(title)
        root.addWidget(subtitle)

        panel = QFrame()
        self.setup_panel = panel
        panel.setObjectName("setupPanel")
        panel.setMaximumWidth(1370)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(14)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Spielmodus:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Generic"])
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        panel_layout.addLayout(mode_row)

        data_row = QHBoxLayout()
        data_row.addWidget(QLabel("Datenquelle:"))
        self.mock_radio = QRadioButton("Mock Data")
        self.live_radio = QRadioButton("Live Data")
        self.mock_radio.setChecked(True)

        self.source_group = QButtonGroup(self)
        self.source_group.addButton(self.mock_radio)
        self.source_group.addButton(self.live_radio)
        self.mock_radio.toggled.connect(self._refresh_limits)
        self.live_radio.toggled.connect(self._refresh_limits)

        data_row.addWidget(self.mock_radio)
        data_row.addWidget(self.live_radio)
        data_row.addStretch(1)
        panel_layout.addLayout(data_row)

        backend_row = QHBoxLayout()
        backend_row.addWidget(QLabel("Live-Backend:"))
        self.live_backend_combo = QComboBox()
        self.live_backend_combo.addItems(["Direct Hub (MAC)", "OpenSignals Stream (LSL)"])
        self.live_backend_combo.currentTextChanged.connect(self._refresh_limits)
        backend_row.addWidget(self.live_backend_combo)
        backend_row.addStretch(1)
        panel_layout.addLayout(backend_row)

        lsl_debug_row = QHBoxLayout()
        self.lsl_debug_checkbox = QCheckBox("LSL Debug-Modus (alle empfangenen Zeitreihen plotten)")
        self.lsl_debug_checkbox.toggled.connect(self._refresh_limits)
        lsl_debug_row.addWidget(self.lsl_debug_checkbox)
        lsl_debug_row.addStretch(1)
        panel_layout.addLayout(lsl_debug_row)

        signal_row = QHBoxLayout()
        signal_row.addWidget(QLabel("Signalmodus:"))
        self.signal_mode_combo = QComboBox()
        self.signal_mode_combo.addItems(["ECG + EDA", "ECG only"])
        self.signal_mode_combo.currentTextChanged.connect(self._update_mapping_preview)
        signal_row.addWidget(self.signal_mode_combo)
        signal_row.addStretch(1)
        panel_layout.addLayout(signal_row)

        hubs_title = QLabel("Hubs (MAC-Adressen)")
        hubs_title.setObjectName("sectionTitle")
        panel_layout.addWidget(hubs_title)

        hub_row = QHBoxLayout()
        self.detect_hubs_btn = QPushButton("Hubs erkennen")
        self.detect_hubs_btn.clicked.connect(self.detect_hubs)
        self.connected_hubs_lbl = QLabel("Keine Hubs erkannt")
        self.connected_hubs_lbl.setObjectName("status")
        hub_row.addWidget(self.detect_hubs_btn)
        hub_row.addWidget(self.connected_hubs_lbl)
        hub_row.addStretch(1)
        panel_layout.addLayout(hub_row)

        self.manual_hubs_edit = QLineEdit()
        self.manual_hubs_edit.setPlaceholderText("Optional: MACs manuell (kommagetrennt), z.B. AA:..,BB:..")
        self.manual_hubs_edit.textChanged.connect(self._refresh_limits)
        panel_layout.addWidget(self.manual_hubs_edit)

        players_title = QLabel("Spieler")
        players_title.setObjectName("sectionTitle")
        panel_layout.addWidget(players_title)

        self.max_players_lbl = QLabel("Maximal 4 Spieler (1 Hub) / 8 Spieler (2 Hubs)")
        self.max_players_lbl.setObjectName("status")
        panel_layout.addWidget(self.max_players_lbl)

        self.players_box = QGridLayout()
        self.players_box.setHorizontalSpacing(14)
        self.players_box.setVerticalSpacing(8)
        self.players_box.setColumnStretch(0, 1)
        self.players_box.setColumnStretch(1, 1)
        panel_layout.addLayout(self.players_box)

        add_row = QHBoxLayout()
        self.add_player_btn = QPushButton("+")
        self.add_player_btn.setFixedWidth(34)
        self.add_player_btn.clicked.connect(self.add_player_field)
        add_row.addWidget(self.add_player_btn)
        self.add_hint = QLabel("Spieler hinzufügen")
        add_row.addWidget(self.add_hint)
        add_row.addStretch(1)
        panel_layout.addLayout(add_row)

        map_title = QLabel("Auto-Mapping (Orientierung)")
        map_title.setObjectName("sectionTitle")
        panel_layout.addWidget(map_title)

        self.mapping_left_lbl = QLabel("Noch kein Mapping")
        self.mapping_left_lbl.setWordWrap(True)
        self.mapping_left_lbl.setObjectName("status")
        self.mapping_right_lbl = QLabel("")
        self.mapping_right_lbl.setWordWrap(True)
        self.mapping_right_lbl.setObjectName("status")

        mapping_scroll = QScrollArea()
        mapping_scroll.setWidgetResizable(True)
        mapping_widget = QWidget()
        mlay = QHBoxLayout(mapping_widget)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.setSpacing(24)
        mlay.addWidget(self.mapping_left_lbl, 1)
        mlay.addWidget(self.mapping_right_lbl, 1)
        mapping_scroll.setWidget(mapping_widget)
        mapping_scroll.setMinimumHeight(140)
        panel_layout.addWidget(mapping_scroll)

        panel_row = QHBoxLayout()
        panel_row.addStretch(1)
        panel_row.addWidget(panel, 1)
        panel_row.addStretch(1)
        root.addLayout(panel_row, 1)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setMinimumHeight(44)
        root.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.player_edits: List[QLineEdit] = []
        self.detected_hubs: List[str] = []
        self._max_players = 4
        self.add_player_field("Player 1")
        self._refresh_limits()
        self._setup_intro_animation()

    def _live_uses_lsl(self) -> bool:
        return self.live_radio.isChecked() and self.live_backend_combo.currentText().startswith("OpenSignals")

    def _include_eda(self) -> bool:
        return self.signal_mode_combo.currentText().startswith("ECG + EDA")

    def _lsl_debug_enabled(self) -> bool:
        return self._live_uses_lsl() and self.lsl_debug_checkbox.isChecked()

    def _parse_manual_hubs(self) -> List[str]:
        raw = self.manual_hubs_edit.text().strip()
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()][:2]

    def _active_hubs(self) -> List[str]:
        manual = self._parse_manual_hubs()
        return manual if manual else self.detected_hubs

    def detect_hubs(self) -> None:
        self.detected_hubs = discover_connected_hubs()
        if self.detected_hubs:
            self.connected_hubs_lbl.setText("Erkannt: " + " | ".join(self.detected_hubs))
        else:
            self.connected_hubs_lbl.setText("Keine Hubs erkannt (Fallback: manuell eintragen)")
        self._refresh_limits()

    def _refresh_limits(self) -> None:
        hub_count = max(1, min(2, len(self._active_hubs()) or 1))
        self._max_players = 8

        if self._live_uses_lsl():
            self.detect_hubs_btn.setEnabled(False)
            self.manual_hubs_edit.setEnabled(False)
            self.lsl_debug_checkbox.setEnabled(True)
            self.connected_hubs_lbl.setText("LSL-Modus: Hub-Erkennung nicht nötig")
        else:
            self.detect_hubs_btn.setEnabled(True)
            self.manual_hubs_edit.setEnabled(True)
            self.lsl_debug_checkbox.setEnabled(False)
            self.lsl_debug_checkbox.setChecked(False)

        self.max_players_lbl.setText(f"Aktuell max. {self._max_players} Spieler (Hub(s): {hub_count})")

        while len(self.player_edits) > self._max_players:
            edit = self.player_edits.pop()
            edit.setParent(None)

        self._reflow_player_fields()
        self.add_player_btn.setEnabled(len(self.player_edits) < self._max_players)
        self._update_mapping_preview()

    def _setup_intro_animation(self) -> None:
        self._intro_effect = QGraphicsOpacityEffect(self.setup_panel)
        self.setup_panel.setGraphicsEffect(self._intro_effect)
        self._intro_effect.setOpacity(0.0)

        fade = QPropertyAnimation(self._intro_effect, b"opacity", self)
        fade.setDuration(420)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        btn_fade_effect = QGraphicsOpacityEffect(self.start_btn)
        self.start_btn.setGraphicsEffect(btn_fade_effect)
        btn_fade_effect.setOpacity(0.0)
        btn_fade = QPropertyAnimation(btn_fade_effect, b"opacity", self)
        btn_fade.setDuration(280)
        btn_fade.setStartValue(0.0)
        btn_fade.setEndValue(1.0)
        btn_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._intro_anim = QSequentialAnimationGroup(self)
        self._intro_anim.addAnimation(fade)
        self._intro_anim.addAnimation(btn_fade)
        self._intro_anim.start()

    def _reflow_player_fields(self) -> None:
        while self.players_box.count():
            item = self.players_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        for i, edit in enumerate(self.player_edits):
            row = i % 4
            col = i // 4
            self.players_box.addWidget(edit, row, col)

    def add_player_field(self, default_text: str | None = None) -> None:
        if len(self.player_edits) >= self._max_players:
            return
        idx = len(self.player_edits) + 1
        edit = QLineEdit()
        edit.setPlaceholderText(f"Player {idx}")
        if default_text:
            edit.setText(default_text)
        edit.textChanged.connect(self._update_mapping_preview)
        self.player_edits.append(edit)
        self._reflow_player_fields()

        self.add_player_btn.setEnabled(len(self.player_edits) < self._max_players)
        self._update_mapping_preview()

    def _effective_players(self) -> List[str]:
        players: List[str] = []
        for i, edit in enumerate(self.player_edits, start=1):
            players.append(edit.text().strip() or f"Player {i}")
        return players

    def _update_mapping_preview(self) -> None:
        hubs = self._active_hubs()
        players = self._effective_players()

        if self._live_uses_lsl():
            hubs = ["LSL"]
        elif not hubs:
            msg = "Keine Hub-MAC vorhanden. Für Live: Hubs erkennen oder manuell eintragen."
            self.mapping_left_lbl.setText(msg)
            self.mapping_right_lbl.setText("")
            return

        if self._lsl_debug_enabled():
            self.mapping_left_lbl.setText("LSL-Debug aktiv: Alle eingehenden Streams/Kanäle werden automatisch als eigene Karten geplottet.")
            self.mapping_right_lbl.setText("Spieler-/Hub-Mapping wird in diesem Modus ignoriert.")
            return

        assignments = build_assignments(players, hubs, include_eda=self._include_eda())
        if not assignments:
            self.mapping_left_lbl.setText("Kein Mapping verfügbar.")
            self.mapping_right_lbl.setText("")
            return

        lines = []
        for a in assignments:
            if a.channel_eda > 0:
                lines.append(f"{a.player_name} → {a.hub_mac} | CH{a.channel_ekg}=EKG, CH{a.channel_eda}=EDA")
            else:
                lines.append(f"{a.player_name} → {a.hub_mac} | CH{a.channel_ekg}=EKG, EDA übersprungen")

        self.mapping_left_lbl.setText("\n".join(lines[:4]))
        self.mapping_right_lbl.setText("\n".join(lines[4:8]))

    def get_config(self) -> Tuple[str, str, List[str], List[str], str, bool, bool]:
        mode = self.mode_combo.currentText()
        source = "live" if self.live_radio.isChecked() else "mock"
        players = self._effective_players()
        live_backend = "lsl" if self._live_uses_lsl() else "direct"
        hubs = ["LSL"] if live_backend == "lsl" else self._active_hubs()
        include_eda = self._include_eda()
        lsl_debug = self._lsl_debug_enabled()
        return mode, source, players, hubs, live_backend, include_eda, lsl_debug


class DashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.provider: DataProvider | None = None
        self.players: List[str] = []
        self.cards: Dict[str, PlayerCard] = {}
        self.show_eda = True
        self.buffers: Dict[str, PlayerBuffer] = {}
        self.hidden_players: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        left = QVBoxLayout()
        self.title = QLabel("BIO DEDUCTION GAMES")
        self.title.setObjectName("title")
        self.subtitle = QLabel("Generic Mode • Live HR + EDA")
        self.subtitle.setObjectName("subtitle")
        left.addWidget(self.title)
        left.addWidget(self.subtitle)

        self.status = QLabel("Data source: -")
        self.status.setObjectName("status")
        self.back_btn = QPushButton("Zurück zum Start")

        header.addLayout(left)
        header.addStretch(1)
        header.addWidget(self.status)
        header.addWidget(self.back_btn)
        root.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setSpacing(24)
        root.addLayout(self.grid, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._palette = [
            "#f7c948",
            "#ff7f7f",
            "#8ce99a",
            "#9ecbff",
            "#f4a6ff",
            "#ffd8a8",
            "#98f5e1",
            "#ffd43b",
        ]

    def start(
        self,
        mode: str,
        source: str,
        players: List[str],
        hubs: List[str],
        live_backend: str = "direct",
        include_eda: bool = True,
        lsl_debug: bool = False,
    ) -> None:
        self.timer.stop()
        self._clear_grid()
        self.hidden_players = set()

        self.players = players
        self.show_eda = include_eda and not lsl_debug
        assignments = build_assignments(players, hubs, include_eda=include_eda)

        if self.provider is not None:
            self.provider.close()

        if source == "mock":
            self.provider = MockProvider(players)
            source_text = "Mock Data"
        else:
            if live_backend == "lsl" and lsl_debug:
                self.provider = OpenSignalsLSLDebugProvider()
                backend = self.provider.backend_name if isinstance(self.provider, OpenSignalsLSLDebugProvider) else "unknown"
                details = self.provider.status if isinstance(self.provider, OpenSignalsLSLDebugProvider) else ""
                source_text = f"Live Data OpenSignals LSL DEBUG ({backend}) {details}".strip()
                self.players = []
            elif live_backend == "lsl":
                self.provider = OpenSignalsLSLProvider(assignments)
                backend = self.provider.backend_name if isinstance(self.provider, OpenSignalsLSLProvider) else "unknown"
                details = self.provider.status if isinstance(self.provider, OpenSignalsLSLProvider) else ""
                source_text = f"Live Data via OpenSignals LSL ({backend}) {details}".strip()
            else:
                self.provider = LiveHubProvider(assignments)
                backend = self.provider.backend_name if isinstance(self.provider, LiveHubProvider) else "unknown"
                details = self.provider.status if isinstance(self.provider, LiveHubProvider) else ""
                source_text = f"Live Data Direct Hub ({backend}) {details}".strip()

        signal_text = "LSL Raw Debug" if lsl_debug else ("HR + EDA" if include_eda else "HR (ECG only)")
        self.subtitle.setText(f"{mode} Mode • {signal_text}")
        self.status.setText(f"Data source: {source_text}")

        self.buffers = {
            p: PlayerBuffer(deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS))
            for p in self.players
        }

        self.cards = {}

        for p in self.players:
            self._add_card_for_player(p)

        self.timer.start(200)

    def _add_card_for_player(self, player: str) -> None:
        if player in self.cards:
            return

        idx = len(self.cards)
        accent = self._palette[idx % len(self._palette)]
        card = PlayerCard(player, accent, show_eda=self.show_eda)
        card.clicked.connect(self._eliminate_player)
        self.cards[player] = card

        if player not in self.buffers:
            self.buffers[player] = PlayerBuffer(deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS))

        r, c = divmod(idx, 4)
        self.grid.addWidget(card, r, c)

    def _eliminate_player(self, player: str) -> None:
        card = self.cards.get(player)
        if not card:
            return

        if player in self.hidden_players:
            self.hidden_players.discard(player)
            card.set_eliminated(False)
        else:
            self.hidden_players.add(player)
            card.set_eliminated(True)

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _tick(self) -> None:
        if self.provider is None:
            return

        if isinstance(self.provider, (LiveHubProvider, OpenSignalsLSLProvider, OpenSignalsLSLDebugProvider)):
            self.status.setText(f"Data source: {self.provider.source_name} • {self.provider.status}")

        samples = self.provider.get_samples()

        for pid, s in samples.items():
            if pid not in self.buffers:
                self._add_card_for_player(pid)
            if pid in self.hidden_players:
                continue
            b = self.buffers[pid]
            b.ts.append(s.t)
            b.hrs.append(s.hr)
            b.edas.append(s.eda)

        self._render()

    def _render(self) -> None:
        for pid, card in self.cards.items():
            b = self.buffers[pid]
            if not b.ts:
                continue
            now = b.ts[-1]

            filtered: List[Tuple[float, float, float]] = [
                (t, hr, eda)
                for t, hr, eda in zip(b.ts, b.hrs, b.edas)
                if t >= now - WINDOW_SECONDS
            ]
            if not filtered:
                continue

            x = [t - now for (t, _, _) in filtered]
            y_hr = [hr for (_, hr, _) in filtered]
            y_eda = [eda for (_, _, eda) in filtered]
            card.update_data(x, y_hr, y_eda)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bio Deduction Games")
        self.resize(1700, 980)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start_screen = StartScreen()
        self.dashboard = DashboardScreen()

        self.stack.addWidget(self.start_screen)
        self.stack.addWidget(self.dashboard)
        self.stack.setCurrentWidget(self.start_screen)

        self.start_screen.start_btn.clicked.connect(self._start_game)
        self.dashboard.back_btn.clicked.connect(self._back_to_start)

        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0f1f, stop:1 #101a34);
                color: #E6ECFF;
                font-family: Segoe UI, Inter, Arial;
            }
            QLabel#title {
                font-size: 30px;
                font-weight: 800;
                letter-spacing: 1px;
            }
            QLabel#subtitle {
                color: #9AA7C7;
                font-size: 14px;
            }
            QLabel#status {
                color: #9AA7C7;
                font-size: 12px;
                padding-right: 10px;
            }
            QLabel#sectionTitle {
                font-size: 14px;
                font-weight: 700;
                color: #C7D4F4;
            }
            QFrame#setupPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #121b35, stop:1 #162449);
                border: 1px solid #2c3f70;
                border-radius: 16px;
            }
            QLineEdit, QComboBox {
                background: #101a33;
                border: 1px solid #314674;
                border-radius: 10px;
                padding: 8px 11px;
                color: #E6ECFF;
                min-height: 18px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #5a86ff;
            }
            QPushButton {
                background: #1D2A4A;
                border: 1px solid #355186;
                border-radius: 10px;
                padding: 8px 12px;
                color: #E6ECFF;
            }
            QPushButton:hover {
                background: #2a3f6b;
                border-color: #4d71b7;
            }
            QPushButton#primaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2f63ff, stop:1 #5d83ff);
                border-color: #5d83ff;
                font-weight: 800;
                min-width: 150px;
            }
            QPushButton#primaryBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4975ff, stop:1 #7597ff);
            }
            QPushButton#elimBtn {
                background: #3a274f;
                border-color: #614080;
            }
            QFrame#playerCard {
                background: #121a32;
                border: 1px solid #223156;
                border-radius: 12px;
                min-height: 220px;
                max-height: 300px;
            }
            QLabel#nameLabel {
                font-weight: 800;
                font-size: 22px;
            }
            QLabel#hrLabel {
                font-weight: 800;
                font-size: 23px;
            }
            QLabel#heartLabel {
                font-size: 24px;
                font-weight: 800;
            }
            """
        )

    def _start_game(self) -> None:
        mode, source, players, hubs, live_backend, include_eda, lsl_debug = self.start_screen.get_config()
        if not players and not (source == "live" and live_backend == "lsl" and lsl_debug):
            QMessageBox.warning(self, "Fehlende Spieler", "Bitte mindestens einen Spieler anlegen.")
            return

        self.dashboard.start(mode, source, players, hubs, live_backend, include_eda, lsl_debug)
        self.stack.setCurrentWidget(self.dashboard)

    def _back_to_start(self) -> None:
        self.dashboard.timer.stop()
        if self.dashboard.provider is not None:
            self.dashboard.provider.close()
        self.stack.setCurrentWidget(self.start_screen)


def build_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    pg.setConfigOptions(antialias=True)

    window = MainWindow()
    window.show()
    app._main_window = window
    return app
