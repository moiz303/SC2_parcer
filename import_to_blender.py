import bpy
import math
import json
import os
import random
import re
import sys

# ==============================================================================
# 1. ВХОДНЫЕ ПЕРЕМЕННЫЕ И ГЛОБАЛЬНЫЕ НАСТРОЙКИ
# ==============================================================================
# Значения по умолчанию (хардкод переменные вроде fps самого реплея)
JSON_UNIFIED_PATH = r"C:\Users\0\PycharmProjects\SC2_parcer\temp\unified_Blueshift LE.json"
JSON_SPEEDS_PATH = r"C:\Users\0\PycharmProjects\SC2_parcer\speeds.json"
UNITS_MODELS_FOLDER_PATH = r"C:\Users\0\Documents\StarCraft II\unit_models"
BUILDINGS_MODELS_FOLDER_PATH = r"C:\Users\0\Documents\StarCraft II\building_models"
TEXTURES_FOLDER_PATH = r"C:\Users\0\Documents\StarCraft II\textures"
OUTPUT_FILE_PATH = r"C:\Users\0\Desktop\result.mp4"
RENDER_CONFIG = {}
SAVE_FULL_RENDER = False
ANALYSIS = {
    "success": True,
    "start_frame": 14513,
    "end_frame": 15013,
    "duration_frames": 500,
    "center_x": 36.0,
    "center_y": 5.0,
    "error": None
}

COORD_SCALE = 1.0
MODEL_FORWARD_OFFSET = math.pi / 2
MOVEMENT_THRESHOLD = 1.8
ARMY_IDLE_THRESHOLD = 32
BLENDER_FPS = 30
SC2_FPS = 22.4

RACE_MATERIALS = {}
MODEL_CACHE = {}
ANIM_CACHE = {}
SPEED_CACHE = {}
BIRTH_CACHE = {}

RACE_FOLDER_MAP = {
    "Зерги": ["zerg"], "Zerg": ["zerg"],
    "Протоссы": ["protoss"], "Protoss": ["protoss"],
    "Терраны": ["terran"], "Terran": ["terran"],
    "Neutral": ["neutral", "resources", "critters"]
}

# ==============================================================================
# 2. КЛЮЧЕВЫЕ СЛОВА
# ==============================================================================
UNIT_STATE_KEYWORDS = {
    'birth': ['birth', 'spawn', 'hatch', 'warp', 'summon', 'enter', 'appear', 'emerge', 'morphstart'],
    'walk': ['walk', 'move', 'run', 'fly', 'crawl', 'glide', 'sprint', 'travel', 'locomote'],
    'attack': ['attack', 'shoot', 'bite', 'slash', 'cast', 'strike', 'fire', 'melee', 'ranged', 'pounce', 'lunge'],
    'work': ['gather', 'mine', 'harvest', 'repair', 'extract', 'return', 'construct', 'work', 'carry', 'load'],
    'idle': ['stand', 'idle', 'default', 'rest', 'hover', 'float', 'breathe', 'pose', 'fidget', 'alert', 'turn',
             'shift', 'stance'],
    'death': ['death', 'die', 'explode', 'morphend', 'destroy', 'demise', 'kill', 'end', 'collapse'],
    'morph': ['morph', 'mutate', 'transform', 'evolve', 'upgrade', 'metamorph', 'change', 'cocoon', 'egg']
}
BUILDING_STATE_KEYWORDS = {
    'birth': ['birth', 'build', 'construct', 'place', 'hatch', 'root', 'spawn'],
    'walk': ['walk', 'move', 'lift', 'land', 'takeoff', 'relocate', 'uproot'],
    'attack': ['attack', 'shoot', 'defense', 'cast', 'turret', 'fire'],
    'work': ['work', 'activate', 'train', 'research', 'produce', 'generate'],
    'idle': ['stand', 'idle', 'default', 'rest', 'loop', 'standby', 'hum', 'pulse', 'ambient'],
    'death': ['death', 'die', 'explode', 'destroy', 'ruin', 'demolish', 'collapse', 'debris'],
    'morph': ['morph', 'mutate', 'transform', 'evolve', 'upgrade', 'metamorph']
}
ALL_STATE_KEYWORDS = set(
    kw.lower() for kws in (*UNIT_STATE_KEYWORDS.values(), *BUILDING_STATE_KEYWORDS.values()) for kw in kws)


# ==============================================================================
# 3. ТЕХНИЧЕСКИЕ ХЕЛПЕРЫ
# ==============================================================================
def ui_progress(stage, progress, message=""):
    """Микро-хелпер для передачи сообщений с backend на frontend"""
    print(
        "__UI__" +
        json.dumps({
            "stage": stage,
            "progress": progress,
            "message": message
        }),
        flush=True
    )


def sc2_to_blender(x, y, z): return x * COORD_SCALE, -y * COORD_SCALE, z * COORD_SCALE


def normalize_type(obj_type, is_building=False):
    clean = str(obj_type).strip().lower().replace(" ", "")
    if is_building and "mineralfield" in clean:
        clean = re.sub(r'^.*mineralfield.*$', 'labmineralfield', clean)
    return clean


