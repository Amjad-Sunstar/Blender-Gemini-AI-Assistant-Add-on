import bpy
import math
from mathutils import Vector
from google.genai import types
from . import safety

# --- 1. LOCAL INTENT ROUTER (Zero API tokens, instant execution) ---
def try_local_intent(prompt: str) -> tuple[bool, str]:
    p = prompt.strip().lower()
    exact_map = {
        "add cube": ("create_primitive", {"primitive_type": "CUBE"}),
        "create cube": ("create_primitive", {"primitive_type": "CUBE"}),
        "add sphere": ("create_primitive", {"primitive_type": "SPHERE"}),
        "create sphere": ("create_primitive", {"primitive_type": "SPHERE"}),
        "add cylinder": ("create_primitive", {"primitive_type": "CYLINDER"}),
        "add cone": ("create_primitive", {"primitive_type": "CONE"}),
        "add plane": ("create_primitive", {"primitive_type": "PLANE"}),
        "add torus": ("create_primitive", {"primitive_type": "TORUS"}),
        "delete active": ("quick_op", {"op": "DELETE"}),
        "delete selected": ("quick_op", {"op": "DELETE"}),
        "duplicate": ("quick_op", {"op": "DUPLICATE"}),
        "duplicate active": ("quick_op", {"op": "DUPLICATE"}),
        "reset transform": ("quick_op", {"op": "RESET"}),
        "shade smooth": ("quick_op", {"op": "SMOOTH"}),
        "apply modifiers": ("quick_op", {"op": "APPLY_MODS"}),
        "studio light": ("quick_op", {"op": "STUDIO_LIGHT"}),
        "3 point light": ("quick_op", {"op": "STUDIO_LIGHT"}),
        "add camera": ("quick_op", {"op": "ADD_CAM"}),
        "render image": ("quick_op", {"op": "RENDER_IMG"}),
        "render animation": ("quick_op", {"op": "RENDER_ANIM"}),
    }
    if p in exact_map:
        func_name, args = exact_map[p]
        bpy.ops.ed.undo_push(message=f"Gemini Local: {p}")
        ok, msg = execute_discrete_tool(func_name, args)
        return True, f"[Instant] {msg}"
    return False, ""

