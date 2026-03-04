from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Thread
from typing import Callable, Dict, List, Optional
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
    source_name: str = "unknown"

    def get_samples(self) -> Dict[str, Sample]:
        raise NotImplementedError

    def close(self) -> None:
        return


class MockProvider(DataProvider):
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

            out[pid] = Sample(
                t=now,
                hr=self.hr_base[pid] + random.uniform(-1.5, 1.5),
                eda=self.eda_base[pid] + random.uniform(-0.2, 0.2),
            )
        return out


class LiveHubProvider(DataProvider):
    """Concrete live approach via biosignalsplux (best-effort, version-tolerant).

    - Expects OpenSignals/BioPlux stack available on the machine.
    - Uses fixed channel mapping from PlayerAssignment.
    - Internally derives HR from ECG channel (simple peak detector placeholder).
    """

    source_name = "Live Data"

    def __init__(self, assignments: List[PlayerAssignment], sampling_rate: int = 1000) -> None:
        self.assignments = assignments
        self.sampling_rate = sampling_rate
        self._samples: Dict[str, Sample] = {}
        self._lock = Lock()

        self._last_ecg: Dict[str, float] = {}
        self._last_peak_ts: Dict[str, float] = {}
        self._hr: Dict[str, float] = {}

        self._stop = False
        self._worker: Optional[Thread] = None

        self._backend_name = "none"
        self.status = "idle"

        self._start_worker()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def _start_worker(self) -> None:
        self._worker = Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def _run_worker(self) -> None:
        try:
            import biosignalsplux as bsp  # type: ignore

            self._backend_name = "biosignalsplux"
        except Exception:
            self._backend_name = "none"
            self.status = "biosignalsplux not installed"
            return

        self.status = "connecting"

        per_hub: Dict[str, List[PlayerAssignment]] = {}
        for a in self.assignments:
            per_hub.setdefault(a.hub_mac, []).append(a)

        hub_threads: List[Thread] = []
        for hub_mac, hub_assignments in per_hub.items():
            t = Thread(target=self._run_single_hub, args=(bsp, hub_mac, hub_assignments), daemon=True)
            hub_threads.append(t)
            t.start()

        self.status = "streaming"
        while not self._stop:
            time.sleep(0.2)

    def _run_single_hub(self, bsp, hub_mac: str, assignments: List[PlayerAssignment]) -> None:
        # This adapter intentionally tries several common API variants because
        # biosignalsplux distributions differ between OS/versions.
        device = None

        class _CallbackDevice(getattr(bsp, "Device", object)):  # type: ignore[misc]
            def __init__(self, *args, on_frame: Callable[[List[float]], None], **kwargs):
                self._on_frame = on_frame
                super().__init__(*args, **kwargs)

            def onRawFrame(self, *args):  # noqa: N802
                analog: Optional[List[float]] = None
                for arg in reversed(args):
                    if isinstance(arg, (list, tuple)) and len(arg) > 0:
                        try:
                            analog = [float(x) for x in arg]
                            break
                        except Exception:
                            continue
                if analog is not None:
                    self._on_frame(analog)
                return True

        def on_frame(analog: List[float]) -> None:
            now = time.time()
            for a in assignments:
                i_ecg = a.channel_ekg - 1
                i_eda = a.channel_eda - 1 if a.channel_eda > 0 else None
                if i_ecg >= len(analog):
                    continue

                ecg = float(analog[i_ecg])
                eda = float(analog[i_eda]) if i_eda is not None and i_eda < len(analog) else 0.0
                hr = self._estimate_hr(a.player_name, ecg, now)

                with self._lock:
                    self._samples[a.player_name] = Sample(t=now, hr=hr, eda=eda)

        try:
            if hasattr(bsp, "Device"):
                device = _CallbackDevice(hub_mac, on_frame=on_frame)
            else:
                self.status = "biosignalsplux Device class missing"
                return

            if hasattr(device, "open"):
                device.open()

            started = False
            for args in [
                (self.sampling_rate, 0xFF, 16),
                (self.sampling_rate, 0xFF),
                (self.sampling_rate,),
            ]:
                try:
                    device.start(*args)
                    started = True
                    break
                except Exception:
                    continue

            if not started:
                self.status = f"failed to start hub {hub_mac}"
                return

            while not self._stop:
                if hasattr(device, "loop"):
                    try:
                        device.loop()
                    except Exception:
                        time.sleep(0.01)
                else:
                    time.sleep(0.02)

        except Exception as e:
            self.status = f"hub {hub_mac} error: {e}"
        finally:
            if device is not None:
                for m in ("stop", "close", "disconnect"):
                    if hasattr(device, m):
                        try:
                            getattr(device, m)()
                        except Exception:
                            pass

    def _estimate_hr(self, player: str, ecg: float, ts: float) -> float:
        prev = self._last_ecg.get(player, ecg)
        self._last_ecg[player] = ecg

        threshold = 0.65 * max(1.0, abs(prev))
        rising = ecg > threshold and prev <= threshold

        if rising:
            last_peak = self._last_peak_ts.get(player)
            if last_peak is not None:
                rr = ts - last_peak
                if 0.35 <= rr <= 1.5:
                    inst_hr = 60.0 / rr
                    old = self._hr.get(player, inst_hr)
                    self._hr[player] = old * 0.7 + inst_hr * 0.3
            self._last_peak_ts[player] = ts

        return self._hr.get(player, 0.0)

    def get_samples(self) -> Dict[str, Sample]:
        with self._lock:
            return dict(self._samples)

    def close(self) -> None:
        self._stop = True
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.5)