def is_action_empty(action, threshold=1e-4):
    """
    Проверяет, статична ли анимация
    Совместимо и с Blender 4.4+ (Layered Actions), и со старыми версиями.
    """
    fcurves = []

    # 1. Новый API (Blender 4.4+): Action -> layers -> strips -> channelbags -> fcurves
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    fcurves.extend(channelbag.fcurves)

    # 2. Старый API (до Blender 4.4): Action -> fcurves
    elif hasattr(action, 'fcurves'):
        fcurves = action.fcurves
    if not fcurves:
        return True

    for fc in fcurves:
        if fc.keyframe_points:
            vals = [kp.co[1] for kp in fc.keyframe_points]
            if max(vals) - min(vals) > threshold:
                return False
        else:
            try:
                r = fc.range()
                v1 = fc.evaluate(r[0])
                v2 = fc.evaluate(r[1])
                if abs(v2 - v1) > threshold:
                    return False
            except Exception:
                pass
    return True


def clear_scene():
    # 1. Удаляем все объекты
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # 2. Удаляем все анимации
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    # 3. Удаляем библиотеки, чтобы Blender заново прочитал файлы с диска
    for lib in list(bpy.data.libraries):
        bpy.data.libraries.remove(lib)
    # 4. Удаляем все "осиротевшие" Data-блоки (меши, арматуры, материалы и т.д.)
    data_collections = [
        bpy.data.meshes, bpy.data.armatures, bpy.data.materials,
        bpy.data.textures, bpy.data.images, bpy.data.node_groups,
        bpy.data.curves, bpy.data.lights, bpy.data.cameras
    ]
    for collection in data_collections:
        for item in list(collection):
            try:
                collection.remove(item)
            except Exception:
                pass

    # 5. Финальная зачистка сирот
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:
        pass

    # 6. Очищаем глобальные кэши Python
    MODEL_CACHE.clear()
    ANIM_CACHE.clear()
    BIRTH_CACHE.clear()
    RACE_MATERIALS.clear()


def get_race_material(unit_type, race='neutral'):
    if unit_type in RACE_MATERIALS:
        return RACE_MATERIALS[unit_type]

    mat = bpy.data.materials.new(name=f"Mat_{unit_type}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()

    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    tex_node = nodes.new(type='ShaderNodeTexImage')

    tex_path = None

    for suffix in ['_diff.dds', '_diffuse.dds', '_diff.png', '_diffuse.png']:
        path = os.path.join(TEXTURES_FOLDER_PATH, f"{unit_type}{suffix}")
        if os.path.exists(path):
            tex_path = path
            break

    if (tex_path is None) and (
            unit_type == 'destructiblerockex1diagonalhugeblur'):
        tex_path = os.path.join(
            TEXTURES_FOLDER_PATH,
            'purifier_destructible_rock_huge_diff.dds'
        )

    # ---------------- Загрузка текстуры ----------------

    if tex_path:
        try:
            img = bpy.data.images.load(tex_path, check_existing=True)
            tex_node.image = img

            if unit_type == "rocks_newfolsom":
                coord_node = nodes.new(type="ShaderNodeTexCoord")
                links.new(coord_node.outputs["UV"], tex_node.inputs["Vector"])

            links.new(tex_node.outputs["Color"],
                      bsdf_node.inputs["Base Color"])

        except Exception as e:
            print(f"⚠ Ошибка загрузки текстуры {tex_path}: {e}")

    # ---------------- Fallback ----------------

    if not tex_node.image:
        race_clean = str(race).strip().lower()

        race_map = {
            'терраны': 'terran',
            'terran': 'terran',
            'зерги': 'zerg',
            'zerg': 'zerg',
            'протоссы': 'protoss',
            'protoss': 'protoss'
        }

        normalized_race = race_map.get(race_clean, 'neutral')

        colors = {
            'terran': (0.2, 0.5, 0.8, 1.0),
            'zerg': (0.6, 0.2, 0.2, 1.0),
            'protoss': (0.8, 0.7, 0.2, 1.0),
            'neutral': (0.5, 0.5, 0.5, 1.0)
        }

        bsdf_node.inputs["Base Color"].default_value = colors[normalized_race]

    links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    RACE_MATERIALS[unit_type] = mat
    return mat


def create_fallback_object(cache_key, race, prefix="Unit"):
    mesh = bpy.data.meshes.new(f"FB_{cache_key}_mesh")
    verts = [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5), (-0.5, -0.5, 0.5),
             (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 7, 3), (1, 5, 6, 2), (0, 1, 5, 4), (3, 2, 6, 7)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"{prefix}_{cache_key}", mesh)
    bpy.context.collection.objects.link(obj)
    mat = get_race_material(cache_key, race)
    if mat and len(obj.data.materials) == 0: obj.data.materials.append(mat)
    return {"root": obj, "hierarchy": [obj]}


def render_scene(scene, out_file, analysis, save_full: bool):
    # Настройки вывода
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'

    old_start = scene.frame_start
    old_end = scene.frame_end

    # Настройки сцены
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.use_motion_blur = False
    scene.eevee.use_raytracing = False
    scene.eevee.use_volumetric_shadows = False

    scene.frame_start = analysis.get("start_frame", 0)
    scene.frame_end = analysis.get("end_frame", 1000)
    scene.render.filepath = out_file
    bpy.ops.render.render(animation=True)

    if save_full:
        scene.frame_start = old_start
        scene.frame_end = old_end
        scene.render.filepath = out_file
        bpy.ops.render.render(animation=True)

    scene.frame_start = old_start
    scene.frame_end = old_end


