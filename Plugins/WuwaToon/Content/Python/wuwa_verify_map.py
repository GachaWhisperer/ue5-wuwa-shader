"""Load a map synchronously in a fresh process and report its actors (guards against saving an empty world)."""
import os

import unreal

def prop(obj, name):
    try:
        return obj.get_editor_property(name)
    except Exception as e:  # report instead of aborting the whole verification
        return f'<{name}: {e}>'


def nm(o):
    return o.get_name() if hasattr(o, 'get_name') else o


MAP = os.environ.get('WUWA_MAP', '/Game/WuWa/Validation/Yangyang/L_YangyangShaderValidation')
world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
labels = sorted(a.get_actor_label() for a in actors)
unreal.log(f'[WuwaVerify] {MAP}: {len(actors)} actors: {", ".join(labels)}')
for a in actors:
    if isinstance(a, unreal.WuwaToonCharacterActor):
        body = a.skeletal_mesh_component
        mesh = body.get_skeletal_mesh_asset()
        unreal.log(f'[WuwaVerify] {a.get_actor_label()}: mesh {mesh.get_name() if mesh else None}, '
                   f'surface {[m.get_name() if m else None for m in body.get_materials()]}')
        unreal.log('[WuwaVerify]   surface parents ' + str([nm(m.get_editor_property('parent')) if isinstance(m, unreal.MaterialInstance) else nm(m)
                                                        for m in body.get_materials()]))
        # Kuro per-section extra passes (HETPasses.md): one follower component per pass type; M_Wuwa_Hidden = slot not drawn.
        for pname in ('outline_mesh', 'het_mask_mesh', 'het_occluder_mesh', 'face_shadow_mesh', 'heta_mesh'):
            c = a.get_editor_property(pname)
            unreal.log(f'[WuwaVerify]   {pname}: capture_only={c.get_editor_property("visible_in_scene_capture_only")} '
                       f'leader={nm(c.leader_pose_component) if hasattr(c, "leader_pose_component") and c.leader_pose_component else None} '
                       f'materials {[m.get_name() if m else None for m in c.get_materials()]}')
        data = unreal.WuwaToonExtraMaterialsUserData.find_on_mesh(mesh) if mesh else None
        if data:
            for sec in data.get_editor_property('sections'):
                unreal.log(f'[WuwaVerify]   data slot {sec.get_editor_property("material_slot")} '
                           f'{sec.get_editor_property("kuro_base_slot_name")} (queue {sec.get_editor_property("base_render_queue")}): ' +
                           ', '.join(f'{p.get_editor_property("kuro_slot_name")}/{p.get_editor_property("type")}->'
                                     f'{p.get_editor_property("material").get_name() if p.get_editor_property("material") else ("<empty>" if p.get_editor_property("empty") else None)}'
                                     f' LOD<={p.get_editor_property("max_kuro_lod")}' for p in sec.get_editor_property('passes')))
            unreal.log(f'[WuwaVerify]   data occluders {list(data.get_editor_property("het_occluder_slots"))} '
                       f'({data.get_editor_property("het_occluder_material").get_name() if data.get_editor_property("het_occluder_material") else None}), '
                       f'LOD distances {list(data.get_editor_property("kuro_lod_distances"))}, draw distances '
                       f'{data.get_editor_property("eye_transparent_draw_distance")}/{data.get_editor_property("face_shadow_mesh_draw_distance")}/'
                       f'{data.get_editor_property("outline_draw_distance")}')
        else:
            unreal.log_warning('[WuwaVerify]   mesh has no WuwaToonExtraMaterialsUserData')
    if isinstance(a, unreal.WuwaToonEnvironment):
        unreal.log(f'[WuwaVerify] {a.get_actor_label()}: ' + ', '.join(
            f'{k}={nm(prop(a, k))}' for k in ('het_mask_target', 'face_shadow_mask_target', 'het_max_behind',
                                              'heta_opacity_scale', 'fs_depth_eps', 'toon_depth_target', 'toon_shadow_target')))
        # Lighting preset (JSON-driven dropdown), validation toggles (not recovered), FS shell shadow, capture view alignment.
        unreal.log(f'[WuwaVerify]   ' + ', '.join(
            f'{k}={nm(prop(a, k))}' for k in ('lighting_preset', 'sky_light', 'validation_direct_light_only',
                                              'validation_high_contrast', 'validation_high_contrast_shadow_scale',
                                              'validation_light_rotation_degrees_per_second',
                                              'face_shadow_shell_casts_toon_shadow', 'late_view_alignment',
                                              'capture_view_source')))
        unreal.log(f'[WuwaVerify]   lighting preset options {list(unreal.WuwaToonEnvironment.get_lighting_preset_names())}')
        import wuwa_validation_presets as P
        name = str(prop(a, 'lighting_preset'))
        unreal.log(f'[WuwaVerify]   preset {name} vs JSON: {P.check(name, world) or "consistent"}')
        a.assign_character_mask_ids()
        for c in a.get_editor_property('characters'):
            if isinstance(c, unreal.WuwaToonCharacterActor):
                tc = c.get_editor_property('toon_character')
                unreal.log(f'[WuwaVerify]   {c.get_actor_label()}: mask ID {tc.get_effective_mask_id()} '
                           f'(explicit {tc.get_editor_property("mask_id")}, CPD slot 26)')

heta = unreal.load_asset('/Game/WuWa/Materials/Masters/M_Wuwa_ToonHair_HETA')
if heta:
    unreal.log(f'[WuwaVerify] M_Wuwa_ToonHair_HETA: blend {heta.get_editor_property("blend_mode")}, '
               f'output_translucent_velocity={heta.get_editor_property("output_translucent_velocity")}')
