# save as inspect_lsl.py
from pylsl import resolve_streams, StreamInlet

print("Suche LSL-Streams...")
streams = resolve_streams(wait_time=5)

if not streams:
    print("Keine LSL-Streams gefunden.")
    raise SystemExit(1)

for i, s in enumerate(streams):
    try:
        print(
            f"\n[{i}] name={s.name()} | type={s.type()} | ch={s.channel_count()} "
            f"| srate={s.nominal_srate()} | format={s.channel_format()} | source_id={s.source_id()}"
        )
    except Exception as e:
        print(f"[{i}] Fehler beim Lesen von Stream-Info: {e}")

print("\n--- Detail je Stream ---")

for i, s in enumerate(streams):
    print(f"\n===== STREAM {i}: {s.name()} =====")

    info = s.as_xml()
    print("XML (erste ~2000 Zeichen):")
    print(info[:2000])

    inlet = StreamInlet(s, max_buflen=5)
    print("Ziehe 3 Samples...")

    got = 0
    while got < 3:
        sample, ts = inlet.pull_sample(timeout=2.0)

        if sample is None:
            print(" timeout (kein Sample)")
            continue

        print(f" sample[{got}] @ {ts}: len={len(sample)} -> {sample}")
        got += 1