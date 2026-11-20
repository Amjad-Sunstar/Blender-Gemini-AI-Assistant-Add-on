bl_info = {
    "name": "Gemini AI Assistant Pro",
    "author": "Custom Setup",
    "version": (3, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Gemini AI",
    "description": "Pro Gemini AI Assistant with Multi-Key Rotation, Undo AI, Full PBR Poly Haven, Vision & Code Inspector",
    "category": "3D View",
}

import sys
import os
import importlib
import bpy

_user_modules = os.path.join(bpy.utils.resource_path('USER'), "scripts", "modules")
if _user_modules not in sys.path and os.path.exists(_user_modules):
    sys.path.append(_user_modules)

from . import safety, tools, polyhaven, gemini_client, ui
importlib.reload(safety)
importlib.reload(tools)
importlib.reload(polyhaven)
importlib.reload(gemini_client)
importlib.reload(ui)

def get_model_items(self, context):
    return gemini_client.DYNAMIC_MODEL_ITEMS

class GeminiAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    api_key: bpy.props.StringProperty(
        name="Gemini API Key(s)",
        description="Paste 1 key, or multiple keys separated by commas (key1, key2) for automatic quota rotation",
        default="",
        subtype='PASSWORD',
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "api_key")
        layout.label(text="Tip: Separate multiple keys with commas (AIza..., AIza...) for auto-rotation!")
        row = layout.row()
        op1 = row.operator("wm.url_open", text="Get API Key (AI Studio)", icon='KEYINGSET')
        op1.url = "https://aistudio.google.com/apikey"
        op2 = row.operator("wm.url_open", text="Check Free Tier Usage", icon='URL')
        op2.url = "https://aistudio.google.com/usage"

classes = (
    GeminiAddonPreferences,
    ui.GEMINI_OT_RefreshModels,
    ui.GEMINI_OT_QuickAction,
    ui.GEMINI_OT_UndoLastAI,
    ui.GEMINI_OT_OpenLastScript,
    ui.GEMINI_OT_ChooseRefImage,
    ui.GEMINI_OT_ClearRefImage,
    ui.GEMINI_OT_SearchPolyHaven,
    ui.GEMINI_OT_ImportPolyHaven,
    ui.GEMINI_OT_Generate,
    ui.GEMINI_OT_NewConversation,
    ui.GEMINI_PT_AssistantPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    S = bpy.types.Scene
    S.gemini_show_quick = bpy.props.BoolProperty(default=True)
    S.gemini_show_ph = bpy.props.BoolProperty(default=True)
    S.gemini_ph_query = bpy.props.StringProperty(name="Search", default="")
    S.gemini_ph_type = bpy.props.EnumProperty(
        name="Type",
        items=[("HDRIS", "HDRIs", ""), ("TEXTURES", "Textures", ""), ("MODELS", "Models", "")],
        default="HDRIS"
    )
    S.gemini_ph_res = bpy.props.EnumProperty(
        name="Resolution",
        items=[("1K", "1K", ""), ("2K", "2K", ""), ("4K", "4K", "")],
        default="1K"
    )
    S.gemini_ref_image = bpy.props.StringProperty(name="Reference Image", default="")
    S.gemini_model = bpy.props.EnumProperty(
        name="Gemini Model",
        description="Choose Gemini model or Auto Rotation",
        items=get_model_items,
    )
    S.gemini_use_vision = bpy.props.BoolProperty(
        name="Send Viewport Vision",
        description="Send a snapshot of your 3D Viewport so Gemini can see the current scene",
        default=False
    )
    S.gemini_prompt = bpy.props.StringProperty(name="Prompt", default="")
    S.gemini_status = bpy.props.StringProperty(name="Status", default="Ready")
    S.gemini_last_code = bpy.props.StringProperty(name="Last Code", default="")

    if not bpy.app.timers.is_registered(ui.main_thread_timer):
        bpy.app.timers.register(ui.main_thread_timer)

def unregister():
    if bpy.app.timers.is_registered(ui.main_thread_timer):
        bpy.app.timers.unregister(ui.main_thread_timer)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    S = bpy.types.Scene
    for prop in (
        "gemini_show_quick", "gemini_show_ph", "gemini_ph_query",
        "gemini_ph_type", "gemini_ph_res", "gemini_ref_image",
        "gemini_model", "gemini_use_vision", "gemini_prompt",
        "gemini_status", "gemini_last_code"
    ):
        if hasattr(S, prop):
            delattr(S, prop)

if __name__ == "__main__":
    register()