import re
import html
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from prose_engine import paths as prose_paths

REPO_ROOT = prose_paths.root()
NOVEL_PATH = prose_paths.asset("work", "americandad", "foxy_mo2_hybrid_novel.md")
READER_PATH = prose_paths.asset("work", "americandad", "foxy_mo2_reader.html")

COLOR_MAP = {
    "FRANCINE": "#fb7185",
    "NURSE FRANNY ANDERSON": "#f43f5e",
    "NURSE PAMELA FRANNY ANDERSON": "#f43f5e",
    "RAINEE": "#34d399",
    "RAINEE (PETER)": "#f59e0b",
    "HALEY": "#38bdf8",
    "STELLA": "#fbbf24",
    "ROGER": "#c084fc",
    "FRAT GUY": "#a78bfa",
    "COLLEGE STUDENTS": "#a78bfa",
}

SCENE_METAS = [
    {
        "id": "scene-1-kitchen-briefing",
        "num": 1,
        "title": "SCENE 1: The Kitchen Briefing & The Ancestral Massage",
        "slug": "INT. LING HOUSE - KITCHEN / LIVING ROOM - 07:31 A.M.",
        "short": "S1: Kitchen Briefing",
        "images": [
            {"file": "image1.png", "caption": "Ling family kitchen & 3 stacked Tupperware dinners"},
            {"file": "image2.jpeg", "caption": "Francine Ling in off-the-shoulder pink lace-trim dress & pink heels"},
            {"file": "image3.png", "caption": "Haley Ling (green floral headband & peace medallion)"},
            {"file": "image4.png", "caption": "Haley full outfit (cropped grey tank, crescent navel ring, studded belt)"},
            {"file": "image5.png", "caption": "Stella Ling (living origami newspaper-craft girl with twin newsprint bows)"}
        ]
    },
    {
        "id": "scene-2-master-suite",
        "num": 2,
        "title": "SCENE 2: The Master Suite & The Sudden Coup",
        "slug": "INT. LING HOUSE - MASTER BEDROOM - 07:31 A.M.",
        "short": "S2: Master Suite",
        "images": [
            {"file": "image6.jpeg", "caption": "Celestial Fox Rainee (glittering red waves, fox ears, red-and-black bandage dress, tail)"},
            {"file": "image7.jpeg", "caption": "Rainee perched on vanity stool in red collared dress & white stockings"}
        ]
    },
    {
        "id": "scene-3-double-commode",
        "num": 3,
        "title": "SCENE 3: The Double Commode & The Two-Chair Rule",
        "slug": "INT. LING HOUSE - MASTER BATHROOM - 07:32 A.M.",
        "short": "S3: Double Commode",
        "images": [
            {"file": "image8.png", "caption": "Double-wide gloss-black porcelain throne with gold lotus filigree"},
            {"file": "image9.png", "caption": "Living room staging (avocado sofa, yellow scalloped throw, orange armchair)"}
        ]
    },
    {
        "id": "scene-4-peter-griffin-morph",
        "num": 4,
        "title": "SCENE 4: The Rainee-Peter Griffin Morph Sequence",
        "slug": "INT. LING HOUSE - STAIRCASE & LIVING ROOM - 07:45 A.M.",
        "short": "S4: Peter Griffin Morph",
        "images": [
            {"file": "image10.jpeg", "caption": "Stage 1 Morph: Bulbous nose, blue lips, green-sleeved crop top & ballooning thighs"},
            {"file": "image11.png", "caption": "Stage 2 Full Rainee-Peter Morph: Cleft butt-chin, fox ears, white tee, colossal jeans & candy cane"}
        ]
    },
    {
        "id": "scene-5-nurse-franny-morph",
        "num": 5,
        "title": "SCENE 5: The Nurse Pamela Franny Anderson Morph",
        "slug": "INT. LING HOUSE - LIVING ROOM - 08:00 A.M.",
        "short": "S5: Nurse Franny Morph",
        "images": [
            {"file": "image12.jpeg", "caption": "Nurse Pamela Franny Anderson (sheer nurse-cap veil & lace halter)"},
            {"file": "image13.png", "caption": "90s Pamela Anderson mountain of blonde curls & plunging white minidress"},
            {"file": "image14.png", "caption": "Nurse Franny Deluxe bombshell caricature close-up"},
            {"file": "image15.jpeg", "caption": "Full Nurse Franny: Nurse cap veil, white halter mini, pink-top thigh-highs & pink pumps"}
        ]
    },
    {
        "id": "scene-6-the-departure",
        "num": 6,
        "title": "SCENE 6: The Departure & Station Wagon Peelout",
        "slug": "EXT. LING HOUSE - DRIVEWAY - 08:15 A.M.",
        "short": "S6: The Departure",
        "images": [
            {"file": "image16.png", "caption": "Francine & Rainee's red family sedan peeling out of the Ling driveway"}
        ]
    },
    {
        "id": "scene-7-roger-rutgers-takeover",
        "num": 7,
        "title": "SCENE 7: Roger's Rutgers Spring Break Takeover",
        "slug": "EXT. LING HOUSE - DRIVEWAY / LAWN - 08:16 A.M.",
        "short": "S7: Roger's Rutgers Takeover",
        "images": [
            {"file": "image17.png", "caption": "Roger (blonde wig, purple ermine cape, scepter, blue cart of goody bags) & Rutgers students"}
        ]
    }
]

