import sys

import whisper

audio = sys.argv[1]
model = whisper.load_model("base.en", device="cuda")
result = model.transcribe(audio, fp16=True, verbose=False)
for segment in result.get("segments", []):
    print(f"[{segment['start']:6.1f}] {segment['text'].strip()}", flush=True)
