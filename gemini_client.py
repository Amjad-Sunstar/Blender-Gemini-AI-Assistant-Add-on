import bpy
import os
import tempfile
import mimetypes
from google import genai
from google.genai import types
from . import tools

DYNAMIC_MODEL_ITEMS = [
    ("AUTO", "Auto (Smart Rotation)", "Automatically picks best active model & rotates on limits"),
    ("gemini-2.5-flash", "gemini-2.5-flash", "Fast & balanced for 3D generation"),
    ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite", "Ultra-fast lightweight model"),
    ("gemini-2.5-pro", "gemini-2.5-pro", "Best for complex scenes & reasoning"),
    ("gemini-3-flash-preview", "gemini-3-flash-preview", "Latest Gemini 3 Flash preview"),
]

EXCLUDED_KEYWORDS = (
    "embedding", "imagen", "veo", "aqa", "tts", "audio",
    "live", "robotics", "computer-use", "deep-research", "bisect"
)

SESSION_API_CALLS = 0

SYSTEM_INSTRUCTION = """
You are an expert Blender 3D AI Assistant integrated directly inside Blender.
You control the Blender scene using the provided function tools (`create_primitive`, `apply_material`, `add_modifier`, `transform_object`, `delete_object`, `animate_object`, `run_bpy_script`).
- For simple creation, materials, modifiers, transforms, or keyframe animation, call the discrete tools directly.
- For complex 3D models, characters, multi-object layouts, procedural geometry, or custom shaders, call `run_bpy_script` with clean, self-contained `bpy` / `bmesh` code.
- Always name created objects descriptively so follow-up prompts can reference them easily.
- Never import `os`, `sys`, `subprocess`, or `pathlib`.
- If a reference image is provided, approximate its colors, proportions, and 3D layout in Blender.
- Keep final text replies concise (1-2 sentences).
"""

def parse_api_keys(raw_keys: str) -> list[str]:
    return [k.strip() for k in raw_keys.split(",") if k.strip()]

def fetch_models_from_api(raw_keys: str) -> list[str]:
    global DYNAMIC_MODEL_ITEMS
    keys = parse_api_keys(raw_keys)
    if not keys:
        raise RuntimeError("No API key provided.")

    client = genai.Client(api_key=keys[0])
    discovered = []

    for m in client.models.list():
        raw_name = getattr(m, "name", "") or ""
        name = raw_name.replace("models/", "").strip()
        if not name.startswith("gemini-"):
            continue
        if any(bad in name.lower() for bad in EXCLUDED_KEYWORDS):
            continue

        actions = getattr(m, "supported_actions", None)
        if actions and "generateContent" not in actions:
            continue

        discovered.append(name)

    if discovered:
        def priority(m_name: str):
            is_flash = 0 if "flash" in m_name else 1
            is_lite = 1 if "lite" in m_name else 0
            is_exp = 2 if ("exp" in m_name or "preview" in m_name) else 0
            return (is_flash, is_lite, is_exp, m_name)

        discovered.sort(key=priority)
        new_items = [("AUTO", "Auto (Smart Rotation)", "Automatically picks best active model")]
        for m_name in discovered:
            new_items.append((m_name, m_name, f"Use {m_name}"))
        DYNAMIC_MODEL_ITEMS = new_items

    return discovered

def get_scene_context() -> str:
    objs = []
    for obj in bpy.context.scene.objects[:40]:
        loc = tuple(round(v, 2) for v in obj.location)
        dim = tuple(round(v, 2) for v in obj.dimensions)
        mats = [m.name for m in obj.data.materials if m] if hasattr(obj.data, "materials") else []
        mat_str = f" mats={mats}" if mats else ""
        objs.append(f"{obj.name} ({obj.type}) loc={loc} dim={dim}{mat_str}")

    active = bpy.context.active_object.name if bpy.context.active_object else "None"
    selected = [o.name for o in bpy.context.selected_objects[:10]]
    return (
        f"Active: {active} | Selected: {selected} | Frame: {bpy.context.scene.frame_current}\n"
        f"Scene Objects: {', '.join(objs) if objs else 'Empty Scene'}"
    )

