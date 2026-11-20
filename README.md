# Blender Gemini AI Assistant Pro

![Blender](https://img.shields.io/badge/Blender-4.0%20%7C%205.0%2B-orange?logo=blender)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![Gemini API](https://img.shields.io/badge/Google-Gemini%20API-4285F4?logo=google)
![License](https://img.shields.io/badge/License-MIT-green)

**Blender Gemini AI Assistant Pro** is an AI-powered 3D modeling, scene layout, animation, and asset integration addon built directly into Blender's 3D Viewport sidebar. Powered by Google's `google-genai` SDK, it combines multimodal Vision, function-calling tools, safe AST-validated Python execution, and Poly Haven asset integration without freezing Blender's UI.

---

## Key Features

- **Smart Multi-Model & Multi-Key Rotation:** Automatically discovers active Gemini models (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview`, etc.) from your API key and rotates across multiple comma-separated API keys if free-tier rate limits (`429`) occur.
- **3D Viewport Vision:** Captures a live snapshot of your 3D Viewport so Gemini can see your current scene layout, lighting, and proportions before making edits.
- **Reference Image to 3D:** Upload any reference image (`.png`, `.jpg`, `.webp`) and let Gemini approximate its colors, composition, and 3D geometry.
- **Discrete Function-Calling Tools + Safe Scripting:**
  - Direct tools for creating primitives, applying PBR materials (Metallic, Glass, Emission), adding modifiers (`Subsurf`, `Bevel`, `Solidify`, `Array`, `Mirror`), transforming, deleting, and keyframe animation.
  - Fallback `run_bpy_script` tool for complex procedural geometry using `bpy` and `bmesh`.
- **AST Security Validation & Restricted Sandbox:** Every AI-generated script is parsed via Python's `ast` module before execution to block dangerous modules (`os`, `sys`, `subprocess`, `shutil`, `socket`, etc.) and file/system calls.
- **Self-Correcting Retry Loop:** If an executed `bpy` script raises a runtime error, the traceback is automatically fed back to Gemini to fix and re-run.
- **Local Intent Router & Quick Actions:** Instant, zero-API-cost buttons and text shortcuts for primitives, transforms, smooth shading, **3-Point Studio Lighting**, **Auto Camera**, and non-blocking **Image/Animation Renders**.
- **Poly Haven Asset Browser:** Search and import HDRIs, 3D `.blend` models, and **Full PBR Textures** (automatically downloading and wiring Diffuse, Roughness, and Normal maps into `Principled BSDF`).
- **1-Click Undo AI & Live Script Inspector:** Automatically creates a Blender Undo checkpoint before AI edits and lets you open the last generated Python script directly in Blender's Text Editor.

---

## Project Structure

```text
blender_gemini_ai/
├── __init__.py        # Addon registration, multi-key preferences & scene properties
├── ui.py              # Non-blocking sidebar panel, threading queue & operators
├── gemini_client.py   # Google GenAI SDK integration, Vision, model/key rotation
├── tools.py           # Local intent router, discrete Blender tools & function schemas
├── polyhaven.py       # Poly Haven API search, background downloader & PBR shader builder
└── safety.py          # AST code validator & restricted exec() sandbox
```

---

## Installation

### 1. Get a Free Gemini API Key
1. Visit [Google AI Studio](https://aistudio.google.com/apikey) and generate an API key.
2. *(Optional)* Generate 2–3 keys if you want automatic multi-key quota rotation.

### 2. Install `google-genai` inside Blender's Python
Blender uses its own bundled Python environment. Open Blender's **Scripting** workspace, go to the **Python Console**, and run the command matching your OS:

**Windows (Standard & Microsoft Store builds):**
```python
import bpy, subprocess, sys, os
target_dir = os.path.join(bpy.utils.resource_path('USER'), "scripts", "modules")
subprocess.check_call([sys.executable, "-m", "pip", "install", "--target", target_dir, "google-genai"])
```

**Linux (Run in terminal using Blender's bundled Python path):**
```bash
/path/to/blender/python/bin/python3.11 -m pip install google-genai
```

Verify installation in Blender's Python Console:
```python
from google import genai; print("Gemini SDK Ready!")
```

### 3. Install the Addon in Blender
1. Download or clone this repository and compress the `blender_gemini_ai` folder into `blender_gemini_ai.zip`.
2. Open Blender and go to **Edit > Preferences > Add-ons**.
3. Click **Install from Disk...** (or **Install...**), select `blender_gemini_ai.zip`, and enable **Gemini AI Assistant Pro**.
4. Expand the addon preferences and paste your **Gemini API Key(s)** (comma-separated if using multiple keys).

---

## Usage

1. Press **`N`** in the **3D Viewport** to open the right sidebar and select the **Gemini AI** tab.
2. Click the **Refresh (`↻`)** button next to the **Model** dropdown to fetch all active models available for your API key.
3. Type a prompt and click **Generate**:
   - *"Delete the default cube and build a low-poly pine tree with snow on top"*
   - *"Add a metallic gold torus in the center and animate a 360-degree Z rotation from frame 1 to 120"*
   - *"Set up a studio floor and apply a glass material to the selected sphere"*
4. Use **Undo AI** to revert the last AI operation, or **View Code** to inspect the generated script inside Blender's Text Editor.

---

## Security & Architecture

- **Non-Blocking Threading:** All Gemini API requests and Poly Haven asset downloads execute on background daemon threads, passing `bpy` mutations safely back to Blender's main thread via `bpy.app.timers`.
- **Sandboxed Execution:** Generated scripts run inside a stripped `__builtins__` namespace exposing only safe math/data utilities alongside `bpy`, `bmesh`, `math`, `mathutils`, and `random`.

---

## License

This project is licensed under the MIT License. Feel free to fork, modify, and contribute!