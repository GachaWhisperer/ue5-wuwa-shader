"""Roster gallery map /Game/WuWa/Validation/Roster/L_RosterGallery (build or verify-by-reload).

Build (WUWA_ROSTER_GALLERY_MODE=build): new_blank_map + save_map (new_level refuses existing maps). Every imported unit
(character, alternate skin, signature weapon) gets a grid cell; each of its meshes is an AWuwaToonCharacterActor
(main mesh + character parts at the cell origin, props / weapon models offset along +Y). One AWuwaToonEnvironment with
the OutdoorDaylight preset (ApplyLightingPreset -> recovered OpenWorld_Suibo_Day_12h), the shared toon render targets the
generated materials sample by default (/Game/WuWa/Validation/Yangyang/RT_*), main light, sky light, atmosphere, floor.
Verify (WUWA_ROSTER_GALLERY_MODE=verify): fresh session, load_map (synchronous), check every planned actor exists with its
mesh, the environment preset / characters / targets; writes the JSON result. Nothing is saved in verify mode.
Input: WUWA_ROSTER_GALLERY=<json> {'cells': [{'key', 'label', 'meshes': [{'path', 'label', 'prop'}]}], 'result': path}
"""
import os

import unreal

import wuwa_roster_common as C

MAP = '/Game/WuWa/Validation/Roster/L_RosterGallery'
RT_DIR = '/Game/WuWa/Validation/Yangyang'
MPC = '/Game/WuWa/Materials/MPC_WuwaToon.MPC_WuwaToon'
COLS, DX, DY, PROP_DY = 10, 250.0, 450.0, 110.0
PRESET = 'OutdoorDaylight'


def spawn(cls, loc=(0, 0, 0), rot=(0, 0, 0), label=None):
    a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))
    if label:
        a.set_actor_label(label)
    return a


