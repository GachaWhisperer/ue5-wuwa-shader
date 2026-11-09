"""Build /Game/WuWa/Validation/Yangyang/L_YangyangShaderValidation (master prompt Â§8 test environment).

Contents: movable directional light (main toon light), sky light + atmosphere, Yangyang skeletal mesh with
UWuwaToonCharacterComponent, AWuwaToonEnvironment with toon depth / toon shadow render targets, a neutral
backdrop, and named cameras for the camera-angle/distance tests. Lighting presets are applied separately by
wuwa_validation_presets.py so the same map serves every scenario.
"""
import unreal

MAP = '/Game/WuWa/Validation/Yangyang/L_YangyangShaderValidation'
RT_DIR = '/Game/WuWa/Validation/Yangyang'
MESH = '/Game/WuWa/Characters/Yangyang/Mesh/R2T1YangyangMd10011/SkeletalMeshes/R2T1YangyangMd10011.R2T1YangyangMd10011'
MPC = '/Game/WuWa/Materials/MPC_WuwaToon.MPC_WuwaToon'

CAMERAS = {  # name: (location, rotation pitch/yaw) relative to the character at the origin (cm)
    'Cam_FullBody_Front': ((300, 0, 90), (0, 180)),
    'Cam_FullBody_Side': ((0, 300, 90), (0, -90)),
    'Cam_FullBody_Back': ((-300, 0, 90), (0, 0)),
    'Cam_Face_Front': ((70, 0, 150), (0, 180)),
    'Cam_Face_ThreeQuarter': ((50, 50, 150), (0, -135)),
    'Cam_Far': ((1200, 0, 120), (0, 180)),
}


def render_target(name, size, fmt, clear=unreal.LinearColor(65504, 65504, 65504, 1)):  # default "no character" = far
    path = f'{RT_DIR}/{name}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    rt = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, RT_DIR, unreal.TextureRenderTarget2D,
                                                                 unreal.TextureRenderTargetFactoryNew())
    rt.set_editor_property('size_x', size[0]); rt.set_editor_property('size_y', size[1])
    rt.set_editor_property('render_target_format', fmt)
    rt.set_editor_property('clear_color', clear)
    unreal.EditorAssetLibrary.save_loaded_asset(rt)
    return rt


def spawn(cls, loc=(0, 0, 0), rot=(0, 0, 0), label=None):
    a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))
    if label:
        a.set_actor_label(label)
    return a


def main():
    # new_level() refuses an existing map and silently leaves a transient world current. Build in a fresh blank
    # world instead and save_map() it over the target path (overwrites the existing package).
    if not unreal.EditorLoadingAndSavingUtils.new_blank_map(False):
        raise RuntimeError('new_blank_map failed')

    sun = spawn(unreal.DirectionalLight, (0, 0, 500), (-40, -30, 0), 'MainToonLight')
    sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sun.light_component.set_editor_property('intensity', 6.0)
    sky = spawn(unreal.SkyLight, (0, 0, 300), label='SkyLight')
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky.light_component.set_editor_property('real_time_capture', True)
    spawn(unreal.SkyAtmosphere, label='SkyAtmosphere')
    spawn(unreal.ExponentialHeightFog, label='HeightFog')

    floor = spawn(unreal.StaticMeshActor, (0, 0, 0), label='Floor')
    floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Plane.Plane'))
    floor.set_actor_scale3d(unreal.Vector(20, 20, 1))

    char = spawn(unreal.WuwaToonCharacterActor, (0, 0, 0), (0, 0, 0), 'Yangyang')
    char.skeletal_mesh_component.set_skeletal_mesh_asset(unreal.load_asset(MESH))

    env = spawn(unreal.WuwaToonEnvironment, (0, 0, 0), label='WuwaToonEnvironment')
    env.set_editor_property('toon_parameters', unreal.load_asset(MPC))
    env.set_editor_property('main_light', sun)
    env.set_editor_property('characters', [char])
    env.set_editor_property('toon_depth_target', render_target('RT_ToonDepth', (1920, 1080), unreal.TextureRenderTargetFormat.RTF_R32F))
    env.set_editor_property('toon_shadow_target', render_target('RT_ToonShadow', (1024, 1024), unreal.TextureRenderTargetFormat.RTF_R32F))
    # Kuro HET / FS extra-pass masks (HETPasses.md §4.2). Same assets the generated materials sample by default
    # (wuwa_generate_materials.py creates them); RGB = mask, A = scene depth (cm).
    for prop, name in (('het_mask_target', 'RT_WuwaHETMask'), ('face_shadow_mask_target', 'RT_WuwaFaceShadowMask')):
        env.set_editor_property(prop, render_target(name, (1920, 1080), unreal.TextureRenderTargetFormat.RTF_RGBA32F,
                                                    unreal.LinearColor(0, 0, 0, 65504)))

    for name, (loc, (pitch, yaw)) in CAMERAS.items():
        spawn(unreal.CameraActor, loc, (pitch, yaw, 0), name)

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
        raise RuntimeError(f'save_map({MAP}) failed')
    count = len(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors())
    unreal.log(f'[WuwaMap] built {MAP} with {count} actors')


main()
