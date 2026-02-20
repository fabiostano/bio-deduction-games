from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .data import DataProvider, Sample

WINDOW_SECONDS = 60.0
MAX_POINTS = 1200


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
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

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

        self.hr_curve = self.hr_plot.plot(pen=pg.mkPen(color=accent, width=2))
        self.eda_curve = self.eda_plot.plot(pen=pg.mkPen(color="#62d0ff", width=2))

        root.addWidget(self.hr_plot)
        root.addWidget(self.eda_plot)

    def _style_plot(self, plot: pg.PlotWidget, title: str) -> None:
        plot.setBackground("#101424")
        plot.showGrid(x=True, y=True, alpha=0.18)
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


class MainWindow(QMainWindow):
    def __init__(self, provider: DataProvider, players: List[str]) -> None:
        super().__init__()
        self.provider = provider
        self.players = players
        self.setWindowTitle("Bio Deduction Games — Generic Mode")
        self.resize(1600, 950)

        self.buffers: Dict[str, PlayerBuffer] = {
            p: PlayerBuffer(deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS), deque(maxlen=MAX_POINTS))
            for p in players
        }

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("BIO DEDUCTION GAMES")
        title.setObjectName("title")
        subtitle = QLabel("Generic Mode • Live HR + EDA")
        subtitle.setObjectName("subtitle")
        left = QVBoxLayout()
        left.addWidget(title)
        left.addWidget(subtitle)

        self.status = QLabel("Data source: MockProvider")
        self.status.setObjectName("status")
        self.fullscreen_btn = QPushButton("Toggle Fullscreen")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)

        header.addLayout(left)
        header.addStretch(1)
        header.addWidget(self.status)
        header.addWidget(self.fullscreen_btn)
        root.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(10)
        root.addLayout(grid, 1)

        colors = ["#f7c948", "#ff7f7f", "#8ce99a", "#9ecbff", "#f4a6ff", "#ffd8a8"]
        self.cards: Dict[str, PlayerCard] = {}
        for i, p in enumerate(players):
            card = PlayerCard(p, colors[i % len(colors)])
            self.cards[p] = card
            r, c = divmod(i, 3)
            grid.addWidget(card, r, c)

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
            QFrame#playerCard {
                background: #121a32;
                border: 1px solid #223156;
                border-radius: 12px;
            }
            QLabel#nameLabel {
                font-weight: 700;
                font-size: 15px;
            }
            QLabel#hrLabel {
                font-weight: 700;
                font-size: 24px;
            }
            """
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _tick(self) -> None:
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

            ts = list(b.ts)
            hrs = list(b.hrs)
            edas = list(b.edas)

            filtered: List[Tuple[float, float, float]] = [
                (t, hr, eda)
                for t, hr, eda in zip(ts, hrs, edas)
                if t >= now - WINDOW_SECONDS
            ]
            if not filtered:
                continue

            x = [t - now for (t, _, _) in filtered]
            y_hr = [hr for (_, hr, _) in filtered]
            y_eda = [eda for (_, _, eda) in filtered]

            card.update_data(x, y_hr, y_eda)


def build_app(provider: DataProvider, players: List[str]) -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))

    pg.setConfigOptions(antialias=True)

    window = MainWindow(provider, players)
    window.show()
    app._main_window = window  # keep reference
    return app
