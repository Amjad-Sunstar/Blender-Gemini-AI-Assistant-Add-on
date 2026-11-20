import bpy
import os
import json
import tempfile
import urllib.request

HEADERS = {"User-Agent": "BlenderGeminiAIAssistant/3.0"}

def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def download_file(url: str, dest_path: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as f:
        f.write(resp.read())

def search_polyhaven(asset_type: str, query: str) -> list[tuple[str, str]]:
    t_map = {"HDRIS": "hdris", "TEXTURES": "textures", "MODELS": "models"}
    api_type = t_map.get(asset_type.upper(), "hdris")
    data = fetch_json(f"https://api.polyhaven.com/assets?t={api_type}")

    q_words = [w.strip().lower() for w in query.split() if w.strip()]
    results = []
    for asset_id, meta in data.items():
        name = meta.get("name", asset_id)
        tags = " ".join(meta.get("tags", []))
        cats = " ".join(meta.get("categories", []))
        searchable = f"{asset_id} {name} {tags} {cats}".lower()
        if not q_words or all(w in searchable for w in q_words):
            results.append((asset_id, name))
        if len(results) >= 8:
            break
    return results

def _pick_map_url(files_data: dict, keywords: tuple[str, ...], res: str) -> tuple[str | None, str | None]:
    map_key = next((k for k in files_data.keys() if any(kw in k.lower() for kw in keywords)), None)
    if not map_key:
        return None, None
    res_dict = files_data[map_key].get(res, {})
    fmt = "jpg" if "jpg" in res_dict else ("png" if "png" in res_dict else next(iter(res_dict.keys()), None))
    if not fmt:
        return None, None
    return res_dict[fmt]["url"], fmt

def prepare_download(asset_id: str, asset_type: str, resolution: str) -> tuple[dict, str]:
    """Downloads asset maps/files in background thread and returns (paths_dict, mode)."""
    res = resolution.lower()
    files_data = fetch_json(f"https://api.polyhaven.com/files/{asset_id}")
    cache_dir = os.path.join(tempfile.gettempdir(), "blender_polyhaven_cache")
    os.makedirs(cache_dir, exist_ok=True)

    atype = asset_type.upper()
    if atype == "HDRIS":
        hdri_formats = files_data.get("hdri", {}).get(res, {})
        fmt = "hdr" if "hdr" in hdri_formats else ("exr" if "exr" in hdri_formats else None)
        if not fmt:
            raise RuntimeError(f"Resolution {resolution} not available for {asset_id}.")
        url = hdri_formats[fmt]["url"]
        dest = os.path.join(cache_dir, f"{asset_id}_{res}.{fmt}")
        if not os.path.exists(dest):
            download_file(url, dest)
        return {"hdri": dest}, "HDRIS"

    elif atype == "TEXTURES":
        paths = {}
        diff_url, diff_fmt = _pick_map_url(files_data, ("diff", "col", "albedo"), res)
        if not diff_url:
            raise RuntimeError(f"Diffuse map not found for {asset_id}.")
        diff_dest = os.path.join(cache_dir, f"{asset_id}_{res}_diff.{diff_fmt}")
        if not os.path.exists(diff_dest):
            download_file(diff_url, diff_dest)
        paths["diffuse"] = diff_dest

        rough_url, rough_fmt = _pick_map_url(files_data, ("rough",), res)
        if rough_url:
            rough_dest = os.path.join(cache_dir, f"{asset_id}_{res}_rough.{rough_fmt}")
            if not os.path.exists(rough_dest):
                download_file(rough_url, rough_dest)
            paths["roughness"] = rough_dest

        nor_url, nor_fmt = _pick_map_url(files_data, ("nor_gl", "nor_dx", "normal"), res)
        if nor_url:
            nor_dest = os.path.join(cache_dir, f"{asset_id}_{res}_nor.{nor_fmt}")
            if not os.path.exists(nor_dest):
                download_file(nor_url, nor_dest)
            paths["normal"] = nor_dest

        return paths, "TEXTURES"

    elif atype == "MODELS":
        blend_dict = files_data.get("blend", {}).get(res, {}).get("blend", {})
        if blend_dict and "url" in blend_dict:
            url = blend_dict["url"]
            dest = os.path.join(cache_dir, f"{asset_id}_{res}.blend")
            if not os.path.exists(dest):
                download_file(url, dest)
            for inc_path, inc_info in blend_dict.get("include", {}).items():
                inc_dest = os.path.join(cache_dir, inc_path)
                os.makedirs(os.path.dirname(inc_dest), exist_ok=True)
                if not os.path.exists(inc_dest):
                    download_file(inc_info["url"], inc_dest)
            return {"blend": dest}, "MODELS_BLEND"
        raise RuntimeError(f".blend file not available at {resolution} for {asset_id}.")

    raise RuntimeError("Unsupported asset type.")

def apply_asset_on_main_thread(paths: dict, mode: str, asset_id: str) -> str:
    if mode == "HDRIS":
        world = bpy.context.scene.world
        if not world:
            world = bpy.data.worlds.new("World")
            bpy.context.scene.world = world
        if hasattr(world, "use_nodes"):
            world.use_nodes = True
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        nodes.clear()

        out_node = nodes.new("ShaderNodeOutputWorld")
        bg_node = nodes.new("ShaderNodeBackground")
        env_node = nodes.new("ShaderNodeTexEnvironment")
        env_node.image = bpy.data.images.load(paths["hdri"], check_existing=True)

        links.new(env_node.outputs["Color"], bg_node.inputs["Color"])
        links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])
        return f"Applied HDRI: {asset_id}"

    elif mode == "TEXTURES":
        obj = bpy.context.active_object
        if not obj or obj.type != 'MESH':
            bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
            obj = bpy.context.active_object
            bpy.ops.object.shade_smooth()

        mat = bpy.data.materials.new(name=f"PH_{asset_id}")
        if hasattr(mat, "use_nodes"):
            mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")

        # Diffuse Map
        tex_diff = nodes.new("ShaderNodeTexImage")
        tex_diff.location = (-400, 300)
        tex_diff.image = bpy.data.images.load(paths["diffuse"], check_existing=True)
        links.new(tex_diff.outputs["Color"], bsdf.inputs["Base Color"])

        # Roughness Map
        if "roughness" in paths:
            tex_rough = nodes.new("ShaderNodeTexImage")
            tex_rough.location = (-400, 0)
            img_r = bpy.data.images.load(paths["roughness"], check_existing=True)
            try:
                img_r.colorspace_settings.name = 'Non-Color'
            except Exception:
                pass
            tex_rough.image = img_r
            links.new(tex_rough.outputs["Color"], bsdf.inputs["Roughness"])

        # Normal Map
        if "normal" in paths:
            tex_nor = nodes.new("ShaderNodeTexImage")
            tex_nor.location = (-600, -300)
            img_n = bpy.data.images.load(paths["normal"], check_existing=True)
            try:
                img_n.colorspace_settings.name = 'Non-Color'
            except Exception:
                pass
            tex_nor.image = img_n
            nor_map = nodes.new("ShaderNodeNormalMap")
            nor_map.location = (-250, -300)
            links.new(tex_nor.outputs["Color"], nor_map.inputs["Color"])
            links.new(nor_map.outputs["Normal"], bsdf.inputs["Normal"])

        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        return f"Applied Full PBR '{asset_id}' to {obj.name}"

    elif mode == "MODELS_BLEND":
        with bpy.data.libraries.load(paths["blend"], link=False) as (data_from, data_to):
            data_to.objects = data_from.objects
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
        return f"Imported 3D Model: {asset_id}"

    return "Asset loaded."