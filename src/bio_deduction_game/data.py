from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import random
import time


@dataclass
class Sample:
    t: float
    hr: float
    eda: float


@dataclass
class PlayerAssignment:
    player_name: str
    hub_mac: str
    channel_ekg: int
    channel_eda: int


class DataProvider:
    """Interface for biosignal providers."""

    source_name: str = "unknown"

    def get_samples(self) -> Dict[str, Sample]:
        raise NotImplementedError


class MockProvider(DataProvider):
    """Demo provider with plausible-looking values for UI development."""

    source_name = "Mock Data"

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
    """OpenSignals Hub live provider scaffold.

    Notes:
    - Discovery and low-level streaming differ by OpenSignals setup/version.
    - This class is intentionally structured for real integration and currently
      returns empty samples when no backend is wired.
    """

    source_name = "Live Data"

    def __init__(self, assignments: List[PlayerAssignment]) -> None:
        self.assignments = assignments
        self._backend_name = self._detect_backend()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def _detect_backend(self) -> str:
        try:
            import biosignalsplux  # type: ignore  # noqa: F401

            return "biosignalsplux"
        except Exception:
            return "none"

    def get_samples(self) -> Dict[str, Sample]:
        # TODO: Implement real stream ingestion from OpenSignals Hub.
        # Expected mapping per player on each hub:
        #   1=Player1_EKG, 2=Player1_EDA, 3=Player2_EKG, 4=Player2_EDA,
        #   5=Player3_EKG, 6=Player3_EDA, 7=Player4_EKG, 8=Player4_EDA
        return {}


def discover_connected_hubs() -> List[str]:
    """Best-effort hub discovery scaffold.

    Returns a list of connected hub identifiers (MACs preferred).
    Currently supports manual fallback only; auto-discovery hook is prepared.
    """

    auto: List[str] = []

    # Future: try OpenSignals SDK discovery API here when available.
    if auto:
        return auto[:2]

    return []


def build_assignments(players: List[str], hub_macs: List[str]) -> List[PlayerAssignment]:
    """Distribute players across hubs and map fixed channel pairs.

    Channel layout per hub:
      1/2 -> player1 EKG/EDA
      3/4 -> player2 EKG/EDA
      5/6 -> player3 EKG/EDA
      7/8 -> player4 EKG/EDA
    """

    hubs = [h.strip() for h in hub_macs if h.strip()][:2]
    if not hubs:
        return []

    assignments: List[PlayerAssignment] = []
    per_hub: Dict[str, int] = {h: 0 for h in hubs}

    for idx, player in enumerate(players):
        hub = hubs[idx % len(hubs)]
        slot = per_hub[hub]
        if slot >= 4:
            continue

        ekg_ch = slot * 2 + 1
        eda_ch = slot * 2 + 2
        assignments.append(
            PlayerAssignment(
                player_name=player,
                hub_mac=hub,
                channel_ekg=ekg_ch,
                channel_eda=eda_ch,
            )
        )
        per_hub[hub] += 1

    return assignments