def capture_viewport_bytes() -> bytes | None:
    try:
        scene = bpy.context.scene
        orig_path = scene.render.filepath
        orig_fmt = scene.render.image_settings.file_format
        tmp_path = os.path.join(tempfile.gettempdir(), "blender_gemini_viewport.jpg")

        scene.render.filepath = tmp_path
        scene.render.image_settings.file_format = 'JPEG'
        bpy.ops.render.opengl(write_still=True)

        scene.render.filepath = orig_path
        scene.render.image_settings.file_format = orig_fmt

        if os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                data = f.read()
            os.remove(tmp_path)
            return data
    except Exception:
        pass
    return None

def load_image_part(filepath: str) -> types.Part | None:
    if not filepath or not os.path.exists(filepath):
        return None
    mime, _ = mimetypes.guess_type(filepath)
    if not mime:
        mime = "image/png"
    with open(filepath, "rb") as f:
        return types.Part.from_bytes(data=f.read(), mime_type=mime)

def generate_with_multi_key_rotation(api_keys: list[str], model_list: list[str], contents: list, config: types.GenerateContentConfig):
    global SESSION_API_CALLS
    last_err = ""
    for key_idx, key in enumerate(api_keys):
        client = genai.Client(api_key=key)
        for model_name in model_list:
            try:
                SESSION_API_CALLS += 1
                resp = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                return resp, model_name, key_idx + 1
            except Exception as e:
                last_err = f"[Key#{key_idx+1} | {model_name}] {str(e)}"
                print(f"[Gemini Addon] Rotation fallback: {last_err}")
                # Invalid key -> skip to next key immediately
                if "api_key_invalid" in last_err.lower() or "api key not valid" in last_err.lower():
                    break
                continue
    raise RuntimeError(last_err or "All keys and models failed.")

def run_agent_turn(
    raw_api_keys: str,
    selected_model: str,
    prompt: str,
    history: list,
    scene_ctx: str,
    ref_image_path: str,
    viewport_bytes: bytes | None,
    dispatch_tool_fn,
    status_fn
) -> tuple[str, list]:
    api_keys = parse_api_keys(raw_api_keys)
    if not api_keys:
        raise RuntimeError("API Key missing!")

    if len(DYNAMIC_MODEL_ITEMS) <= 5:
        try:
            fetch_models_from_api(raw_api_keys)
        except Exception:
            pass

    available = [item[0] for item in DYNAMIC_MODEL_ITEMS if item[0] != "AUTO"]
    if not available:
        available = ["gemini-2.5-flash", "gemini-2.5-pro"]

    if selected_model and selected_model != "AUTO":
        model_queue = [selected_model] + [m for m in available if m != selected_model]
    else:
        model_queue = available

    gemini_tools = tools.get_gemini_tools()
    parts = [types.Part.from_text(text=f"[Scene Context]\n{scene_ctx}\n\n[User Request]\n{prompt}")]

    if viewport_bytes:
        parts.append(types.Part.from_text(text="[Current 3D Viewport Screenshot]"))
        parts.append(types.Part.from_bytes(data=viewport_bytes, mime_type="image/jpeg"))

    ref_part = load_image_part(ref_image_path)
    if ref_part:
        parts.append(types.Part.from_text(text="[Reference Image for Layout/Colors]"))
        parts.append(ref_part)

    history.append(types.Content(role="user", parts=parts))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=gemini_tools,
        temperature=0.2,
    )

    final_summary = "Done!"
    used_model = model_queue[0]
    undo_pushed = False

    for step in range(4):
        status_fn(f"Thinking ({used_model})...")
        response, used_model, key_num = generate_with_multi_key_rotation(api_keys, model_queue, history, config)

        if not response.candidates:
            break

        model_content = response.candidates[0].content
        history.append(model_content)

        fn_calls = [p.function_call for p in model_content.parts if p.function_call]
        if not fn_calls:
            text_parts = [p.text for p in model_content.parts if p.text]
            tag = f"[K{key_num}:{used_model}]" if len(api_keys) > 1 else f"[{used_model}]"
            if text_parts:
                final_summary = f"{tag} " + " ".join(text_parts).strip()[:95]
            else:
                final_summary = f"Done! {tag}"
            break

        fn_response_parts = []
        for fc in fn_calls:
            status_fn(f"Running {fc.name}...")
            args = dict(fc.args) if fc.args else {}
            ok, tool_msg = dispatch_tool_fn(fc.name, args, push_undo=not undo_pushed)
            undo_pushed = True
            fn_response_parts.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response={"success": ok, "message": tool_msg},
                )
            )
            if not ok:
                status_fn(f"Error in {fc.name}, AI fixing...")

        history.append(types.Content(role="user", parts=fn_response_parts))

    return final_summary, history[-14:]