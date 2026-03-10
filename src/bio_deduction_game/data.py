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

    def _stream_score(self, stream) -> int:
        try:
            name = (stream.name() or "").lower()
        except Exception:
            name = ""
        try:
            stype = (stream.type() or "").lower()
        except Exception:
            stype = ""

        score = 0
        if "opensignals" in name:
            score += 5
        if "bio" in stype:
            score += 3
        if "ecg" in stype:
            score += 2
        return score

    def _stream_label(self, stream) -> str:
        bits: List[str] = []
        for getter in ("name", "type", "source_id"):
            fn = getattr(stream, getter, None)
            if callable(fn):
                try:
                    v = fn()
                    if v:
                        bits.append(str(v))
                except Exception:
                    pass
        if not bits:
            return "unknown-stream"
        return " / ".join(bits)

    def _run_worker(self) -> None:
        try:
            import pylsl  # type: ignore

            self._backend_name = "pylsl"
        except Exception:
            self._backend_name = "none"
            self.status = "pylsl not installed"
            return

        self.status = "searching LSL streams"

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

        ranked = sorted(streams, key=self._stream_score, reverse=True)

        max_channel_needed = 0
        for a in self.assignments:
            max_channel_needed = max(max_channel_needed, a.channel_ekg, a.channel_eda)

        combined = None
        for s in ranked:
            try:
                ch = int(s.channel_count())
            except Exception:
                ch = 0
            if ch >= max_channel_needed and max_channel_needed > 0:
                combined = s
                break

        if combined is not None:
            try:
                inlet = pylsl.StreamInlet(combined, max_buflen=10)
            except Exception as e:
                self.status = f"failed to open LSL inlet: {e}"
                return

            self.status = f"streaming combined LSL: {self._stream_label(combined)}"

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
                    self._consume_combined_frame([float(x) for x in analog], now)
            return

        # Fallback: map one LSL stream per player assignment (single-channel mode).
        player_assignments = list(self.assignments)
        if not player_assignments:
            self.status = "no player assignments"
            return

        usable = []
        for s in ranked:
            try:
                ch = int(s.channel_count())
            except Exception:
                ch = 0
            if ch in (1, 2):
                usable.append(s)

        if len(usable) < len(player_assignments):
            self.status = (
                f"found {len(usable)} single-channel stream(s), need {len(player_assignments)}"
            )
            return

        inlets = []
        mapped_labels: List[str] = []
        for a, s in zip(player_assignments, usable):
            try:
                inlet = pylsl.StreamInlet(s, max_buflen=10)
            except Exception as e:
                self.status = f"failed to open stream for {a.player_name}: {e}"
                return
            inlets.append((a, inlet, s))
            mapped_labels.append(f"{a.player_name}←{self._stream_label(s)}")

        self.status = "streaming per-player LSL: " + " | ".join(mapped_labels)

        while not self._stop:
            had_data = False
            for a, inlet, _s in inlets:
                try:
                    chunk, ts = inlet.pull_chunk(timeout=0.0, max_samples=32)
                except Exception:
                    continue

                if not chunk:
                    continue

                had_data = True
                for analog, t in zip(chunk, ts):
                    now = float(t) if t else time.time()
                    self._consume_single_stream_frame(a, [float(x) for x in analog], now)

            if not had_data:
                time.sleep(0.02)

    def _consume_single_stream_frame(self, assignment: PlayerAssignment, analog: List[float], now: float) -> None:
        if not analog:
            return

        # OpenSignals single-channel LSL is commonly [counter, signal].
        ecg = float(analog[-1])
        hr = self._estimate_hr(assignment.player_name, ecg, now)

        with self._lock:
            self._samples[assignment.player_name] = Sample(t=now, hr=hr, eda=0.0)

    def _consume_combined_frame(self, analog: List[float], now: float) -> None:
        if not analog:
            return

        for a in self.assignments:
            i_ecg = a.channel_ekg - 1
            i_eda = a.channel_eda - 1 if a.channel_eda > 0 else None

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