# --- 2. DISCRETE BLENDER TOOLS ---
def execute_discrete_tool(func_name: str, args: dict) -> tuple[bool, str]:
    try:
        if func_name == "quick_op":
            op = args.get("op")
            obj = bpy.context.active_object
            if op == "DELETE":
                if bpy.context.selected_objects:
                    bpy.ops.object.delete()
                    return True, "Deleted selected object(s)."
                return False, "No active object selected."
            elif op == "DUPLICATE":
                if obj:
                    bpy.ops.object.duplicate_move(TRANSFORM_OT_translate={"value": (1.2, 0.0, 0.0)})
                    return True, f"Duplicated {obj.name}."
                return False, "No active object to duplicate."
            elif op == "RESET":
                if obj:
                    obj.location = (0.0, 0.0, 0.0)
                    obj.rotation_euler = (0.0, 0.0, 0.0)
                    obj.scale = (1.0, 1.0, 1.0)
                    return True, f"Reset transform for {obj.name}."
                return False, "No active object."
            elif op == "SMOOTH":
                if obj and obj.type == 'MESH':
                    bpy.ops.object.shade_smooth()
                    return True, f"Applied Shade Smooth to {obj.name}."
                return False, "Select a mesh object first."
            elif op == "APPLY_MODS":
                if obj and obj.modifiers:
                    for mod in list(obj.modifiers):
                        bpy.ops.object.modifier_apply(modifier=mod.name)
                    return True, f"Applied all modifiers on {obj.name}."
                return False, "No modifiers to apply."
            elif op == "STUDIO_LIGHT":
                lights = [
                    ("Key_Light", (4.0, -4.0, 5.0), 800, (1.0, 0.96, 0.92), 3.0),
                    ("Fill_Light", (-4.5, -2.5, 3.0), 300, (0.85, 0.92, 1.0), 4.0),
                    ("Rim_Light", (0.0, 4.5, 4.0), 600, (1.0, 1.0, 1.0), 2.5),
                ]
                for lname, loc, energy, col, size in lights:
                    ldata = bpy.data.lights.new(name=lname, type='AREA')
                    ldata.energy = energy
                    ldata.color = col
                    ldata.size = size
                    lobj = bpy.data.objects.new(name=lname, object_data=ldata)
                    bpy.context.collection.objects.link(lobj)
                    lobj.location = loc
                    direction = Vector((0.0, 0.0, 0.5)) - lobj.location
                    lobj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
                return True, "Added 3-Point Studio Lighting."
            elif op == "ADD_CAM":
                cdata = bpy.data.cameras.new(name="AI_Camera")
                cobj = bpy.data.objects.new(name="AI_Camera", object_data=cdata)
                bpy.context.collection.objects.link(cobj)
                cobj.location = (5.5, -5.5, 3.8)
                direction = Vector((0.0, 0.0, 0.5)) - cobj.location
                cobj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
                bpy.context.scene.camera = cobj
                return True, "Added & aimed AI_Camera."
            elif op == "RENDER_IMG":
                bpy.ops.render.render('INVOKE_DEFAULT')
                return True, "Started non-blocking image render."
            elif op == "RENDER_ANIM":
                bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
                return True, "Started non-blocking animation render."

        elif func_name == "create_primitive":
            ptype = args.get("primitive_type", "CUBE").upper()
            loc = tuple(args.get("location", [0.0, 0.0, 0.0]))
            scale = tuple(args.get("scale", [1.0, 1.0, 1.0]))
            name = args.get("name", "")
            color = args.get("color_rgba", None)
            smooth = bool(args.get("shade_smooth", False))

            ops_map = {
                "CUBE": bpy.ops.mesh.primitive_cube_add,
                "SPHERE": bpy.ops.mesh.primitive_uv_sphere_add,
                "CYLINDER": bpy.ops.mesh.primitive_cylinder_add,
                "CONE": bpy.ops.mesh.primitive_cone_add,
                "PLANE": bpy.ops.mesh.primitive_plane_add,
                "TORUS": bpy.ops.mesh.primitive_torus_add,
            }
            if ptype not in ops_map:
                return False, f"Unknown primitive: {ptype}"

            ops_map[ptype](location=loc)
            obj = bpy.context.active_object
            obj.scale = scale
            if name:
                obj.name = name
            if smooth:
                bpy.ops.object.shade_smooth()
            if color and len(color) >= 3:
                _assign_pbr_material(obj, color_rgba=color)
            return True, f"Created {ptype} '{obj.name}' at {loc}."

        elif func_name == "apply_material":
            obj_name = args.get("object_name", "")
            obj = bpy.data.objects.get(obj_name) or bpy.context.active_object
            if not obj or obj.type != 'MESH':
                return False, f"Mesh object '{obj_name}' not found."
            _assign_pbr_material(
                obj,
                color_rgba=args.get("color_rgba", [0.8, 0.8, 0.8, 1.0]),
                metallic=float(args.get("metallic", 0.0)),
                roughness=float(args.get("roughness", 0.4)),
                transmission=float(args.get("transmission", 0.0)),
                emission_strength=float(args.get("emission_strength", 0.0)),
            )
            return True, f"Applied material to '{obj.name}'."

        elif func_name == "add_modifier":
            obj_name = args.get("object_name", "")
            obj = bpy.data.objects.get(obj_name) or bpy.context.active_object
            if not obj or obj.type != 'MESH':
                return False, f"Mesh object '{obj_name}' not found."
            mtype = args.get("modifier_type", "SUBSURF").upper()
            mod = obj.modifiers.new(name=f"AI_{mtype}", type=mtype)
            if mtype == "SUBSURF":
                lvl = int(args.get("levels", 2))
                mod.levels = lvl
                mod.render_levels = lvl
            elif mtype == "BEVEL":
                mod.width = float(args.get("width", 0.05))
                mod.segments = int(args.get("segments", 3))
            elif mtype == "SOLIDIFY":
                mod.thickness = float(args.get("thickness", 0.05))
            elif mtype == "ARRAY":
                mod.count = int(args.get("count", 3))
            return True, f"Added {mtype} modifier to '{obj.name}'."

        elif func_name == "transform_object":
            obj_name = args.get("object_name", "")
            obj = bpy.data.objects.get(obj_name) or bpy.context.active_object
            if not obj:
                return False, f"Object '{obj_name}' not found."
            if args.get("location"):
                obj.location = tuple(args["location"])
            if args.get("rotation_deg"):
                obj.rotation_euler = tuple(math.radians(a) for a in args["rotation_deg"])
            if args.get("scale"):
                obj.scale = tuple(args["scale"])
            return True, f"Transformed '{obj.name}'."

        elif func_name == "delete_object":
            obj_name = args.get("object_name", "")
            obj = bpy.data.objects.get(obj_name)
            if not obj:
                return False, f"Object '{obj_name}' not found."
            bpy.data.objects.remove(obj, do_unlink=True)
            return True, f"Deleted '{obj_name}'."

        elif func_name == "animate_object":
            obj_name = args.get("object_name", "")
            obj = bpy.data.objects.get(obj_name) or bpy.context.active_object
            if not obj:
                return False, f"Object '{obj_name}' not found."
            f_start = int(args.get("start_frame", 1))
            f_end = int(args.get("end_frame", 60))
            obj.keyframe_insert(data_path="location", frame=f_start)
            obj.keyframe_insert(data_path="rotation_euler", frame=f_start)
            if args.get("end_location"):
                obj.location = tuple(args["end_location"])
            if args.get("end_rotation_deg"):
                obj.rotation_euler = tuple(math.radians(a) for a in args["end_rotation_deg"])
            obj.keyframe_insert(data_path="location", frame=f_end)
            obj.keyframe_insert(data_path="rotation_euler", frame=f_end)
            return True, f"Animated '{obj.name}' (frames {f_start}-{f_end})."

        elif func_name == "run_bpy_script":
            code = args.get("code", "")
            bpy.context.scene.gemini_last_code = code
            return safety.execute_safe_code(code)

        return False, f"Unknown tool: {func_name}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}"