class OpenSignalsLSLProvider(DataProvider):
    """Live provider consuming OpenSignals streams via LSL (pylsl)."""

    source_name = "Live Data (OpenSignals LSL)"

    def __init__(self, assignments: List[PlayerAssignment]) -> None:
        self.assignments = assignments
        self._samples: Dict[str, Sample] = {}
        self._lock = Lock()

        self._last_ecg: Dict[str, float] = {}
        self._last_peak_ts: Dict[str, float] = {}
        self._hr: Dict[str, float] = {}
        self._last_counter: Optional[float] = None

        self._stop = False
        self._worker: Optional[Thread] = None

        self._backend_name = "none"
        self.status = "idle"
        self._start_worker()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def _start_worker(self) -> None:
        self._worker = Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def _run_worker(self) -> None:
        try:
            import pylsl  # type: ignore

            self._backend_name = "pylsl"
        except Exception:
            self._backend_name = "none"
            self.status = "pylsl not installed"
            return

        self.status = "searching LSL stream"

        streams = []
        try:
            streams = pylsl.resolve_byprop("name", "OpenSignals", timeout=2)
        except Exception:
            streams = []

        if not streams:
            try:
                streams = pylsl.resolve_streams(wait_time=2)
            except Exception:
                streams = []

        if not streams:
            self.status = "no LSL streams found"
            return

        selected = streams[0]
        for s in streams:
            try:
                name = (s.name() or "").lower()
                stype = (s.type() or "").lower()
                if "opensignals" in name or "biosignal" in stype or "ecg" in stype:
                    selected = s
                    break
            except Exception:
                continue

        try:
            inlet = pylsl.StreamInlet(selected, max_buflen=10)
        except Exception as e:
            self.status = f"failed to open LSL inlet: {e}"
            return

        try:
            self.status = f"streaming LSL: {selected.name()}"
        except Exception:
            self.status = "streaming LSL"

        while not self._stop:
            try:
                chunk, ts = inlet.pull_chunk(timeout=0.2, max_samples=64)
            except Exception as e:
                self.status = f"LSL read error: {e}"
                time.sleep(0.2)
                continue

            if not chunk:
                continue

            for analog, t in zip(chunk, ts):
                now = float(t) if t else time.time()
                self._consume_frame([float(x) for x in analog], now)

    def _consume_frame(self, analog: List[float], now: float) -> None:
        if not analog:
            return

        # OpenSignals LSL often sends [counter, signal] for single-channel streams.
        # Detect this layout and map ECG to channel 2 while forcing EDA to 0.
        ecg_idx_override: Optional[int] = None
        eda_idx_override: Optional[int] = None

        if len(analog) == 2:
            first = float(analog[0])
            second = float(analog[1])
            if self._last_counter is None:
                self._last_counter = first
            else:
                delta = first - self._last_counter
                self._last_counter = first
                if 0.5 <= delta <= 5.0 and abs(second) < 20_000:
                    ecg_idx_override = 1
                    eda_idx_override = None

        for a in self.assignments:
            # Single-signal OpenSignals layout ([counter, signal]) represents one
            # physical channel only. In that case map data to slot-1 players only
            # (CH1 on each hub mapping) and skip higher slots.
            if ecg_idx_override is not None and a.channel_ekg != 1:
                continue

            i_ecg = ecg_idx_override if ecg_idx_override is not None else (a.channel_ekg - 1)
            if eda_idx_override is not None:
                i_eda = eda_idx_override
            elif a.channel_eda > 0:
                i_eda = a.channel_eda - 1
            else:
                i_eda = None

            if i_ecg >= len(analog):
                continue

            ecg = float(analog[i_ecg])
            eda = float(analog[i_eda]) if i_eda is not None and i_eda < len(analog) else 0.0
            hr = self._estimate_hr(a.player_name, ecg, now)

            with self._lock:
                self._samples[a.player_name] = Sample(t=now, hr=hr, eda=eda)

    def _estimate_hr(self, player: str, ecg: float, ts: float) -> float:
        prev = self._last_ecg.get(player, ecg)
        self._last_ecg[player] = ecg

        threshold = 0.65 * max(1.0, abs(prev))
        rising = ecg > threshold and prev <= threshold

        if rising:
            last_peak = self._last_peak_ts.get(player)
            if last_peak is not None:
                rr = ts - last_peak
                if 0.35 <= rr <= 1.5:
                    inst_hr = 60.0 / rr
                    old = self._hr.get(player, inst_hr)
                    self._hr[player] = old * 0.7 + inst_hr * 0.3
            self._last_peak_ts[player] = ts

        return self._hr.get(player, 0.0)

    def get_samples(self) -> Dict[str, Sample]:
        with self._lock:
            return dict(self._samples)

    def close(self) -> None:
        self._stop = True
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.5)


def discover_connected_hubs() -> List[str]:
    """Best-effort OpenSignals/BioPlux hub discovery.

    Tries common biosignalsplux scan/discovery entry points.
    """

    try:
        import biosignalsplux as bsp  # type: ignore
    except Exception:
        return []

    candidates = ["discover", "scan", "search", "find", "find_devices", "discoverDevices"]
    for name in candidates:
        fn = getattr(bsp, name, None)
        if not callable(fn):
            continue
        try:
            result = fn()
        except Exception:
            continue

        hubs: List[str] = []
        if isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str):
                    hubs.append(item)
                else:
                    mac = getattr(item, "mac", None) or getattr(item, "address", None)
                    if mac:
                        hubs.append(str(mac))
        if hubs:
            return hubs[:2]

    return []


def build_assignments(players: List[str], hub_macs: List[str], include_eda: bool = True) -> List[PlayerAssignment]:
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

        assignments.append(
            PlayerAssignment(
                player_name=player,
                hub_mac=hub,
                channel_ekg=slot * 2 + 1,
                channel_eda=(slot * 2 + 2) if include_eda else 0,
            )
        )
        per_hub[hub] += 1

    return assignments
