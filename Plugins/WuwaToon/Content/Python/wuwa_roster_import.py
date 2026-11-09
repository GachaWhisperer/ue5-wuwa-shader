"""Roster batch import (tools/roster/run_roster_import.py `ue` / `ue-materials`): one editor session, N units.

Per unit (plan computed outside the editor from Specs/Roster/<unit>_MIs.json + _ExtraMaterials.json):
  1. entry-local textures -> <unit folder>/Textures (original sRGB / compression / address modes)
  2. fixed glTF meshes    -> <model folder>/Mesh/<mesh>/SkeletalMeshes/<mesh> (authored normals/tangents, morphs, all UV
                             sets, vertex colour); the importer's placeholder glTF materials are deleted after assignment
  3. material instances   -> <model folder>/Materials/<MI> parented to the roster masters (Masters/Roster) or to the
                             flagged fallback M_Wuwa_Unported* (status material_unported:<root>)
  4. mesh slots (surface MIs) + UWuwaToonExtraMaterialsUserData (Kuro per-section extra passes: outline / HET / HETA / FS,
     HET occluder slots, Kuro LOD distances, draw distances), as wuwa_generate_materials.write_mesh_data does for Yangyang.
     Unported extra passes are not drawn (pass material None); M_Empty slots are not drawn.
Writes <result_dir>/<unit>.json. `materials_only` re-runs 3-4 on the existing meshes (after registry updates).
Run: set WUWA_ROSTER_BATCH=<json>; UnrealEditor.exe WuwaRender.uproject -ExecutePythonScript="import wuwa_roster_import" ...
"""
import os
import time
import traceback

import unreal

os.environ['WUWA_GENERATE_AS_LIBRARY'] = '1'
import wuwa_generate_materials as G   # noqa: E402
import wuwa_roster_common as C        # noqa: E402

EAL = unreal.EditorAssetLibrary
SLOT_TYPE_NAMES = G.SLOT_TYPE_NAMES
HIDDEN = '/Game/WuWa/Materials/Masters/M_Wuwa_Hidden'
OCCLUDER = '/Game/WuWa/Materials/Masters/M_Wuwa_CaptureOccluder'


def find_mesh(paths):
    for p in paths:
        a = unreal.load_asset(C.asset_path(p))
        if isinstance(a, unreal.SkeletalMesh):
            return a
    return None


def import_mesh(mp):
    dest = mp['ue_base'] + '/Mesh'
    paths = C.import_files([mp['glb']], dest)[0]
    mesh = find_mesh(paths)
    if mesh is None:   # importer may report the folder only; fall back to the conventional Interchange layout
        mesh = unreal.load_asset(f"{dest}/{mp['name']}/SkeletalMeshes/{mp['name']}")
    junk = []
    for p in paths:
        a = unreal.load_asset(C.asset_path(p))
        if isinstance(a, unreal.MaterialInterface):
            junk.append(C.asset_path(p))
    return mesh, junk


def build_instances(unit, master_dir, result):
    folder = unit['materials_dir']
    out = {}
    for inst in unit['instances']:
        master_path = f"{master_dir}/{inst['master']}"
        master = unreal.load_asset(master_path) if EAL.does_asset_exist(master_path) else None
        info = {'parameters': inst['parameters'], 'textures': inst['textures']}
        if master is None:
            # master missing (failed to build): flagged fallback instead of a broken MI
            result['instance_problems'].append(f"{inst['name']}: master {inst['master']} missing -> M_Wuwa_Unported")
            master = unreal.load_asset(f'{master_dir}/M_Wuwa_Unported')
            info = {'parameters': {}, 'textures': {k: v for k, v in inst['textures'].items() if k == 'MainTex'}}
        try:
            out[inst['name']] = G.build_instance(inst['name'], info, master, folder, inst.get('extra_scalars') or None)
        except Exception as e:
            result['instance_problems'].append(f"{inst['name']}: {e}")
    return out


