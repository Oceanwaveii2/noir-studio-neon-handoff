# Noir Fiction Studio — Decoupled UI Workspace (`ui/`)

This directory holds the decoupled frontend for **Noir Fiction Studio**, separated from the Python backend/asset tree (`tools/assets/v2/`) so the UI can evolve independently toward the **Noir Studio v4.2** visual and architectural specification (DaVinci Resolve × ComfyUI × Linear dark-slate tokens, Tri-Split workspace, 4 Discrete Noise Modes, and Scene-Group Cook Scope).

## How It Connects to the Backend
- **Live Server Route (`/v2` and `/assets/v2/*`)**: `tools/studio_canon_routes.py` (`serve_v2_asset`) resolves files from `ui/` first (falling back to `tools/assets/v2/` if missing), preserving full compatibility with `tools/studio_ui.py` and `tests/test_studio_v2_ui.py`.
- **Standalone Entry (`ui/index.html`)**: Uses relative `./` asset paths and `data-theme="noir-v4"` by default.
- **Themes**:
  - `noir-v4` (default): DaVinci Resolve × ComfyUI × Linear dark-slate studio palette (`#070a10` → `#1d2638`, `#38bdf8` cyan, `#ec4899` rose, `#10b981` emerald, `#f59e0b` amber, `#ef4444` crimson, `#8b5cf6` violet).
  - `racing` and `classic`: Preserved for backward compatibility and URL/localStorage switching (`?theme=racing` / `?theme=classic`).

## Verification
- Core CI: `python -B tools/ci.py --core`
- Studio UI Tests: `python -B -m unittest tests.test_studio_v2_ui`