def is_valid_file(filename, all_keywords):
    name_lower = filename.lower()
    if '_' not in name_lower: return True
    return name_lower.split('_')[1].split('.')[0] in all_keywords


def classify_action(name, is_building=False):
    n = name.lower()
    target_dict = BUILDING_STATE_KEYWORDS if is_building else UNIT_STATE_KEYWORDS
    for state, kws in target_dict.items():
        if any(kw in n for kw in kws): return state
    fallback_dict = UNIT_STATE_KEYWORDS if is_building else BUILDING_STATE_KEYWORDS
    for state, kws in fallback_dict.items():
        if any(kw in n for kw in kws): return state
    return 'idle'


def duplicate_hierarchy(src_root, src_hier, target_collection):
    obj_map = {}
    for old_obj in src_hier:
        new_obj = old_obj.copy()

        if old_obj.data: new_obj.data = old_obj.data.copy()
        if new_obj.animation_data:
            new_obj.animation_data_clear()

        target_collection.objects.link(new_obj)
        obj_map[old_obj] = new_obj

    for old_obj, new_obj in obj_map.items():
        if old_obj.parent and old_obj.parent in obj_map:
            new_obj.parent = obj_map[old_obj.parent]
            new_obj.matrix_parent_inverse = old_obj.matrix_parent_inverse

    new_armature = next((obj for obj in obj_map.values() if obj.type == 'ARMATURE'), None)
    if new_armature:
        for new_obj in obj_map.values():
            if new_obj.type == 'MESH':
                for mod in new_obj.modifiers:
                    if mod.type == 'ARMATURE':
                        mod.object = new_armature
                        mod.show_viewport = True
                        mod.show_render = True

    return obj_map[src_root]


def set_visibility_keys(obj, hide_start_frame, show_start_frame, hide_end_frame):
    unique_targets = [obj] + list(obj.children_recursive)
    if hide_end_frame <= show_start_frame: hide_end_frame = show_start_frame + 2
    for target in unique_targets:
        if not target.animation_data: target.animation_data_create()
        target.hide_viewport = True
        target.hide_render = True
        target.keyframe_insert("hide_viewport", frame=hide_start_frame)
        target.keyframe_insert("hide_render", frame=hide_start_frame)
        target.hide_viewport = False
        target.hide_render = False
        target.keyframe_insert("hide_viewport", frame=show_start_frame)
        target.keyframe_insert("hide_render", frame=show_start_frame)
        target.hide_viewport = True
        target.hide_render = True
        target.keyframe_insert("hide_viewport", frame=hide_end_frame)
        target.keyframe_insert("hide_render", frame=hide_end_frame)


def add_nla_strip_safe(nla_track, action, start_frame, end_frame, force_loop=False):
    if not action or not hasattr(action, 'frame_range'): return None
    s_f, e_f = int(start_frame), int(end_frame)
    if e_f <= s_f: return None
    strips_to_process = [s for s in nla_track.strips if s.frame_start < e_f and s.frame_end > s_f]
    for s in strips_to_process:
        if s.frame_start >= s_f and s.frame_end <= e_f:
            nla_track.strips.remove(s)
        elif s.frame_start < s_f:
            s.frame_end = s_f
        elif s.frame_end > e_f:
            s.frame_start = e_f
        else:
            nla_track.strips.remove(s)
    try:
        strip = nla_track.strips.new(f"{action.name}_{s_f}", s_f, action)
        strip.action_frame_start, strip.action_frame_end = action.frame_range[0], action.frame_range[1]
        strip.blend_in, strip.blend_out = 0.0, 0.0
        strip.blend_type = 'REPLACE'
        strip.extrapolation = 'HOLD'
        if force_loop:
            act_len = max(1.0, action.frame_range[1] - action.frame_range[0])
            strip.repeat = max(1.0, (e_f - s_f) / act_len)
        else:
            strip.repeat = 1.0
        return strip
    except RuntimeError:
        return None


def force_keyframe(obj, prop, frame, value=None):
    obj.rotation_mode = 'XYZ'
    obj.lock_location = (False, False, False)
    obj.lock_rotation = (False, False, False)
    obj.lock_scale = (False, False, False)
    if value is not None:
        if prop == "location":
            obj.location = value
        elif prop == "rotation_euler":
            obj.rotation_euler = value
    obj.keyframe_insert(prop, frame=frame)


# ==============================================================================
# 4. СЕТАПЫ ОСВЕЩЕНИЯ, КАМЕРЫ И СЦЕНЫ
# ==============================================================================
def setup_scene_lighting():

    world = bpy.context.scene.world
    if not world:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Color"].default_value = (0.65, 0.7, 0.75, 1.0)
        bg_node.inputs["Strength"].default_value = 0.5
    sun_data = bpy.data.lights.new(name="SC2_Sun", type='SUN')
    sun_data.energy = 2.0  # Энергия света
    sun_data.color = (1.0, 0.98, 0.95)  # Теплый белый, чтобы текстуры не синили
    sun_data.angle = math.radians(2.5)  # Легкая мягкость теней

    sun_obj = bpy.data.objects.new("SC2_Sun", sun_data)
    bpy.context.collection.objects.link(sun_obj)

    sun_obj.rotation_euler = (math.radians(45), math.radians(15), math.radians(30))


