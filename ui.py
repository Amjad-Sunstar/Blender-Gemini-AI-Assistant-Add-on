import bpy
import os
import threading
from bpy_extras.io_utils import ImportHelper
from . import gemini_client, tools, polyhaven

CHAT_HISTORY = []
MAIN_THREAD_QUEUE = []
POLYHAVEN_RESULTS = []

def main_thread_timer():
    while MAIN_THREAD_QUEUE:
        item = MAIN_THREAD_QUEUE.pop(0)
        kind = item["kind"]

        if kind == "status":
            bpy.context.scene.gemini_status = item["msg"]

        elif kind == "tool":
            if item.get("push_undo"):
                try:
                    bpy.ops.ed.undo_push(message="Before Gemini AI")
                except Exception:
                    pass
            ok, msg = tools.execute_discrete_tool(item["name"], item["args"])
            item["result"] = (ok, msg)
            item["event"].set()

        elif kind == "ph_results":
            global POLYHAVEN_RESULTS
            POLYHAVEN_RESULTS = item["results"]
            bpy.context.scene.gemini_status = f"Found {len(POLYHAVEN_RESULTS)} Poly Haven assets."

        elif kind == "ph_apply":
            try:
                bpy.ops.ed.undo_push(message="Before Poly Haven Import")
                msg = polyhaven.apply_asset_on_main_thread(item["paths"], item["mode"], item["asset_id"])
                bpy.context.scene.gemini_status = msg
            except Exception as e:
                bpy.context.scene.gemini_status = f"Apply Error: {str(e)[:45]}"

        if bpy.context.screen:
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    return 0.15

def dispatch_tool_sync(name: str, args: dict, push_undo: bool = False) -> tuple[bool, str]:
    evt = threading.Event()
    packet = {
        "kind": "tool",
        "name": name,
        "args": args,
        "push_undo": push_undo,
        "event": evt,
        "result": (False, "Timeout"),
    }
    MAIN_THREAD_QUEUE.append(packet)
    evt.wait(timeout=30.0)
    return packet["result"]

def set_status_async(msg: str):
    MAIN_THREAD_QUEUE.append({"kind": "status", "msg": msg})

# --- OPERATORS ---
class GEMINI_OT_RefreshModels(bpy.types.Operator):
    bl_idname = "gemini.refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Fetch active Gemini models from your API key(s)"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        raw_keys = prefs.api_key.strip()
        if not raw_keys:
            self.report({'ERROR'}, "Set your Gemini API Key in Add-on Preferences first!")
            return {'CANCELLED'}

        def worker():
            set_status_async("Fetching available models...")
            try:
                models = gemini_client.fetch_models_from_api(raw_keys)
                set_status_async(f"Loaded {len(models)} active models!")
            except Exception as e:
                set_status_async(f"Model Fetch Error: {str(e)[:45]}")

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}

class GEMINI_OT_QuickAction(bpy.types.Operator):
    bl_idname = "gemini.quick_action"
    bl_label = "Quick Action"
    action: bpy.props.StringProperty()

    def execute(self, context):
        act = self.action
        try:
            bpy.ops.ed.undo_push(message=f"Quick Action: {act}")
        except Exception:
            pass

        if act in {"CUBE", "SPHERE", "CYLINDER", "CONE", "PLANE", "TORUS"}:
            ok, msg = tools.execute_discrete_tool("create_primitive", {"primitive_type": act})
        else:
            ok, msg = tools.execute_discrete_tool("quick_op", {"op": act})
        context.scene.gemini_status = msg
        return {'FINISHED'}

class GEMINI_OT_UndoLastAI(bpy.types.Operator):
    bl_idname = "gemini.undo_last_ai"
    bl_label = "Undo AI"
    bl_description = "Undo the last AI or Quick Action change"

    def execute(self, context):
        try:
            bpy.ops.ed.undo()
            context.scene.gemini_status = "Reverted last action."
        except Exception as e:
            context.scene.gemini_status = f"Undo unavailable: {str(e)[:35]}"
        return {'FINISHED'}

class GEMINI_OT_OpenLastScript(bpy.types.Operator):
    bl_idname = "gemini.open_last_script"
    bl_label = "View Code"
    bl_description = "Open the last AI-generated Python script in Blender's Text Editor"

    def execute(self, context):
        code = context.scene.gemini_last_code
        if not code:
            self.report({'INFO'}, "No script generated yet in this session.")
            return {'CANCELLED'}

        txt_name = "Gemini_AI_Last_Script.py"
        txt = bpy.data.texts.get(txt_name) or bpy.data.texts.new(txt_name)
        txt.clear()
        txt.write(code)

        for area in context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.spaces.active.text = txt
                break
        context.scene.gemini_status = f"Saved to Text Editor: {txt_name}"
        return {'FINISHED'}

