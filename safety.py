import ast
import bpy
import bmesh
import math
import mathutils
import random

BLOCKED_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "urllib",
    "requests", "pathlib", "importlib", "ctypes", "builtins", "pickle"
}
BLOCKED_FUNCTIONS = {
    "eval", "exec", "open", "compile", "__import__", "input", "getattr", "setattr", "delattr"
}

def validate_code(code_str: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in BLOCKED_MODULES:
                    return False, f"Security Block: Importing '{alias.name}' is blocked."
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in BLOCKED_MODULES:
                return False, f"Security Block: Importing from '{node.module}' is blocked."
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_FUNCTIONS:
                return False, f"Security Block: Calling '{node.func.id}()' is blocked."

    return True, "Safe"

def execute_safe_code(code_str: str) -> tuple[bool, str]:
    is_safe, msg = validate_code(code_str)
    if not is_safe:
        return False, msg

    safe_globals = {
        "__builtins__": {
            "range": range, "len": len, "int": int, "float": float, "str": str,
            "list": list, "dict": dict, "tuple": tuple, "set": set, "bool": bool,
            "min": min, "max": max, "abs": abs, "round": round, "enumerate": enumerate,
            "zip": zip, "print": print, "isinstance": isinstance, "sum": sum,
            "sorted": sorted, "reversed": reversed, "any": any, "all": all
        },
        "bpy": bpy,
        "bmesh": bmesh,
        "math": math,
        "mathutils": mathutils,
        "random": random,
    }

    try:
        exec(code_str, safe_globals, {})
        return True, "Executed successfully."
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}"