def setup_ground_plane():
    global TEXTURES_FOLDER_PATH

    mesh = bpy.data.meshes.new("Ground_Mesh")
    verts = [(-250, -250, 0), (250, -250, 0), (250, 250, 0), (-250, 250, 0)]
    faces = [(0, 1, 2, 3)]

    mesh.from_pydata(verts, [], faces)
    mesh.update()

    uv_layer = mesh.uv_layers.new(name="UVMap")

    # Повторяем текстуру 10×10 раз
    uvs = [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
    ]

    for loop, uv in zip(mesh.loops, uvs):
        uv_layer.data[loop.index].uv = uv

    ground_obj = bpy.data.objects.new("Ground_Plane", mesh)
    bpy.context.collection.objects.link(ground_obj)
    ground_obj.location.z = 0

    mat = get_race_material("rocks_newfolsom")
    ground_obj.data.materials.append(mat)


def setup_analysis_camera(analysis):
    center_x, center_y, _ = sc2_to_blender(analysis.get('center_x', 0.0), analysis.get('center_y', 0.0), 0.0)
    start, end = analysis.get("start_frame", 0), analysis.get("end_frame", 1000)

    pivot = bpy.data.objects.new("AnalysisPivot", None)
    pivot.empty_display_type = 'PLAIN_AXES'
    pivot.location = (center_x, center_y, 0)
    bpy.context.collection.objects.link(pivot)

    cam = bpy.data.cameras.new("AnalysisCamera")
    cam.clip_start = 0.5
    cam.clip_end = 350

    cam_obj = bpy.data.objects.new("AnalysisCamera", cam)
    radius, height = 65, 45
    cam_obj.location = (0, -radius, height)
    cam_obj.data.lens = 70.0

    bpy.context.collection.objects.link(cam_obj)
    cam_obj.parent = pivot

    track = cam_obj.constraints.new('TRACK_TO')
    track.target = pivot
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    pivot.rotation_euler[2] = 0
    pivot.keyframe_insert("rotation_euler", frame=start)

    pivot.rotation_euler[2] = math.tau
    pivot.keyframe_insert("rotation_euler", frame=end)

    bpy.context.scene.camera = cam_obj
    return cam_obj


