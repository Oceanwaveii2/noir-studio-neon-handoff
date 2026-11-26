import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')

from prose_engine.voice.slop import flag
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer

for label, filename in [("RAW", "work/americandad/foxy_spring_breakup_raw.md"),
                        ("CORRECTED", "work/americandad/foxy_spring_breakup_corrected.md")]:
    text = Path(filename).read_text(encoding='utf-8')
    paras = [p.strip() for p in text.split('\n\n') if p.strip()]

    total_slop = 0
    total_diag = 0
    for p in paras:
        flags = flag(p)
        diag = ProseDiagnosticsAnalyzer.analyze(p)
        total_slop += len(flags)
        total_diag += len(diag.warnings)

    print(f"=== {label} ===")
    print(f"Paragraphs: {len(paras)}")
    print(f"Total Slop Flags: {total_slop}")
    print(f"Total Diagnostics Warnings: {total_diag}")
