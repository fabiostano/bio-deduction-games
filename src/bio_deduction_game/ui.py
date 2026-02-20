from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .data import DataProvider, LiveHubProvider, MockProvider

WINDOW_SECONDS = 60.0
MAX_POINTS = 1200
MAX_PLAYERS = 6


@dataclass
class PlayerBuffer:
    ts: Deque[float]
    hrs: Deque[float]
    edas: Deque[float]


class PlayerCard(QFrame):
    def __init__(self, player_id: str, accent: str) -> None:
        super().__init__()
        self.player_id = player_id
        self.setObjectName("playerCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        self.name_lbl = QLabel(player_id)
        self.name_lbl.setObjectName("nameLabel")
        self.name_lbl.setStyleSheet(f"color: {accent};")
        self.hr_lbl = QLabel("-- bpm")
        self.hr_lbl.setObjectName("hrLabel")
        top.addWidget(self.name_lbl)
        top.addStretch(1)
        top.addWidget(self.hr_lbl)
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
            self.hr_lbl.setText(f"{hrs[-1]:.0f} bpm")
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

        players_title = QLabel("Spieler")
        players_title.setObjectName("sectionTitle")
        panel_layout.addWidget(players_title)

        self.players_box = QVBoxLayout()
        self.players_box.setSpacing(8)
        panel_layout.addLayout(self.players_box)

        add_row = QHBoxLayout()
        self.add_player_btn = QPushButton("+")
        self.add_player_btn.setFixedWidth(34)
        self.add_player_btn.clicked.connect(self.add_player_field)
        add_row.addWidget(self.add_player_btn)
        add_row.addWidget(QLabel("Spieler hinzufügen (max. 6)"))
        add_row.addStretch(1)
        panel_layout.addLayout(add_row)

        panel_layout.addStretch(1)

        data_row = QHBoxLayout()
        data_row.addWidget(QLabel("Datenquelle:"))
        self.mock_radio = QRadioButton("Mock Data")
        self.live_radio = QRadioButton("Live Data")
        self.mock_radio.setChecked(True)

        self.source_group = QButtonGroup(self)
        self.source_group.addButton(self.mock_radio)
        self.source_group.addButton(self.live_radio)

        data_row.addWidget(self.mock_radio)
        data_row.addWidget(self.live_radio)
        data_row.addStretch(1)
        panel_layout.addLayout(data_row)

        root.addWidget(panel, 1)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primaryBtn")
        root.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.player_edits: List[QLineEdit] = []
        self.add_player_field("Player 1")

    def add_player_field(self, default_text: str | None = None) -> None:
        if len(self.player_edits) >= MAX_PLAYERS:
            return
        idx = len(self.player_edits) + 1
        edit = QLineEdit()
        edit.setPlaceholderText(f"Player {idx}")
        if default_text:
            edit.setText(default_text)
        self.player_edits.append(edit)
        self.players_box.addWidget(edit)

        self.add_player_btn.setEnabled(len(self.player_edits) < MAX_PLAYERS)

    def get_config(self) -> Tuple[str, str, List[str]]:
        mode = self.mode_combo.currentText()
        source = "live" if self.live_radio.isChecked() else "mock"

        players: List[str] = []
        for i, edit in enumerate(self.player_edits, start=1):
            name = edit.text().strip()
            players.append(name or f"Player {i}")

        return mode, source, players


class DashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.provider: DataProvider | None = None
        self.players: List[str] = []
        self.cards: Dict[str, PlayerCard] = {}
        self.buffers: Dict[str, PlayerBuffer] = {}

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
        self.grid.setSpacing(20)
        root.addLayout(self.grid, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self, mode: str, source: str, players: List[str]) -> None:
        self.timer.stop()
        self._clear_grid()

        self.players = players
        self.provider = MockProvider(players) if source == "mock" else LiveHubProvider(players)

        source_text = "Mock Data" if source == "mock" else "Live Data (placeholder)"
        self.subtitle.setText(f"{mode} Mode • Live HR + EDA")
        self.status.setText(f"Data source: {source_text}")

        self.buffers = {
            p: PlayerBuffer(deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS))
            for p in players
        }

        colors = ["#f7c948", "#ff7f7f", "#8ce99a", "#9ecbff", "#f4a6ff", "#ffd8a8"]
        self.cards = {}

        for i, p in enumerate(players):
            card = PlayerCard(p, colors[i % len(colors)])
            self.cards[p] = card
            r, c = divmod(i, 3)
            self.grid.addWidget(card, r, c)

        self.timer.start(200)

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _tick(self) -> None:
        if self.provider is None:
            return

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
        self.resize(1600, 950)

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
            QFrame#playerCard {
                background: #121a32;
                border: 1px solid #223156;
                border-radius: 12px;
                min-height: 240px;
                max-height: 320px;
            }
            QLabel#nameLabel {
                font-weight: 800;
                font-size: 18px;
            }
            QLabel#hrLabel {
                font-weight: 700;
                font-size: 21px;
            }
            """
        )

    def _start_game(self) -> None:
        mode, source, players = self.start_screen.get_config()
        if not players:
            QMessageBox.warning(self, "Fehlende Spieler", "Bitte mindestens einen Spieler anlegen.")
            return

        self.dashboard.start(mode, source, players)
        self.stack.setCurrentWidget(self.dashboard)

    def _back_to_start(self) -> None:
        self.dashboard.timer.stop()
        self.stack.setCurrentWidget(self.start_screen)


def build_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    pg.setConfigOptions(antialias=True)

    window = MainWindow()
    window.show()
    app._main_window = window
    return app