# ==============================================================================
# 5. ФАЗА 1: ПРЕДОБРАБОТКА (СДВИГ ЗДАНИЯ + ТРАНСФОРМОВ)
# ==============================================================================
def preprocess_data(units_data, buildings_data):
    global SC2_FPS, SPEED_CACHE, BIRTH_CACHE, ANIM_CACHE

    if os.path.exists(JSON_SPEEDS_PATH):
        with open(JSON_SPEEDS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            SPEED_CACHE = {k.lower().strip(): float(v) for k, v in data.items()}

    required_types = set()
    for u in units_data:
        if u.get('type'): required_types.add(normalize_type(u['type']))
    for b in buildings_data:
        if b.get('type'): required_types.add(normalize_type(b['type'], is_building=True))
        for t in b.get('transforms', []):
            if t.get('from_type'): required_types.add(normalize_type(t['from_type'], is_building=True))
            if t.get('to_type'): required_types.add(normalize_type(t['to_type'], is_building=True))

    for bldg in buildings_data:
        original_init_frame = bldg.get('init_frame', 0)
        born_frame = bldg.get('born_frame', -1)

        if born_frame == 0 or original_init_frame == 0:
            bldg['is_starting'] = True
            bldg['construction_start_frame'] = 1
            bldg['init_frame'] = 1
            bldg['birth_dur'] = 0
            continue

        bldg['is_starting'] = False
        if original_init_frame <= 0: continue

        b_type = normalize_type(bldg.get('type', ''), is_building=True)
        birth_dur = BIRTH_CACHE.get(b_type, 0.0)

        if birth_dur == 0.0 and b_type in ANIM_CACHE:
            anims = ANIM_CACHE[b_type]
            birth_anims = anims.get('birth', []) + anims.get('build', []) + anims.get('morph', [])
            if birth_anims: birth_dur = birth_anims[0].frame_range[1] - birth_anims[0].frame_range[0]
        if birth_dur == 0.0: birth_dur = 65.0 * (BLENDER_FPS / SC2_FPS)

        bldg['birth_dur'] = birth_dur

        construction_start = int(original_init_frame - birth_dur)
        construction_end = int(original_init_frame)

        bldg['construction_start_frame'] = construction_start
        bldg['finished_frame'] = construction_end

        if ('creeptumor' in b_type) or ('autoturret' in b_type) or ('nydusworm' in b_type):
            required_builders = ['']
        else:
            required_builders = ['drone', 'scv', 'probe', 'mule', 'worker']

        bldg_coords = bldg['frames'][0]
        bx, by = bldg_coords['x'], bldg_coords['y']

        matched_builder = None
        best_score = 999999
        actual_arrival_frame = -1

        for unit in units_data:
            if unit.get('matched'): continue
            if unit.get('owner_name') != bldg.get('owner_name'): continue

            u_type = normalize_type(unit.get('type', ''))
            if u_type not in required_builders: continue

            positions = unit.get('positions', [])
            if not positions: continue

            min_dist = 99999
            unit_arrival_frame = -1

            for p in positions:
                dist = math.hypot(p['x'] - bx, p['y'] - by)
                if dist < 4.0:
                    if dist < min_dist:
                        min_dist = dist
                        unit_arrival_frame = p['frame']

            if unit_arrival_frame == -1:
                for p in positions:
                    dist = math.hypot(p['x'] - bx, p['y'] - by)
                    if dist < min_dist:
                        min_dist = dist
                        unit_arrival_frame = p['frame']

            if min_dist < 15.0 and unit_arrival_frame > 0:
                score = min_dist * 10
                if score < best_score:
                    best_score = score
                    matched_builder = unit
                    actual_arrival_frame = unit_arrival_frame

        if matched_builder and actual_arrival_frame > 0:
            u_type = normalize_type(matched_builder['type'])
            is_drone = (u_type == "drone")

            matched_builder["matched"] = True

            build_point = {
                "frame": construction_start,
                "x": bx,
                "y": by,
                "z": bldg_coords.get("z", 0.0)
            }

            positions = sorted(matched_builder["positions"], key=lambda p: p["frame"])
            arrival_index = None

            for i, p in enumerate(positions):
                dist = math.hypot(p["x"] - bx, p["y"] - by)
                if dist < 2.0:
                    arrival_index = i
                    break

            if arrival_index is None:
                arrival_index = len(positions) - 1

            arrival_frame = positions[arrival_index]["frame"]

            if arrival_frame > construction_start:
                shift = arrival_frame - construction_start
                for i in range(arrival_index + 1):
                    positions[i]["frame"] -= shift

                if matched_builder.get("init_frame") is not None:
                    matched_builder["init_frame"] -= shift

            positions = [
                p for p in positions
                if p["frame"] < construction_start
            ]

            # Добавляем синтетические точки для анимации стройки
            positions.append(build_point)
            positions.append({
                "frame": construction_end,
                "x": bx,
                "y": by,
                "z": bldg_coords.get("z", 0.0)
            })

            positions.sort(key=lambda p: p["frame"])
            matched_builder["positions"] = positions

            matched_builder["build_work"] = {
                "start": construction_start,
                "end": construction_end
            }

            if is_drone:
                matched_builder["died_frame"] = construction_start

    return units_data, buildings_data, required_types


# ==============================================================================
# 6. ФАЗА 2: ЦЕЛЕВАЯ ЗАГРУЗКА РЕСУРСОВ (С ФИЛЬТРАЦИЕЙ ПУСТЫХ АНИМАЦИЙ)
# ==============================================================================
def load_resources_from_folder(base_folder, all_subfolders, required_types, is_building_folder):
    if not os.path.exists(base_folder): return
    loaded_count = 0
    for subfolder in all_subfolders:
        folder_path = os.path.join(base_folder, subfolder)
        if not os.path.isdir(folder_path): continue
        for entry in os.scandir(folder_path):
            if not entry.is_file() or not entry.name.lower().endswith('.blend'): continue
            filename = entry.name
            name_lower = filename.lower()
            base_name = os.path.splitext(name_lower)[0]
            file_type_raw = base_name.split('_', 1)[0]
            file_type = normalize_type(file_type_raw, is_building=is_building_folder)
            if file_type not in required_types: continue
            if not is_valid_file(filename, ALL_STATE_KEYWORDS): continue

            with bpy.data.libraries.load(entry.path) as (data_from, data_to):
                data_to.objects = [name for name in data_from.objects if not name.startswith("Group")]
                valid_action_names = [
                    act_name for act_name in data_from.actions
                    if any(kw in act_name.lower() for kw in ALL_STATE_KEYWORDS)
                ]
                data_to.actions = valid_action_names
            for obj in data_to.objects:
                if obj:
                    obj.make_local()
                    if obj.data:
                        obj.data.make_local()
                        if obj.type == 'MESH':
                            mat = get_race_material(file_type, 'neutral')
                            if mat:
                                obj.data.materials.clear()
                                obj.data.materials.append(mat)
            for act in data_to.actions:
                if act:
                    act.make_local()

            if file_type not in MODEL_CACHE and data_to.objects:
                loaded_names = {obj.name for obj in data_to.objects}
                root_obj = next(
                    (obj for obj in data_to.objects if not obj.parent or obj.parent.name not in loaded_names),
                    data_to.objects[0])
                MODEL_CACHE[file_type] = {"root": root_obj, "hierarchy": list(data_to.objects)}
                loaded_count += 1

            if data_to.actions:
                if file_type not in ANIM_CACHE: ANIM_CACHE[file_type] = {}
                for action in data_to.actions:
                    if is_action_empty(action):
                        continue

                    state = classify_action(action.name, is_building=is_building_folder)
                    if state not in ANIM_CACHE[file_type]: ANIM_CACHE[file_type][state] = []
                    ANIM_CACHE[file_type][state].append(action)

                    if state in ['birth', 'morph', 'build']:
                        try:
                            dur = action.frame_range[1] - action.frame_range[0]
                            if dur > BIRTH_CACHE.get(file_type, 0): BIRTH_CACHE[file_type] = dur
                        except:
                            pass


# ==============================================================================
# 7. ФАЗА 3: ИМПОРТ ЮНИТОВ
# ==============================================================================
def get_safe_pool(anims_dict, *states):
    for s in states:
        pool = anims_dict.get(s, [])
        if pool: return pool
    return []


def import_units(units_data):
    cnt = 0
    for u in units_data:
        ut, rc = u['type'], u.get('owner_race', 'Neutral')
        born = u.get('born_frame', 0)
        died = u.get('died_frame') or 99999
        pos = u.get('positions', [])
        if not pos: continue

        ck = normalize_type(ut)
        src_data = MODEL_CACHE.get(ck, create_fallback_object(ck, rc))
        nr = duplicate_hierarchy(src_data["root"], src_data["hierarchy"], bpy.context.collection)
        nr.name = f"Unit_{ut}_{cnt}"

        for obj in nr.children_recursive:
            if obj.animation_data: obj.animation_data_clear()
        if nr.animation_data: nr.animation_data_clear()

        arm = nr if nr.type == 'ARMATURE' else next((c for c in nr.children_recursive if c.type == 'ARMATURE'),
                                                    nr.find_armature())
        pos = sorted(pos, key=lambda p: p.get('frame', 0))
        base_speed = SPEED_CACHE.get(ut, SPEED_CACHE.get(ck, 2.25))

        if arm:
            if not arm.animation_data: arm.animation_data_create()
            for tr in list(arm.animation_data.nla_tracks): arm.animation_data.nla_tracks.remove(tr)
            arm.animation_data.action = None
            nla_track = arm.animation_data.nla_tracks.new()
            nla_track.name = f"NLA_{arm.name}"

            p0 = pos[0]
            x0, y0, z0 = sc2_to_blender(p0['x'], p0['y'], p0.get('z', 0))
            force_keyframe(nr, "location", born, (x0, y0, z0))
            force_keyframe(nr, "rotation_euler", born, (0.0, 0.0, MODEL_FORWARD_OFFSET))

            prev_frame = born
            prev_pos = (x0, y0, z0)
            prev_rot = MODEL_FORWARD_OFFSET
            anims = ANIM_CACHE.get(ck, {})

            birth_pool = get_safe_pool(anims, 'birth', 'spawn', 'warp', 'morph')
            birth_end_frame = born

            if birth_pool:
                birth_act = random.choice(birth_pool)
                birth_dur = int(birth_act.frame_range[1] - birth_act.frame_range[0])
                birth_end_frame = born + birth_dur
                add_nla_strip_safe(nla_track, birth_act, born, birth_end_frame, force_loop=False)
            else:
                idle_pool = get_safe_pool(anims, 'idle', 'stand', 'default')
                if idle_pool:
                    idle_act = random.choice(idle_pool)
                    buffer_dur = min(60, int(idle_act.frame_range[1] - idle_act.frame_range[0]))
                    if buffer_dur < 10: buffer_dur = 15

                    birth_end_frame = born + buffer_dur
                    add_nla_strip_safe(nla_track, idle_act, born, birth_end_frame, force_loop=True)

            prev_frame = birth_end_frame

            for i in range(len(pos)):
                p = pos[i]
                curr_frame = p.get('frame', 0)
                if curr_frame <= prev_frame: continue

                new_pos = sc2_to_blender(p['x'], p['y'], p.get('z', 0))
                dist = math.hypot(new_pos[0] - prev_pos[0], new_pos[1] - prev_pos[1])
                is_moving = (dist > MOVEMENT_THRESHOLD) or (i == len(pos) - 1 and dist > 0.1)

                force_keyframe(nr, "location", prev_frame, prev_pos)
                force_keyframe(nr, "location", curr_frame, new_pos)

                if is_moving:
                    pool = get_safe_pool(anims, 'walk', 'move', 'run')
                elif u.get('is_army', True) and (curr_frame - prev_frame) < ARMY_IDLE_THRESHOLD:
                    pool = get_safe_pool(anims, 'attack', 'shoot', 'cast')
                else:
                    pool = get_safe_pool(anims, 'work', 'idle', 'stand')

                if not pool: pool = anims.get('idle', [])
                if pool:
                    act = random.choice(pool)
                    strip = add_nla_strip_safe(nla_track, act, prev_frame, curr_frame, force_loop=True)

                    if is_moving and dist > 0.01 and base_speed > 0:
                        frame_diff = curr_frame - prev_frame
                        if frame_diff > 0:
                            game_dist = dist / COORD_SCALE
                            game_time_seconds = frame_diff / BLENDER_FPS
                            actual_speed = game_dist / game_time_seconds
                            if actual_speed > 0:
                                anim_scale = max(0.2, min(5.0, base_speed / actual_speed))
                                if strip and hasattr(strip, 'scale'): strip.scale = anim_scale

                if is_moving and dist > 0.1:
                    target_rot = math.atan2(new_pos[1] - prev_pos[1], new_pos[0] - prev_pos[0]) + MODEL_FORWARD_OFFSET
                    diff = target_rot - prev_rot
                    if diff > math.pi:
                        diff -= 2 * math.pi
                    elif diff < -math.pi:
                        diff += 2 * math.pi
                    prev_rot += diff
                    force_keyframe(nr, "rotation_euler", prev_frame, (0.0, 0.0, prev_rot))
                    force_keyframe(nr, "rotation_euler", curr_frame, (0.0, 0.0, prev_rot))

                prev_pos = new_pos
                prev_frame = curr_frame

            if died and died > prev_frame:
                force_keyframe(nr, "location", died, prev_pos)
                force_keyframe(nr, "rotation_euler", died, (0.0, 0.0, prev_rot))
                death_pool = anims.get('death', []) + anims.get('die', []) + anims.get('explode', [])
                if death_pool:
                    add_nla_strip_safe(nla_track, random.choice(death_pool), prev_frame, died, force_loop=False)

            show_start = max(1, born)
            set_visibility_keys(nr, show_start - 1, show_start, died)
        cnt += 1


# ==============================================================================
# 8. ФАЗА 4: ИМПОРТ ЗДАНИЙ
# ==============================================================================
def import_buildings(buildings_data, max_frame):
    for idx, bldg in enumerate(buildings_data):
        frames = bldg.get('frames', [])
        if not frames: continue

        is_starting = bldg.get('is_starting', False)
        construction_start = bldg.get('construction_start_frame', 1)
        if construction_start <= 0: construction_start = 0
        died_frame = bldg.get('died_frame') or max_frame

        f0 = frames[0]
        base_type = normalize_type(bldg.get('type', ''), is_building=True)

        raw_transforms = bldg.get('transforms', [])
        transforms = sorted([
            t for t in raw_transforms
            if t.get('frame') and t.get('to_type') and int(t['frame']) < died_frame
        ], key=lambda t: int(t['frame']))

        segments = []
        if not transforms:
            segments.append({
                'type': base_type, 'start': construction_start, 'end': died_frame,
                'is_birth': not is_starting, 'is_morph': False, 'is_starting': is_starting
            })
        else:
            first_from = transforms[0].get('from_type') or transforms[0].get('From_Type') or base_type
            first_type = normalize_type(first_from, is_building=True)

            segments.append({
                'type': first_type, 'start': construction_start, 'end': transforms[0]['frame'],
                'is_birth': not is_starting, 'is_morph': False, 'is_starting': is_starting
            })

            for i in range(len(transforms)):
                t = transforms[i]
                morph_type = normalize_type(t['to_type'], is_building=True)
                start_f = t['frame']
                end_f = int(transforms[i + 1]['frame']) if i + 1 < len(transforms) else died_frame

                segments.append({
                    'type': morph_type, 'start': start_f, 'end': end_f,
                    'is_birth': False, 'is_morph': True, 'is_starting': False
                })

        for seg in segments:
            if seg['start'] < seg['end']:
                _spawn_building_segment(seg, bldg, f0, idx)


def _spawn_building_segment(seg, bldg, f0, obj_index):
    b_type = seg['type']
    race = bldg.get('race', 'Neutral')
    start_f = seg['start']
    end_f = seg['end']
    is_birth = seg['is_birth']
    is_morph = seg['is_morph']
    is_starting = seg.get('is_starting', False)

    if start_f >= end_f: return

    ck = normalize_type(b_type, is_building=True)
    src_data = MODEL_CACHE.get(ck, create_fallback_object(ck, race, "Building"))

    nr = duplicate_hierarchy(src_data["root"], src_data["hierarchy"], bpy.context.collection)
    nr.name = f"Building_{b_type}_{obj_index}_{int(start_f)}"

    x, y, z = sc2_to_blender(f0['x'], f0['y'], f0.get('z', 0))
    force_keyframe(nr, "location", 1, (x, y, z))

    anims = ANIM_CACHE.get(ck, {})

    if is_starting:
        anim_seq = []
    elif is_morph:
        anim_seq = anims.get('morph', [])
        if not anim_seq: anim_seq = anims.get('build', [])
        if not anim_seq: anim_seq = anims.get('birth', [])
    elif is_birth:
        anim_seq = anims.get('birth', []) + anims.get('build', [])
    else:
        anim_seq = []

    arm = nr if nr.type == 'ARMATURE' else next((c for c in nr.children_recursive if c.type == 'ARMATURE'),
                                                nr.find_armature())
    target = arm if arm else nr

    if not target.animation_data: target.animation_data_create()
    for tr in list(target.animation_data.nla_tracks): target.animation_data.nla_tracks.remove(tr)
    target.animation_data.action = None

    nla = target.animation_data.nla_tracks.new()
    nla.name = f"NLA_{nr.name}"

    current_time = start_f
    if anim_seq:
        act = random.choice(anim_seq)
        act_dur = int(act.frame_range[1] - act.frame_range[0])
        act_end = min(current_time + act_dur, end_f)
        add_nla_strip_safe(nla, act, current_time, act_end, force_loop=False)
        current_time = act_end

    idle_pool = anims.get('idle', []) + anims.get('work', []) + anims.get('stand', [])
    idle_pool = [a for a in idle_pool if
                 not any(kw in a.name.lower() for kw in ['birth', 'build', 'morph', 'transform', 'hatch'])]

    if current_time < end_f and idle_pool:
        idle_act = random.choice(idle_pool)
        add_nla_strip_safe(nla, idle_act, current_time, end_f, force_loop=True)

    show_frame = 1 if is_starting else start_f
    set_visibility_keys(nr, 1, show_frame, end_f)


# ==============================================================================
# 9. ГЛАВНЫЙ ЦИКЛ
# ==============================================================================
def import_all():
    global SC2_FPS, JSON_UNIFIED_PATH, UNITS_MODELS_FOLDER_PATH, BUILDINGS_MODELS_FOLDER_PATH, \
        SAVE_FULL_RENDER, ANALYSIS, OUTPUT_FILE_PATH
    ui_progress("import_scene", 0, "Очистка сцены...")
    clear_scene()

    ui_progress("import_scene", 10, "Чтение метаданных...")
    if not os.path.exists(JSON_UNIFIED_PATH):
        print(f"Ошибка: Файл {JSON_UNIFIED_PATH} не найден!")
        return

    with open(JSON_UNIFIED_PATH, 'r') as f:
        replay_data = json.load(f)

    dur = replay_data.get('metadata', {'duration': '20 m 0 s'}).get('duration', '20 m 0 s').split()
    max_frame = int(SC2_FPS * (int(dur[0]) * 60 + int(dur[2])))
    races_in_replay = set(RACE_FOLDER_MAP.get('Neutral')) | set(
        [RACE_FOLDER_MAP.get(player.get('race'), [""])[0] for player in
         replay_data.get('metadata', {}).get('players', [])])

    units_data = replay_data.get('units', [])
    buildings_data = replay_data.get('buildings', [])

    ui_progress("import_scene", 20, "Настройка освещения и размещение поверхности...")
    setup_scene_lighting()
    setup_ground_plane()

    ui_progress("import_scene", 35, "Загрузка ресурсов...")
    required_types = set()
    for u in units_data:
        if u.get('type'): required_types.add(normalize_type(u['type']))
    for b in buildings_data:
        if b.get('type'): required_types.add(normalize_type(b['type'], is_building=True))
        for t in b.get('transforms', []):
            if t.get('from_type'): required_types.add(normalize_type(t['from_type'], is_building=True))
            if t.get('to_type'): required_types.add(normalize_type(t['to_type'], is_building=True))

    load_resources_from_folder(UNITS_MODELS_FOLDER_PATH, races_in_replay, required_types, is_building_folder=False)
    load_resources_from_folder(BUILDINGS_MODELS_FOLDER_PATH, races_in_replay, required_types, is_building_folder=True)

    ui_progress("import_scene", 55, "Предобработка...")
    units_data, buildings_data, _ = preprocess_data(units_data, buildings_data)

    ui_progress("import_scene", 70, "Генерация сцены...")
    import_units(units_data)
    import_buildings(buildings_data, max_frame)

    ui_progress("import_scene", 80, "Подготовка пролёта камеры...")
    camera, scene = None, bpy.context.scene
    if ANALYSIS and ANALYSIS.get("success"):
        camera = setup_analysis_camera(ANALYSIS)
    scene.camera = camera

    ui_progress("import_scene", 90, "Финализация сцены...")
    final_frame = max_frame + 100
    scene.frame_start = 0
    scene.frame_end = final_frame
    scene.render.fps = BLENDER_FPS
    ui_progress("import_scene", 100, "ГОТОВО")

    render_scene(scene, OUTPUT_FILE_PATH, ANALYSIS, SAVE_FULL_RENDER)


def load_config_from_args():
    """
    Парсит аргументы из sys.argv.
    Input: blender --background --python script.py -- render_payload.json output.mp4
    """
    global JSON_UNIFIED_PATH, JSON_SPEEDS_PATH, UNITS_MODELS_FOLDER_PATH, \
        BUILDINGS_MODELS_FOLDER_PATH, TEXTURES_FOLDER_PATH, OUTPUT_FILE_PATH, RENDER_CONFIG, \
        SAVE_FULL_RENDER, ANALYSIS

    separator_idx = -1
    try:
        separator_idx = sys.argv.index("--")
    except ValueError:
        pass

    args_start_idx = separator_idx + 1 if separator_idx >= 0 else 1
    remaining_args = sys.argv[args_start_idx:] if args_start_idx < len(sys.argv) else []

    render_payload_path = None
    output_file = None

    for i, arg in enumerate(remaining_args):
        if arg.endswith('.json') and os.path.exists(arg):
            render_payload_path = arg
            if i + 1 < len(remaining_args):
                output_file = remaining_args[i + 1]
            break

    if not render_payload_path and len(remaining_args) >= 2:
        render_payload_path = remaining_args[0]
        output_file = remaining_args[1]
    if render_payload_path and os.path.exists(render_payload_path):
        try:
            with open(render_payload_path, 'r', encoding='utf-8') as f:
                RENDER_CONFIG = json.load(f)

            JSON_UNIFIED_PATH = RENDER_CONFIG.get('unified_json_path', JSON_UNIFIED_PATH)
            JSON_SPEEDS_PATH = RENDER_CONFIG.get('speeds_json_path', JSON_SPEEDS_PATH)
            UNITS_MODELS_FOLDER_PATH = RENDER_CONFIG.get('units_path', UNITS_MODELS_FOLDER_PATH)
            BUILDINGS_MODELS_FOLDER_PATH = RENDER_CONFIG.get('buildings_path', BUILDINGS_MODELS_FOLDER_PATH)
            TEXTURES_FOLDER_PATH = RENDER_CONFIG.get('textures_path', TEXTURES_FOLDER_PATH)
            SAVE_FULL_RENDER = RENDER_CONFIG.get('save_full_render', SAVE_FULL_RENDER)
            ANALYSIS = RENDER_CONFIG.get('analysis', ANALYSIS)
            OUTPUT_FILE_PATH = RENDER_CONFIG.get('output_path', OUTPUT_FILE_PATH)

        except Exception as e:
            print(f"⚠ Ошибка при загрузке конфига: {e}")
            import traceback
            traceback.print_exc()

    if output_file:
        OUTPUT_FILE_PATH = output_file


if __name__ == "__main__":
    load_config_from_args()
    import_all()