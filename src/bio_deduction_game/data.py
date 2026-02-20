from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import random
import time


@dataclass
class Sample:
    t: float
    hr: float
    eda: float


class DataProvider:
    """Interface for biosignal providers."""

    def get_samples(self) -> Dict[str, Sample]:
        raise NotImplementedError


class MockProvider(DataProvider):
    """Demo provider with plausible-looking values for UI development."""

    def __init__(self, player_ids: List[str]) -> None:
        self.player_ids = player_ids
        self.hr_base = {pid: random.uniform(68, 90) for pid in player_ids}
        self.eda_base = {pid: random.uniform(1.0, 6.0) for pid in player_ids}

    def get_samples(self) -> Dict[str, Sample]:
        now = time.time()
        out: Dict[str, Sample] = {}

        for pid in self.player_ids:
            self.hr_base[pid] += random.uniform(-0.8, 0.8)
            self.hr_base[pid] = max(50.0, min(130.0, self.hr_base[pid]))

            self.eda_base[pid] += random.uniform(-0.12, 0.12)
            self.eda_base[pid] = max(0.1, min(20.0, self.eda_base[pid]))

            hr = self.hr_base[pid] + random.uniform(-1.5, 1.5)
            eda = self.eda_base[pid] + random.uniform(-0.2, 0.2)

            out[pid] = Sample(t=now, hr=hr, eda=eda)

        return out


class LiveHubProvider(DataProvider):
    """Placeholder for future OpenSignals Hub integration.

    Intentionally returns no samples until live integration is implemented.
    """

    def __init__(self, player_ids: List[str]) -> None:
        self.player_ids = player_ids

    def get_samples(self) -> Dict[str, Sample]:
        return {}