class GEMINI_OT_ChooseRefImage(bpy.types.Operator, ImportHelper):
    bl_idname = "gemini.choose_ref_image"
    bl_label = "Choose Reference Image"
    filter_glob: bpy.props.StringProperty(default="*.png;*.jpg;*.jpeg;*.webp", options={'HIDDEN'})

    def execute(self, context):
        context.scene.gemini_ref_image = self.filepath
        context.scene.gemini_status = f"Reference: {os.path.basename(self.filepath)}"
        return {'FINISHED'}

class GEMINI_OT_ClearRefImage(bpy.types.Operator):
    bl_idname = "gemini.clear_ref_image"
    bl_label = "Remove Reference Image"

    def execute(self, context):
        context.scene.gemini_ref_image = ""
        return {'FINISHED'}

class GEMINI_OT_SearchPolyHaven(bpy.types.Operator):
    bl_idname = "gemini.search_polyhaven"
    bl_label = "Search Poly Haven"

    def execute(self, context):
        query = context.scene.gemini_ph_query
        atype = context.scene.gemini_ph_type

        def worker():
            set_status_async("Searching Poly Haven...")
            try:
                res = polyhaven.search_polyhaven(atype, query)
                MAIN_THREAD_QUEUE.append({"kind": "ph_results", "results": res})
            except Exception as e:
                set_status_async(f"Poly Haven Error: {str(e)[:45]}")

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}

class GEMINI_OT_ImportPolyHaven(bpy.types.Operator):
    bl_idname = "gemini.import_polyhaven"
    bl_label = "Import Asset"
    asset_id: bpy.props.StringProperty()

    def execute(self, context):
        aid = self.asset_id
        atype = context.scene.gemini_ph_type
        res = context.scene.gemini_ph_res

        def worker():
            set_status_async(f"Downloading {aid} ({res})...")
            try:
                paths, mode = polyhaven.prepare_download(aid, atype, res)
                MAIN_THREAD_QUEUE.append({
                    "kind": "ph_apply",
                    "paths": paths,
                    "mode": mode,
                    "asset_id": aid,
                })
            except Exception as e:
                set_status_async(f"Download Error: {str(e)[:45]}")

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}

class GEMINI_OT_Generate(bpy.types.Operator):
    bl_idname = "gemini.generate"
    bl_label = "Generate"

    def execute(self, context):
        scene = context.scene
        prompt = scene.gemini_prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "Please describe what to build first.")
            return {'CANCELLED'}

        handled, local_msg = tools.try_local_intent(prompt)
        if handled:
            scene.gemini_status = local_msg
            return {'FINISHED'}

        prefs = context.preferences.addons[__package__].preferences
        raw_keys = prefs.api_key.strip()
        if not raw_keys:
            self.report({'ERROR'}, "Set your Gemini API Key in Edit > Preferences > Add-ons!")
            return {'CANCELLED'}

        selected_model = scene.gemini_model
        scene_ctx = gemini_client.get_scene_context()
        ref_path = scene.gemini_ref_image
        vp_bytes = gemini_client.capture_viewport_bytes() if scene.gemini_use_vision else None

        def worker():
            global CHAT_HISTORY
            try:
                summary, updated_hist = gemini_client.run_agent_turn(
                    raw_api_keys=raw_keys,
                    selected_model=selected_model,
                    prompt=prompt,
                    history=CHAT_HISTORY,
                    scene_ctx=scene_ctx,
                    ref_image_path=ref_path,
                    viewport_bytes=vp_bytes,
                    dispatch_tool_fn=dispatch_tool_sync,
                    status_fn=set_status_async,
                )
                CHAT_HISTORY = updated_hist
                set_status_async(summary)
            except Exception as e:
                set_status_async(f"AI Error: {str(e)[:55]}")

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}

class GEMINI_OT_NewConversation(bpy.types.Operator):
    bl_idname = "gemini.new_conversation"
    bl_label = "New Conversation"

    def execute(self, context):
        global CHAT_HISTORY
        CHAT_HISTORY.clear()
        context.scene.gemini_status = "Started new conversation."
        return {'FINISHED'}