def assign(mesh, mp, instances, hidden, occluder, result):
    mats = list(mesh.get_editor_property('materials'))
    ue_names = [str(sm.get_editor_property('material_slot_name')) for sm in mats]
    # glTF material names are the MI object names; MI keys are package names, which differ in case for some assets
    # (e.g. package MI_R2T1BaiLian... / object MI_R2T1Bailian...): match case-insensitively
    ue_lower = [n.lower() for n in ue_names]
    by_slot = {}
    for s in mp['sections']:
        mi = s['material'] or ''
        ue = ue_lower.index(mi.lower()) if mi.lower() in ue_lower else -1
        if ue < 0:
            base = mi.rsplit('_', 1)[0] if mi[-2:-1] == '_' and mi[-1:].isdigit() else mi   # unit-suffixed duplicate names
            ue = ue_lower.index(base.lower()) if base.lower() in ue_lower else -1
        if ue < 0:
            result['slot_problems'].append(f"{mp['name']}: section {s['section']} ({mi}) has no UE slot")
            continue
        by_slot[ue] = s
    sections, occ, slot_report = [], [], []
    for i, sm in enumerate(mats):
        s = by_slot.get(i)
        surf = instances.get(s['surface']) if s and s.get('surface') else None
        sm.set_editor_property('material_interface', surf or hidden)
        mats[i] = sm
        slot_report.append({'slot': i, 'name': ue_names[i], 'surface': s.get('surface') if s else None,
                            'status': s.get('status') if s else 'no_kuro_section'})
        if not s:
            continue
        if s.get('het_occluder') and surf is not None:
            occ.append(i)
        sec = unreal.WuwaToonSectionPasses()
        sec.set_editor_property('material_slot', i)
        sec.set_editor_property('kuro_base_slot_name', s['base_slot_name'] or '')
        sec.set_editor_property('base_render_queue', int(s['base_render_queue'] or 0))
        passes = []
        for p in s['passes']:
            ps = unreal.WuwaToonExtraPass()
            ps.set_editor_property('type', getattr(unreal.WuwaToonSlotType, SLOT_TYPE_NAMES.get(p['type'], 'UNKNOWN')))
            ps.set_editor_property('kuro_slot_name', p['slot_name'] or '')
            ps.set_editor_property('kuro_material_index', int(p['slot']))
            ps.set_editor_property('kuro_material_name', p['material'] or '')
            ps.set_editor_property('empty', bool(p['empty']))
            ps.set_editor_property('max_kuro_lod', int(p['max_lod']))
            ps.set_editor_property('render_queue', int(p['render_queue'] or 0))
            ps.set_editor_property('material', instances.get(p['instance']) if p.get('instance') else None)
            passes.append(ps)
        sec.set_editor_property('passes', passes)
        sections.append(sec)
    mesh.set_editor_property('materials', mats)
    data = unreal.WuwaToonExtraMaterialsUserData.find_or_add_to_mesh(mesh)
    data.set_editor_property('sections', sections)
    data.set_editor_property('het_occluder_slots', occ)
    data.set_editor_property('het_occluder_material', occluder)
    data.set_editor_property('kuro_lod_distances', [float(x) for x in mp.get('lod_distances', [])])
    data.set_editor_property('use_kuro_lod_distance', bool(mp.get('use_kuro_lod_distance', True)))
    data.set_editor_property('head_bone_name', mp.get('head_bone') or 'Bip001Head')
    dd = mp.get('draw_distances') or {}
    data.set_editor_property('eye_transparent_draw_distance', float(dd.get('EyeTransparent', 800.0)))
    data.set_editor_property('face_shadow_mesh_draw_distance', float(dd.get('FaceShadowMesh', 800.0)))
    data.set_editor_property('outline_draw_distance', float(dd.get('Outline', 2000.0)))
    EAL.save_loaded_asset(mesh, only_if_is_dirty=False)
    return slot_report, len(sections), occ


