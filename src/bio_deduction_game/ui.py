from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
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

    def __init__(self, player_id: str, accent: str) -> None:
        super().__init__()
        self.player_id = player_id
        self.accent = accent
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
        self.eda_plot = pg.PlotWidget()

        self._style_plot(self.hr_plot, "HR")
        self._style_plot(self.eda_plot, "EDA")

        hr_color = QColor(accent)
        hr_color.setAlphaF(0.8)
        eda_color = QColor(accent)
        eda_color.setAlphaF(0.6)

        self.hr_curve = self.hr_plot.plot(pen=pg.mkPen(color=hr_color, width=2))
        self.eda_curve = self.eda_plot.plot(pen=pg.mkPen(color=eda_color, width=2))

        root.addWidget(self.hr_plot)
        root.addWidget(self.eda_plot)

        self._pulse_on = True
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start(800)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.player_id)
        super().mousePressEvent(event)

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

    def update_data(self, x_sec: List[float], hrs: List[float], edas: List[float]) -> None:
        if hrs:
            bpm = hrs[-1]
            self.hr_lbl.setText(f"{bpm:.0f} bpm")
            interval = int(max(350, min(1300, 60000 / max(bpm, 1.0))))
            self._pulse_timer.setInterval(interval)

        self.hr_curve.setData(x_sec, hrs)
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
        root.addWidget(title)
        root.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("setupPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(12)

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

        self.players_box = QVBoxLayout()
        self.players_box.setSpacing(8)
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

        self.mapping_lbl = QLabel("Noch kein Mapping")
        self.mapping_lbl.setWordWrap(True)
        self.mapping_lbl.setObjectName("status")

        mapping_scroll = QScrollArea()
        mapping_scroll.setWidgetResizable(True)
        mapping_widget = QWidget()
        mlay = QVBoxLayout(mapping_widget)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.addWidget(self.mapping_lbl)
        mlay.addStretch(1)
        mapping_scroll.setWidget(mapping_widget)
        mapping_scroll.setMinimumHeight(120)
        panel_layout.addWidget(mapping_scroll)

        root.addWidget(panel, 1)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primaryBtn")
        root.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.player_edits: List[QLineEdit] = []
        self.detected_hubs: List[str] = []
        self._max_players = 4
        self.add_player_field("Player 1")
        self._refresh_limits()

    def _live_uses_lsl(self) -> bool:
        return self.live_radio.isChecked() and self.live_backend_combo.currentText().startswith("OpenSignals")

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
        if self._live_uses_lsl():
            hub_count = 1
            self._max_players = 4
            self.detect_hubs_btn.setEnabled(False)
            self.manual_hubs_edit.setEnabled(False)
            self.connected_hubs_lbl.setText("LSL-Modus: Hub-Erkennung nicht nötig")
        else:
            hub_count = max(1, min(2, len(self._active_hubs()) or 1))
            self._max_players = 4 if hub_count == 1 else 8
            self.detect_hubs_btn.setEnabled(True)
            self.manual_hubs_edit.setEnabled(True)

        self.max_players_lbl.setText(f"Aktuell max. {self._max_players} Spieler ({hub_count} Hub(s))")

        while len(self.player_edits) > self._max_players:
            edit = self.player_edits.pop()
            edit.setParent(None)

        self.add_player_btn.setEnabled(len(self.player_edits) < self._max_players)
        self._update_mapping_preview()

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
        self.players_box.addWidget(edit)

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
            self.mapping_lbl.setText("Keine Hub-MAC vorhanden. Für Live: Hubs erkennen oder manuell eintragen.")
            return

        assignments = build_assignments(players, hubs)
        if not assignments:
            self.mapping_lbl.setText("Kein Mapping verfügbar.")
            return

        lines = []
        for a in assignments:
            lines.append(
                f"{a.player_name} → {a.hub_mac} | CH{a.channel_ekg}=EKG, CH{a.channel_eda}=EDA"
            )
        self.mapping_lbl.setText("\n".join(lines))

    def get_config(self) -> Tuple[str, str, List[str], List[str], str]:
        mode = self.mode_combo.currentText()
        source = "live" if self.live_radio.isChecked() else "mock"
        players = self._effective_players()
        live_backend = "lsl" if self._live_uses_lsl() else "direct"
        hubs = ["LSL"] if live_backend == "lsl" else self._active_hubs()
        return mode, source, players, hubs, live_backend


class DashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.provider: DataProvider | None = None
        self.players: List[str] = []
        self.cards: Dict[str, PlayerCard] = {}
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

        elim_title = QLabel("Eliminierte Spieler (klicken zum Zurückholen)")
        elim_title.setObjectName("subtitle")
        root.addWidget(elim_title)

        self.elim_bar = QHBoxLayout()
        self.elim_bar.setSpacing(8)
        root.addLayout(self.elim_bar)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self, mode: str, source: str, players: List[str], hubs: List[str], live_backend: str = "direct") -> None:
        self.timer.stop()
        self._clear_grid()
        self._clear_elim_bar()
        self.hidden_players = set()

        self.players = players
        assignments = build_assignments(players, hubs)

        if self.provider is not None:
            self.provider.close()

        if source == "mock":
            self.provider = MockProvider(players)
            source_text = "Mock Data"
        else:
            if live_backend == "lsl":
                self.provider = OpenSignalsLSLProvider(assignments)
                backend = self.provider.backend_name if isinstance(self.provider, OpenSignalsLSLProvider) else "unknown"
                details = self.provider.status if isinstance(self.provider, OpenSignalsLSLProvider) else ""
                source_text = f"Live Data via OpenSignals LSL ({backend}) {details}".strip()
            else:
                self.provider = LiveHubProvider(assignments)
                backend = self.provider.backend_name if isinstance(self.provider, LiveHubProvider) else "unknown"
                details = self.provider.status if isinstance(self.provider, LiveHubProvider) else ""
                source_text = f"Live Data Direct Hub ({backend}) {details}".strip()

        self.subtitle.setText(f"{mode} Mode • Live HR + EDA")
        self.status.setText(f"Data source: {source_text}")

        self.buffers = {
            p: PlayerBuffer(deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS))
            for p in players
        }

        colors = [
            "#f7c948",
            "#ff7f7f",
            "#8ce99a",
            "#9ecbff",
            "#f4a6ff",
            "#ffd8a8",
            "#98f5e1",
            "#ffd43b",
        ]
        self.cards = {}

        for i, p in enumerate(players):
            card = PlayerCard(p, colors[i % len(colors)])
            card.clicked.connect(self._eliminate_player)
            self.cards[p] = card
            r, c = divmod(i, 4)
            self.grid.addWidget(card, r, c)

        self.timer.start(200)

    def _eliminate_player(self, player: str) -> None:
        if player in self.hidden_players:
            return
        card = self.cards.get(player)
        if not card:
            return
        card.hide()
        self.hidden_players.add(player)

        btn = QPushButton(player)
        btn.setObjectName("elimBtn")
        btn.clicked.connect(lambda: self._restore_player(player, btn))
        self.elim_bar.addWidget(btn)

    def _restore_player(self, player: str, button: QPushButton) -> None:
        card = self.cards.get(player)
        if card:
            card.show()
        self.hidden_players.discard(player)
        button.setParent(None)

    def _clear_elim_bar(self) -> None:
        while self.elim_bar.count():
            item = self.elim_bar.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _tick(self) -> None:
        if self.provider is None:
            return

        if isinstance(self.provider, (LiveHubProvider, OpenSignalsLSLProvider)):
            self.status.setText(f"Data source: {self.provider.source_name} • {self.provider.status}")

        samples = self.provider.get_samples()

        for pid, s in samples.items():
            if pid not in self.buffers:
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
                background: #0b1020;
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
                background: #121a32;
                border: 1px solid #223156;
                border-radius: 12px;
            }
            QLineEdit, QComboBox {
                background: #121a32;
                border: 1px solid #2a3a64;
                border-radius: 8px;
                padding: 7px 10px;
                color: #E6ECFF;
            }
            QPushButton {
                background: #1D2A4A;
                border: 1px solid #2f3d66;
                border-radius: 8px;
                padding: 8px 12px;
                color: #E6ECFF;
            }
            QPushButton:hover {
                background: #27365b;
            }
            QPushButton#primaryBtn {
                background: #2b5fff;
                border-color: #2b5fff;
                font-weight: 700;
                min-width: 120px;
            }
            QPushButton#primaryBtn:hover {
                background: #4776ff;
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
        mode, source, players, hubs, live_backend = self.start_screen.get_config()
        if not players:
            QMessageBox.warning(self, "Fehlende Spieler", "Bitte mindestens einen Spieler anlegen.")
            return

        if source == "live" and live_backend == "direct" and len(players) > 4 and len(hubs) < 2:
            QMessageBox.warning(
                self,
                "Zu viele Spieler",
                "Mehr als 4 Spieler benötigen 2 verbundene Hubs (oder 2 MACs im Setup).",
            )
            return

        self.dashboard.start(mode, source, players, hubs, live_backend)
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
