import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')

from prose_engine.voice.slop import flag
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer

text = Path('work/americandad/foxy_spring_breakup_raw.md').read_text(encoding='utf-8')
paras = [p.strip() for p in text.split('\n\n') if p.strip()]

total_slop = 0
for i, p in enumerate(paras):
    flags = flag(p)
    diag = ProseDiagnosticsAnalyzer.analyze(p)
    if flags or diag.warnings:
        print(f"=== Paragraph {i} ===")
        print(p[:90] + "...")
        for f in flags:
            print(f"  [SLOP] {f.rule}: {f.text} -> {f.why}")
        for w in diag.warnings:
            print(f"  [DIAG] {w}")
        total_slop += len(flags)

print(f"\nTotal slop flags: {total_slop}")