def cell_origin(i):
    return (i % COLS) * DX, (i // COLS) * DY, 0.0


def build(cfg):
    if not unreal.EditorLoadingAndSavingUtils.new_blank_map(False):
        raise RuntimeError('new_blank_map failed')
    sun = spawn(unreal.DirectionalLight, (0, 0, 800), (-40, -30, 0), 'MainToonLight')
    sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sun.light_component.set_editor_property('intensity', 6.0)
    sky = spawn(unreal.SkyLight, (0, 0, 600), label='SkyLight')
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky.light_component.set_editor_property('real_time_capture', True)
    spawn(unreal.SkyAtmosphere, label='SkyAtmosphere')
    spawn(unreal.ExponentialHeightFog, label='HeightFog')
    rows = (len(cfg['cells']) + COLS - 1) // COLS
    floor = spawn(unreal.StaticMeshActor, (COLS * DX / 2, rows * DY / 2, 0), label='Floor')
    floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Plane.Plane'))
    floor.set_actor_scale3d(unreal.Vector(COLS * DX / 100 + 10, rows * DY / 100 + 10, 1))
    chars, placed, missing = [], 0, []
    for i, cell in enumerate(cfg['cells']):
        ox, oy, oz = cell_origin(i)
        nprop = 0
        for m in cell['meshes']:
            mesh = unreal.load_asset(m['path']) if m.get('path') else None
            if not isinstance(mesh, unreal.SkeletalMesh):
                missing.append(f"{cell['key']}:{m.get('label')}")
                continue
            dy = 0.0
            if m.get('prop'):
                nprop += 1
                dy = PROP_DY * nprop
            a = spawn(unreal.WuwaToonCharacterActor, (ox, oy + dy, oz), (0, 90, 0), m['label'])
            a.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
            a.set_folder_path(f"Roster/{cell['group']}")
            chars.append(a)
            placed += 1
        try:
            lbl = spawn(unreal.TextRenderActor, (ox, oy - 60, 2), (90, 0, 0), f"Label_{cell['label']}")
            lbl.text_render.set_text(cell['label'])
            lbl.text_render.set_editor_property('world_size', 14.0)
            lbl.set_folder_path(f"Roster/{cell['group']}")
        except Exception as e:
            C.warn(f"label {cell['label']}: {e}")
    env = spawn(unreal.WuwaToonEnvironment, (0, 0, 0), label='WuwaToonEnvironment')
    env.set_editor_property('toon_parameters', unreal.load_asset(MPC))
    env.set_editor_property('main_light', sun)
    env.set_editor_property('sky_light', sky)
    env.set_editor_property('characters', chars[:255])   # mask IDs are 1..255 per environment (CPD 26)
    env.set_editor_property('toon_depth_target', unreal.load_asset(f'{RT_DIR}/RT_ToonDepth'))
    env.set_editor_property('toon_shadow_target', unreal.load_asset(f'{RT_DIR}/RT_ToonShadow'))
    env.set_editor_property('het_mask_target', unreal.load_asset(f'{RT_DIR}/RT_WuwaHETMask'))
    env.set_editor_property('face_shadow_mask_target', unreal.load_asset(f'{RT_DIR}/RT_WuwaFaceShadowMask'))
    ok = env.apply_lighting_preset(PRESET)
    cam = spawn(unreal.CameraActor, (COLS * DX / 2, -600, 250), (-10, 90, 0), 'Cam_Gallery')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
        raise RuntimeError(f'save_map({MAP}) failed')
    res = {'map': MAP, 'placed': placed, 'missing': missing, 'environment_characters': min(len(chars), 255),
           'preset_applied': bool(ok), 'cells': len(cfg['cells'])}
    C.jsave(cfg['result'], res)
    C.log(f'gallery built: {placed} actors in {len(cfg["cells"])} cells, missing {len(missing)}, preset {PRESET} {ok}')


def verify(cfg):
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    by_label = {a.get_actor_label(): a for a in actors}
    problems, ok_actors = [], 0
    for cell in cfg['cells']:
        for m in cell['meshes']:
            if not m.get('path'):
                continue
            a = by_label.get(m['label'])
            if not isinstance(a, unreal.WuwaToonCharacterActor):
                problems.append(f"{m['label']}: actor missing")
                continue
            mesh = a.skeletal_mesh_component.get_skeletal_mesh_asset()
            if mesh is None or mesh.get_path_name().split('.')[0] != m['path']:
                problems.append(f"{m['label']}: mesh {mesh.get_path_name() if mesh else None} != {m['path']}")
                continue
            if any(x is None for x in a.skeletal_mesh_component.get_materials()):
                problems.append(f"{m['label']}: empty material slot")
            ok_actors += 1
    envs = [a for a in actors if isinstance(a, unreal.WuwaToonEnvironment)]
    env_info = {}
    if len(envs) != 1:
        problems.append(f'{len(envs)} WuwaToonEnvironment actors')
    else:
        e = envs[0]
        env_info = {'lighting_preset': str(e.get_editor_property('lighting_preset')),
                    'characters': len(e.get_editor_property('characters')),
                    'main_light': bool(e.get_editor_property('main_light')),
                    'toon_depth_target': C.asset_path(e.get_editor_property('toon_depth_target').get_path_name()) if e.get_editor_property('toon_depth_target') else None}
        if env_info['lighting_preset'] != PRESET:
            problems.append(f"environment preset {env_info['lighting_preset']} != {PRESET}")
        if not env_info['main_light']:
            problems.append('environment main light missing')
    n_char = sum(1 for a in actors if isinstance(a, unreal.WuwaToonCharacterActor))
    res = {'map': MAP, 'actors': len(actors), 'character_actors': n_char, 'verified_actors': ok_actors,
           'environment': env_info, 'problems': problems, 'ok': not problems}
    C.jsave(cfg['result'], res)
    C.log(f"gallery verify: {len(actors)} actors, {n_char} toon character actors, {ok_actors} verified, problems {len(problems)}: "
          + '; '.join(problems[:5]))


def main():
    cfg = C.jload(os.environ['WUWA_ROSTER_GALLERY'])
    (verify if os.environ.get('WUWA_ROSTER_GALLERY_MODE') == 'verify' else build)(cfg)


C.run_guarded(main)