def _assign_pbr_material(obj, color_rgba, metallic=0.0, roughness=0.4, transmission=0.0, emission_strength=0.0):
    rgba = (
        float(color_rgba[0]),
        float(color_rgba[1]),
        float(color_rgba[2]),
        float(color_rgba[3]) if len(color_rgba) > 3 else 1.0,
    )
    mat = bpy.data.materials.new(name=f"{obj.name}_Mat")
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = rgba
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = transmission
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = transmission
        if emission_strength > 0:
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = rgba
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emission_strength
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

# --- 3. GEMINI FUNCTION CALLING DECLARATIONS ---
def get_gemini_tools() -> list:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="create_primitive",
                    description="Create a 3D primitive mesh (CUBE, SPHERE, CYLINDER, CONE, PLANE, TORUS) with optional position, scale, name, smooth shading, and RGBA color.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "primitive_type": types.Schema(type=types.Type.STRING, description="CUBE, SPHERE, CYLINDER, CONE, PLANE, or TORUS"),
                            "name": types.Schema(type=types.Type.STRING, description="Object name"),
                            "location": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[x, y, z]"),
                            "scale": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[sx, sy, sz]"),
                            "color_rgba": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[r, g, b, a] 0.0-1.0"),
                            "shade_smooth": types.Schema(type=types.Type.BOOLEAN, description="Enable smooth shading"),
                        },
                        required=["primitive_type"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="apply_material",
                    description="Apply a PBR material (color, metallic, roughness, glass transmission, or neon glow emission) to an existing mesh object.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "object_name": types.Schema(type=types.Type.STRING, description="Target object name"),
                            "color_rgba": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[r, g, b, a] 0.0-1.0"),
                            "metallic": types.Schema(type=types.Type.NUMBER, description="0.0 to 1.0"),
                            "roughness": types.Schema(type=types.Type.NUMBER, description="0.0 (glossy) to 1.0 (matte)"),
                            "transmission": types.Schema(type=types.Type.NUMBER, description="0.0 to 1.0 (1.0 for glass)"),
                            "emission_strength": types.Schema(type=types.Type.NUMBER, description="0.0 for none, >1.0 for glow"),
                        },
                        required=["object_name", "color_rgba"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="add_modifier",
                    description="Add a modifier (SUBSURF, BEVEL, SOLIDIFY, ARRAY, MIRROR) to an object.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "object_name": types.Schema(type=types.Type.STRING, description="Target object name"),
                            "modifier_type": types.Schema(type=types.Type.STRING, description="SUBSURF, BEVEL, SOLIDIFY, ARRAY, or MIRROR"),
                            "levels": types.Schema(type=types.Type.INTEGER, description="Subsurf levels (1-3)"),
                            "width": types.Schema(type=types.Type.NUMBER, description="Bevel width"),
                            "segments": types.Schema(type=types.Type.INTEGER, description="Bevel segments"),
                            "thickness": types.Schema(type=types.Type.NUMBER, description="Solidify thickness"),
                            "count": types.Schema(type=types.Type.INTEGER, description="Array count"),
                        },
                        required=["object_name", "modifier_type"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="transform_object",
                    description="Move, rotate (in degrees), or scale an existing object in the scene.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "object_name": types.Schema(type=types.Type.STRING, description="Object name"),
                            "location": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[x, y, z]"),
                            "rotation_deg": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[rx, ry, rz] degrees"),
                            "scale": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="[sx, sy, sz]"),
                        },
                        required=["object_name"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="delete_object",
                    description="Delete an object from the Blender scene by name.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "object_name": types.Schema(type=types.Type.STRING, description="Object name to delete"),
                        },
                        required=["object_name"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="animate_object",
                    description="Keyframes an object's location and/or rotation between start_frame and end_frame.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "object_name": types.Schema(type=types.Type.STRING, description="Object name"),
                            "start_frame": types.Schema(type=types.Type.INTEGER, description="Start frame"),
                            "end_frame": types.Schema(type=types.Type.INTEGER, description="End frame"),
                            "end_location": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="Target [x, y, z]"),
                            "end_rotation_deg": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.NUMBER), description="Target [rx, ry, rz] degrees"),
                        },
                        required=["object_name", "start_frame", "end_frame"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="run_bpy_script",
                    description="Execute a complete, safe Blender Python (bpy/bmesh) script for complex 3D modeling, characters, procedural environments, lighting, or shaders.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "code": types.Schema(type=types.Type.STRING, description="Valid Python code using bpy, bmesh, math, mathutils, random. Never import os/sys/subprocess."),
                        },
                        required=["code"],
                    ),
                ),
            ]
        )
    ]