# --- MAIN SIDEBAR UI PANEL ---
class GEMINI_PT_AssistantPanel(bpy.types.Panel):
    bl_label = "Gemini AI Assistant Pro"
    bl_idname = "GEMINI_PT_assistant_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Gemini AI'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        # 1. QUICK ACTIONS + STUDIO PRESETS (instant, no AI)
        box = layout.box()
        row = box.row()
        row.prop(
            scene, "gemini_show_quick",
            icon="TRIA_DOWN" if scene.gemini_show_quick else "TRIA_RIGHT",
            text="Quick Actions (instant, no AI)",
            emboss=False
        )
        if scene.gemini_show_quick:
            grid = box.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
            for label, code in [("Cube", "CUBE"), ("Sphere", "SPHERE"), ("Cylinder", "CYLINDER"),
                                ("Cone", "CONE"), ("Plane", "PLANE"), ("Torus", "TORUS")]:
                grid.operator("gemini.quick_action", text=label).action = code

            col = box.column(align=True)
            col.operator("gemini.quick_action", text="Duplicate Active", icon='DUPLICATE').action = "DUPLICATE"
            col.operator("gemini.quick_action", text="Delete Active", icon='TRASH').action = "DELETE"
            col.operator("gemini.quick_action", text="Reset Transform", icon='LOOP_BACK').action = "RESET"
            col.operator("gemini.quick_action", text="Shade Smooth", icon='MOD_SMOOTH').action = "SMOOTH"

            sub = col.row()
            sub.enabled = bool(obj and len(obj.modifiers) > 0)
            sub.operator("gemini.quick_action", text="Apply All Modifiers", icon='CHECKMARK').action = "APPLY_MODS"

            row = box.row(align=True)
            row.operator("gemini.quick_action", text="3-Point Light", icon='LIGHT_AREA').action = "STUDIO_LIGHT"
            row.operator("gemini.quick_action", text="Auto Camera", icon='CAMERA_DATA').action = "ADD_CAM"

        # 2. RENDER (Non-blocking)
        box = layout.box()
        box.label(text="Render", icon='RENDER_STILL')
        row = box.row(align=True)
        row.operator("gemini.quick_action", text="Render Image", icon='RENDER_STILL').action = "RENDER_IMG"
        row.operator("gemini.quick_action", text="Render Animation...", icon='RENDER_ANIMATION').action = "RENDER_ANIM"

        # 3. ASSETS (POLY HAVEN - HDRIs, Full PBR Textures, 3D Models)
        box = layout.box()
        row = box.row()
        row.prop(
            scene, "gemini_show_ph",
            icon="TRIA_DOWN" if scene.gemini_show_ph else "TRIA_RIGHT",
            text="Assets (Poly Haven)",
            emboss=False
        )
        if scene.gemini_show_ph:
            box.prop(scene, "gemini_ph_query", text="")
            row = box.row(align=True)
            row.prop(scene, "gemini_ph_type", text="")
            row.prop(scene, "gemini_ph_res", text="")
            box.operator("gemini.search_polyhaven", text="Search Poly Haven", icon='VIEWZOOM')

            if POLYHAVEN_RESULTS:
                res_box = box.box()
                for aid, name in POLYHAVEN_RESULTS:
                    r = res_box.row(align=True)
                    r.label(text=name[:22])
                    r.operator("gemini.import_polyhaven", text="Import", icon='IMPORT').asset_id = aid

        # 4. REFERENCE IMAGE (optional)
        box = layout.box()
        box.label(text="Reference Image (optional)", icon='IMAGE_DATA')
        if scene.gemini_ref_image:
            row = box.row(align=True)
            row.label(text=os.path.basename(scene.gemini_ref_image), icon='FILE_IMAGE')
            row.operator("gemini.clear_ref_image", text="", icon='X')
        else:
            box.operator("gemini.choose_ref_image", text="Choose Reference Image...", icon='FILE_FOLDER')

        info = box.column(align=True)
        info.scale_y = 0.8
        info.label(text="Gemini will approximate colors/layout from it -", icon='INFO')
        info.label(text="not a pixel-perfect or photorealistic copy.")

        # 5. MODEL SELECTION, VISION & PROMPT
        layout.separator()
        row = layout.row(align=True)
        row.prop(scene, "gemini_model", text="Model")
        row.operator("gemini.refresh_models", text="", icon='FILE_REFRESH')

        layout.prop(scene, "gemini_use_vision", text="Send Viewport Vision (3D Preview)")
        layout.label(text="Describe what to build (or a follow-up):")
        layout.prop(scene, "gemini_prompt", text="")

        layout.operator("gemini.generate", text="Generate", icon='PLAY')

        row = layout.row(align=True)
        row.operator("gemini.undo_last_ai", text="Undo AI", icon='LOOP_BACK')
        row.operator("gemini.open_last_script", text="View Code", icon='TEXT')
        row.operator("gemini.new_conversation", text="Reset Chat", icon='TRASH')

        # Status + Free Tier Dashboard Shortcut
        status_box = layout.box()
        status_box.label(text=scene.gemini_status, icon='INFO')
        row = status_box.row(align=True)
        row.scale_y = 0.85
        row.label(text=f"Session Calls: {gemini_client.SESSION_API_CALLS}")
        op = row.operator("wm.url_open", text="Quota Dashboard", icon='URL')
        op.url = "https://aistudio.google.com/usage"