def do_unit(unit, cfg, hidden, occluder):
    r = {'key': unit['key'], 'ok': False, 'meshes': {}, 'texture_errors': [], 'instance_problems': [], 'slot_problems': [],
         'started': time.time()}
    prev = {}
    prev_file = os.path.join(cfg['result_dir'], unit['key'] + '.json')
    if os.path.exists(prev_file):
        prev = C.jload(prev_file)
    if not cfg.get('materials_only'):
        n, errs = C.import_textures(unit['textures'], skip_existing=False)
        r['textures_imported'], r['texture_errors'] = n, errs
    meshes, junk = {}, []
    for mp in unit['meshes']:
        try:
            if cfg.get('materials_only'):
                p = (prev.get('meshes') or {}).get(mp['name'], {}).get('path') or f"{mp['ue_base']}/Mesh/{mp['name']}/SkeletalMeshes/{mp['name']}"
                mesh = unreal.load_asset(p)
            else:
                if not mp.get('glb') or not os.path.exists(mp['glb']):
                    r['meshes'][mp['name']] = {'error': 'fixed glb missing (export/fix failed)'}
                    continue
                mesh, j = import_mesh(mp)
                junk += j
            if mesh is None:
                r['meshes'][mp['name']] = {'error': 'no SkeletalMesh after import'}
                continue
            meshes[mp['name']] = mesh
            r['meshes'][mp['name']] = {'path': mesh.get_path_name().split('.')[0],
                                       'morph_targets': len(mesh.get_editor_property('morph_targets') or []),
                                       'has_vertex_colors': bool(mesh.has_vertex_colors()),
                                       'materials': len(mesh.get_editor_property('materials'))}
        except Exception as e:
            r['meshes'][mp['name']] = {'error': f'import: {e}'}
    instances = build_instances(unit, cfg['master_dir'], r)
    for mp in unit['meshes']:
        mesh = meshes.get(mp['name'])
        if mesh is None:
            continue
        try:
            slots, nsec, occ = assign(mesh, mp, instances, hidden, occluder, r)
            r['meshes'][mp['name']].update(slots=slots, sections=nsec, het_occluder_slots=list(occ))
        except Exception as e:
            r['meshes'][mp['name']]['error'] = f'assign: {e}'
    for p in junk:   # importer placeholder materials (now unreferenced)
        try:
            if EAL.does_asset_exist(p):
                EAL.delete_asset(p)
        except Exception:
            pass
    for base in {mp['ue_base'] for mp in unit['meshes']}:
        EAL.save_directory(base, only_if_is_dirty=True, recursive=True)
    errors = [f"{k}: {v['error']}" for k, v in r['meshes'].items() if v.get('error')]
    r['instances'] = sorted(instances)
    r['ok'] = not errors and bool(meshes)
    r['error'] = '; '.join(errors) if errors else (None if meshes else 'no mesh imported')
    r['seconds'] = time.time() - r.pop('started')
    C.jsave(prev_file, r)
    C.log(f"unit {unit['key']} {unit['name']}: ok={r['ok']} meshes {len(meshes)} instances {len(instances)} "
          f"texture errors {len(r['texture_errors'])} problems {len(r['instance_problems']) + len(r['slot_problems'])} "
          f"({r['seconds']:.0f}s)")


def main():
    cfg = C.jload(os.environ['WUWA_ROSTER_BATCH'])
    hidden = unreal.load_asset(HIDDEN) if EAL.does_asset_exist(HIDDEN) else G.invisible_material()
    occluder = unreal.load_asset(OCCLUDER) if EAL.does_asset_exist(OCCLUDER) else G.occluder_material()
    for unit in cfg['units']:
        # free the previous unit's import transients (one session imports several units; Interchange glTF imports of
        # morph-heavy meshes otherwise accumulate tens of GB of commit and the session dies out of memory)
        unreal.SystemLibrary.collect_garbage()
        try:
            do_unit(unit, cfg, hidden, occluder)
        except Exception:
            C.jsave(os.path.join(cfg['result_dir'], unit['key'] + '.json'),
                    {'key': unit['key'], 'ok': False, 'error': 'exception: ' + traceback.format_exc()[-1500:]})
            unreal.log_error('[WuwaRoster] ' + traceback.format_exc())


C.run_guarded(main)
