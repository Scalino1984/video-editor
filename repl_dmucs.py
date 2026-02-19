#!/usr/bin/env python3
import os
import sys
import time
import replicate

def main() -> int:
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        print("REPLICATE_API_TOKEN fehlt in der Umgebung.", file=sys.stderr)
        return 2

    client = replicate.Client(api_token=token)

    audio_path = "sonnensturm.mp3"
    if not os.path.isfile(audio_path):
        print(f"Datei nicht gefunden: {audio_path}", file=sys.stderr)
        return 2

    # Model-Version wie bei dir
    version = "ryan5453/demucs:5a7041cc9b82e5a558fea6b3d7b12dea89625e89da33f0447bd727c2d0ab9e77"

    with open(audio_path, "rb") as f:
        prediction = client.predictions.create(
            version=version,
            input={
                "audio": f,              # lokale Datei -> Client macht Upload
                "model": "htdemucs",
                "stem": "none",
                "output_format": "mp3",
                "split": True,
                "shifts": 1,
                "overlap": 0.25,
                "clip_mode": "rescale",
                "mp3_preset": 2,
                "mp3_bitrate": 320,
                "wav_format": "int24",
                "jobs": 0
            },
        )

    # Polling bis fertig
    while prediction.status not in ("succeeded", "failed", "canceled"):
        time.sleep(2)
        prediction = client.predictions.get(prediction.id)
        print(f"{prediction.status} …", file=sys.stderr)

    if prediction.status != "succeeded":
        print(f"Prediction fehlgeschlagen: {prediction.error}", file=sys.stderr)
        return 1

    print(prediction.output)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