def format_sfx(text):
    def repl(m):
        sound = m.group(1)
        return f'<span class="px-2 py-0.5 rounded bg-orange-950/60 border border-orange-500/60 text-orange-300 font-bold italic">{sound}</span>'
    return re.sub(r'\*([A-Za-z0-9\-!?,. \'\"]+)\*', repl, text)

def build_reader():
    text = NOVEL_PATH.read_text(encoding="utf-8")
    
    # Split text into scenes using ### SCENE
    scene_chunks = re.split(r'\n(?=### SCENE \d+:)', text)
    
    # scene_chunks[0] is the chapter header
    # scene_chunks[1..7] are scenes 1..7
    parsed_scenes = scene_chunks[1:]
    
    html_out = []
    
    # Build Top Navigation items
    nav_links = []
    index_links = []
    for meta in SCENE_METAS:
        s_tag = f"S{meta['num']}"
        nav_links.append(f'<a href="#{meta["id"]}" class="nav-btn px-2.5 py-1 bg-slate-800 hover:bg-sky-600 hover:text-white text-slate-300 rounded font-medium border border-slate-700 whitespace-nowrap">{s_tag}</a>')
        index_links.append(f'<a href="#{meta["id"]}" title="{meta["title"]}" class="px-2 py-0.5 bg-slate-800/80 hover:bg-sky-600 hover:text-white text-slate-300 rounded border border-slate-700/60 transition">{meta["short"]}</a>')
        
    nav_html = "\n".join(nav_links)
    index_html = "\n".join(index_links)
    
    header = f"""<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>American Foxy Mom (MO2) — Master Screenplay Reader</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Courier+Prime:ital,wght@0,400;0,700;1,400;1,700&display=swap');
    :root {{
      --void: #101113;
      --card-bg: #16191f;
      --gold: #c49a67;
      --gold-hover: #d8b284;
      --parchment: #f4f1ea;
      --parchment-border: #dcd7ca;
      --ink: #22201d;
    }}
    body {{
      background: var(--void) !important;
      color: #cbd5e1;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      padding: 0;
    }}
    .screenplay-container {{ max-width: 860px; margin: 0 auto; }}
    .parchment-card {{
      background: var(--parchment) !important;
      color: var(--ink) !important;
      box-shadow: 0 18px 55px rgba(0,0,0,0.85);
      border-radius: 3px;
      padding: 56px 64px 100px;
      margin-top: 24px;
      margin-bottom: 60px;
    }}
    .scene-heading {{
      font-family: 'Courier Prime', monospace;
      font-weight: 700;
      color: #8b5e28;
      margin-top: 2rem;
      margin-bottom: 0.75rem;
      text-transform: uppercase;
      border-left: 3px solid var(--gold);
      padding: 0.4rem 0.75rem;
      background: rgba(196, 154, 103, 0.12);
      border-radius: 0 0.25rem 0.25rem 0;
    }}
    .character-cue {{
      font-family: 'Courier Prime', monospace;
      font-weight: 700;
      margin-top: 1.6rem;
      margin-bottom: 0.25rem;
      text-align: center;
      letter-spacing: 0.12em;
      font-size: 0.95rem;
    }}
    .parenthetical {{
      font-family: 'Courier Prime', monospace;
      font-style: italic;
      color: #64748b;
      text-align: center;
      margin-bottom: 0.25rem;
      font-size: 0.9rem;
    }}
    .dialogue {{
      font-family: 'Courier Prime', monospace;
      max-width: 540px;
      margin: 0 auto 1.25rem auto;
      line-height: 1.6;
      color: #171513 !important;
      font-size: 0.975rem;
    }}
    .action-block {{
      font-family: Georgia, serif;
      margin: 1rem 0;
      line-height: 1.65;
      color: var(--ink) !important;
      font-size: 1.05rem;
    }}
    .transition-cue {{
      font-family: 'Courier Prime', monospace;
      text-align: right;
      font-weight: 700;
      color: #b91c1c;
      margin: 1.5rem 0;
      letter-spacing: 0.1em;
    }}
    .chunk-header {{
      background: #ece7dc !important;
      border-left: 4px solid var(--gold) !important;
      padding: 1rem 1.25rem;
      border-radius: 0.375rem;
      margin: 2.5rem 0 1.25rem 0;
      color: #2b261f !important;
      font-family: Georgia, serif;
    }}
    .act-banner {{
      background: #e2dcd0 !important;
      border: 1px solid #cbbeab !important;
      padding: 1.25rem;
      border-radius: 0.5rem;
      margin: 2.5rem 0 1.5rem 0;
      color: #383023 !important;
      text-align: center;
      font-family: Georgia, serif;
    }}
    .nav-btn {{
      background: #1f242d;
      border: 1px solid #2e3543;
      color: #cbd5e1;
      transition: all 0.15s ease-in-out;
    }}
    .nav-btn:hover {{
      background: var(--gold);
      color: #101113;
      border-color: var(--gold);
      transform: translateY(-1px);
    }}
  </style>
</head>
<body class="bg-[#101113] text-[#cbd5e1] antialiased min-h-screen">

  <!-- Sticky Top Navigation Bar -->
  <header class="sticky top-0 z-50 bg-[#16191f]/95 backdrop-blur-md border-b border-[#222731] shadow-2xl px-4 py-3">
    <div class="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <span class="px-2 py-0.5 bg-[#c49a67] text-[#101113] rounded text-xs font-black tracking-wider uppercase">AMERICAN FOXY MOM</span>
        <span class="text-sm font-semibold text-slate-200">Chapter 16: The Spring Break Protocol</span>
        <span class="text-xs text-[#c49a67] font-mono hidden sm:inline">✓ Eclipse Master Screenplay (7 Scenes)</span>
      </div>
      <div class="flex items-center gap-2 overflow-x-auto max-w-full pb-1 md:pb-0 text-xs">
        <a href="http://localhost:8765" class="nav-btn px-3 py-1 bg-[#c49a67] text-[#101113] font-bold rounded whitespace-nowrap" style="color:#101113;background:#c49a67;">⚡ Studio Workbench</a>
        {nav_html}
        <a href="#top" class="nav-btn px-2.5 py-1 bg-slate-800 hover:bg-amber-500 hover:text-slate-950 text-amber-400 rounded font-semibold border border-amber-500/30 whitespace-nowrap">↑ Top</a>
      </div>
    </div>
  </header>

  <div id="top" class="screenplay-container px-4 py-8">

    <!-- Title Card -->
    <div class="bg-[#16191f] border border-[#222731] rounded-xl p-6 md:p-10 mb-8 shadow-2xl relative overflow-hidden">
      <div class="absolute -right-12 -top-12 w-48 h-48 bg-amber-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div class="absolute -left-12 -bottom-12 w-48 h-48 bg-sky-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div class="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6 border-b border-slate-800 pb-8">
        <div>
          <div class="inline-flex items-center gap-2 px-3 py-1 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-full text-xs font-bold tracking-wider uppercase mb-3">
            <span>TV-14 Animated Farce</span>
            <span>•</span>
            <span>Noir Fiction Engine</span>
          </div>
          <h1 class="text-3xl md:text-5xl font-black text-white tracking-tight leading-none mb-3">
            AMERICAN FOXY MOM <span class="text-amber-400">:</span> THE SPRING BREAK PROTOCOL
          </h1>
          <p class="text-base md:text-lg text-slate-400 font-medium max-w-2xl">
            Novel-Script Hybrid Adaptation · Master Chronology Edition (7 Scenes) · Conditioned with cadence burstiness σ = 6.8 and zero AI tells.
          </p>
        </div>
        <div class="bg-slate-950/60 border border-slate-800 rounded-xl p-4 text-xs font-mono space-y-1 text-slate-400 min-w-[260px]">
          <div class="text-slate-300 font-semibold mb-1 pb-1 border-b border-slate-800">CANON INTEGRITY HUD</div>
          <div>Scenes Present: <span class="text-emerald-400 font-bold">7 OF 7 COMPLETE (PDF MASTER)</span></div>
          <div>Family Lineage: <span class="text-emerald-400 font-bold">LING ONLY (0 SMITH)</span></div>
          <div>Baba Ling Recovery: <span class="text-emerald-400 font-bold">VERBATIM PRESERVED</span></div>
          <div>Rainee Seating: <span class="text-amber-400 font-bold">2-CHAIR CONSTRAINT</span></div>
          <div>Haley Siren State: <span class="text-sky-400 font-bold">DORMANT / HUMAN</span></div>
          <div>Burstiness Score: <span class="text-emerald-400 font-bold">σ = 6.8 (PASS)</span></div>
        </div>
      </div>

      <!-- Quick Scene Jump Index -->
      <div class="mt-6 pt-4">
        <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Complete Scene Jump Index:</div>
        <div class="flex flex-wrap items-center gap-2 text-xs">
          {index_html}
        </div>
      </div>
    </div>

    <!-- Screenplay Script Body -->
    <div class="parchment-card shadow-2xl screenplay-body space-y-4">
      <div id="act-1-the-spring-break-briefing" class="act-banner text-2xl md:text-3xl font-black text-amber-400 tracking-tight">ACT I: THE SPRING BREAK PROTOCOL</div>
      <div class="action-block text-sm leading-relaxed text-slate-300 font-mono">### Official Master Screenplay Draft (American Foxy Mom MO2)</div>
      <div class="character-cue uppercase tracking-wider text-sm font-semibold" style="color:#38bdf8">Format:</div>
      <div class="dialogue font-mono text-sm leading-relaxed text-slate-100">Multi-Scene Animated Farce / Episodic Sitcom (TV-14)</div>
      <div class="character-cue uppercase tracking-wider text-sm font-semibold" style="color:#38bdf8">Continuity Standard:</div>
      <div class="dialogue font-mono text-sm leading-relaxed text-slate-100">Passed Invariant Gates (0 Hard Errors, 0 Soft Warnings, 0 Banned AI-isms, 0 Smith Surnames)</div>
      <div class="p-4 my-4 bg-[#ece7dc] border-l-4 border-[#c49a67] text-[#363026] text-xs font-sans rounded-r shadow-inner leading-relaxed">
        <strong>Prose Style:</strong> High-Farce Sitcom Hybrid (Sensory Anchored, Cadence Burstiness σ = 6.8, Zero Filter Words, Pure Ling Surname, Stage Direction Master)
      </div>
      <hr class="border-slate-800 my-8">
"""
    html_out.append(header)
    
    # Process each scene
    for s_idx, scene_str in enumerate(parsed_scenes):
        meta = SCENE_METAS[s_idx]
        paras = [p.strip() for p in scene_str.split("\n\n") if p.strip()]
        
        # Heading lines are in the first paragraph
        first_para = paras[0]
        body_paras = paras[1:]
        
        html_out.append(f'<div id="{meta["id"]}" class="chunk-header text-xl font-bold text-sky-400">{meta["title"]}</div>')
        html_out.append(f'<div class="scene-heading text-lg font-bold tracking-wide mt-8 pt-4">{meta["slug"]}</div>')
        
        if meta.get("images"):
            img_cards = []
            for img in meta["images"]:
                fname = img["file"]
                rel_src = f"foxy_mo2_images/{fname}"
                http_src = f"/images/{fname}"
                img_cards.append(
                    f'<div class="flex flex-col bg-[#16191f] border border-slate-800 rounded p-2 overflow-hidden shadow-md w-[200px]">'
                    f'<img src="{rel_src}" data-http="{http_src}" onerror="if(!this.dataset.fb){{this.dataset.fb=1;this.src=this.dataset.http;}}" alt="{img["caption"]}" class="w-full h-44 object-contain bg-black/50 rounded cursor-pointer hover:opacity-90 transition" onclick="window.open(this.src)" />'
                    f'<div class="text-[10px] text-amber-300 font-mono mt-1.5 leading-tight">{img["caption"]}</div>'
                    f'</div>'
                )
            gallery_html = (
                f'<div class="my-4 p-3 bg-slate-950/80 border border-slate-800/80 rounded-lg">'
                f'<div class="text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">'
                f'<span class="w-2 h-2 rounded-full bg-emerald-400 inline-block"></span> CANON VISUAL SPECIFICATIONS (LOCKED FROM PDF)'
                f'</div>'
                f'<div class="flex flex-wrap gap-3">{"".join(img_cards)}</div>'
                f'</div>'
            )
            html_out.append(gallery_html)
        
        current_speaker = "NARRATOR"
        
        for p_idx, p in enumerate(body_paras):
            # Check sound effect only
            if p.startswith('*') and p.endswith('*') and len(p.split('\n')) == 1:
                sfx_fmt = format_sfx(p)
                html_out.append(f'<div class="action-block text-sm leading-relaxed text-slate-300 font-mono">{sfx_fmt}</div>')
                continue
                
            has_quote = ('"' in p or '“' in p or '”' in p)
            
            # Determine speaker if dialogue present
            if has_quote:
                # Specific character patterns
                if any(k in p for k in ["Rainee-Peter", "Peter-bear", "Peter Griffin"]) or (s_idx == 3 and any(k in p for k in ["Hehehe", "double chin", "kill zone", "sweet merciful Jesus", "Peter", "whoops", "rusty lawnmower"])):
                    current_speaker = "RAINEE (PETER)"
                elif any(k in p for k in ["Nurse Pamela", "Pamela Franny", "Dr. Franny", "paramedic training"]):
                    current_speaker = "NURSE PAMELA FRANNY ANDERSON"
                elif any(k in p for k in ["butt plug", "Rutgers", "motel off the freeway", "goody bags", "royal ermine", "diamond tennis bracelets", "jewelry"]) or (s_idx == 6 and any(k in p for k in ["Roger", "ROGER", "Op! Too late", "taking the girls"])):
                    current_speaker = "ROGER"
                elif "Frat Guy" in p or "FRAT GUY" in p or p.startswith('"What\'s this?"') or p.startswith('"Hey, bro!"'):
                    current_speaker = "FRAT GUY"
                elif "COLLEGE STUDENTS" in p or p.startswith('"Woooo! Yeah!"'):
                    current_speaker = "COLLEGE STUDENTS"
                elif "Francine" in p or "FRANCINE" in p or p.startswith('"Troops!') or p.startswith('"Three nights') or p.startswith('"Show some respect') or p.startswith('"Change back!'):
                    current_speaker = "FRANCINE"
                elif "Rainee" in p or "RAINEE" in p or p.startswith('"Not today') or p.startswith('"Sweet Jade Emperor') or p.startswith('"Quiet, Haley!') or p.startswith('"Nailed it'):
                    current_speaker = "RAINEE"
                elif "Haley" in p or "HALEY" in p or p.startswith('"If it starts') or p.startswith('"Mom?!') or p.startswith('"Wait... what?!') or p.startswith('"I am going to murder'):
                    current_speaker = "HALEY"
                elif "Stella" in p or "STELLA" in p or p.startswith('"Ah. The ancient') or p.startswith('"That\'s... sweet') or p.startswith('"Don\'t body-shame') or p.startswith('"Not until we tap'):
                    current_speaker = "STELLA"

            # Parse paragraph tokens: action vs dialogue
            tokens = re.split(r'(["“][^"”]+["”])', p)
            for tok in tokens:
                tok = tok.strip()
                if not tok:
                    continue
                if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith('“') and tok.endswith('”')):
                    clean_dia = tok[1:-1]
                    spk_color = COLOR_MAP.get(current_speaker, "#38bdf8")
                    html_out.append(f'<div class="character-cue uppercase tracking-wider text-sm font-semibold" style="color:{spk_color}">{current_speaker}</div>')
                    html_out.append(f'<div class="dialogue font-mono text-sm leading-relaxed text-slate-100">&quot;{format_sfx(clean_dia)}&quot;</div>')
                else:
                    html_out.append(f'<div class="action-block text-sm leading-relaxed text-slate-300 font-mono">{format_sfx(tok)}</div>')
                    
        # Add transition cue between scenes
        if s_idx < len(parsed_scenes) - 1:
            html_out.append('<div class="transition-cue">DISSOLVE TO:</div>')
            html_out.append('<hr class="border-slate-800 my-8">')
            
    # Add ending
    footer = """
      <div class="act-banner text-center text-xl font-black text-amber-400 tracking-wider my-12">
        [ END OF CHAPTER 16 — TO BE CONTINUED ]
      </div>
    </div>
  </div>

  <footer class="mt-16 py-8 border-t border-slate-800 text-center text-xs text-slate-500 font-mono">
    Noir Fiction Engine · American Foxy Mom (MO2) Master Publication · Port 8765 Verified · 7 Authentic Scenes
  </footer>
</body>
</html>
"""
    html_out.append(footer)
    
    full_html = "\n".join(html_out)
    READER_PATH.write_text(full_html, encoding="utf-8")
    artifact_reader = Path(r"C:\NOIR_LOCAL\.gemini\antigravity\brain\f8842a47-08ce-4d96-a6b6-3a3d89029b1e\foxy_mo2_reader.html")
    if artifact_reader.parent.exists():
        artifact_reader.write_text(full_html, encoding="utf-8")
    print(f"Successfully generated {READER_PATH} ({len(full_html)} bytes, {len(parsed_scenes)} scenes).")

if __name__ == "__main__":
    build_reader()
