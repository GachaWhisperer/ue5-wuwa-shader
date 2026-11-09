"""Roster verification in a fresh editor session (assets reloaded from disk, nothing modified or saved).

Per unit / mesh (plan from tools/roster/run_roster_import.py, import results from the batch sessions):
  * the SkeletalMesh loads; render LODs; morph target count == glTF morph count (CUE4Parse export of the cooked mesh);
  * vertex colours present when the glTF has COLOR_0 (render colour buffer non-empty);
  * UV channels in the render data == the cooked mesh's NumTexCoords (UWuwaToonMeshQuery, plugin);
  * every slot's material is the planned MI (surface) or M_Wuwa_Hidden; each MI's parent is the planned master and the
    master asset exists; fallback MIs are parented to M_Wuwa_Unported*;
  * UWuwaToonExtraMaterialsUserData: sections / passes / pass materials equal the plan (Kuro LODSectionExtraMaterialMap).
Legacy units (Yangyang) are checked for mesh / slots / user data presence only (validated by the Yangyang gate).
Writes the result JSON given in WUWA_ROSTER_VERIFY.
"""
import os

import unreal

import wuwa_roster_common as C

EAL = unreal.EditorAssetLibrary
Q = unreal.WuwaToonMeshQuery


def name_of(o):
    return o.get_name() if o else None


def verify_mesh(unit, mp, ue_res, problems, master_dir):
    out = {}
    path = mp.get('legacy_path') or (ue_res.get('meshes') or {}).get(mp['name'], {}).get('path')
    if not path:
        problems.append(f"{mp['name']}: not imported")
        return out
    mesh = unreal.load_asset(path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        problems.append(f"{mp['name']}: {path} is not a SkeletalMesh")
        return out
    morphs = len(mesh.get_editor_property('morph_targets') or [])
    uv = Q.get_skeletal_mesh_num_uv_channels(mesh, 0)
    colors = Q.get_skeletal_mesh_num_color_vertices(mesh, 0)
    lods_fn = next((getattr(Q, n) for n in dir(Q) if n.startswith('get_skeletal_mesh_num_render')), None)
    lods = lods_fn(mesh) if lods_fn else -1
    gs = mp.get('glb_streams') or {}
    exp = mp.get('expected') or {}
    out.update(path=path, morph_targets=morphs, uv_channels=uv, color_vertices=colors, render_lods=lods,
               glb=gs, expected=exp)
    if gs:
        if morphs != gs.get('morph_targets'):
            problems.append(f"{mp['name']}: morph targets {morphs} != glTF {gs.get('morph_targets')}")
        if gs.get('vertex_color') and colors <= 0:
            problems.append(f"{mp['name']}: glTF has COLOR_0 but no vertex colours in render data")

    # UV: the cooked mesh's LODModels[0].NumTexCoords is the reference (CUE4Parse's glTF pads to 8 TEXCOORD sets; UE
    # skeletal render data holds at most 4 = MAX_TEXCOORDS, which is also what every cooked Kuro character mesh has)
    want_uv = exp.get('uv_sets') if exp.get('uv_sets') is not None else min(gs.get('uv_sets') or 0, 4)
    if uv >= 0 and want_uv and uv < want_uv:
        problems.append(f"{mp['name']}: UV channels {uv} < cooked NumTexCoords {want_uv}")
    elif uv > (want_uv or 0):
        out['note_uv'] = f'{uv} UV channels imported, cooked mesh has {want_uv}: the extra channels are glTF padding copies'
    if exp.get('morph_targets') is not None and gs and gs.get('morph_targets') != exp['morph_targets']:
        out['note_morph'] = f"cooked mesh has {exp['morph_targets']} morph targets, glTF export {gs.get('morph_targets')}"
    if exp.get('vertex_colors') and colors <= 0:
        problems.append(f"{mp['name']}: cooked mesh has vertex colours, imported mesh none")
    mats = list(mesh.get_editor_property('materials'))
    out['slots'] = []
    for sm in mats:
        mi = sm.get_editor_property('material_interface')
        parent = mi.get_editor_property('parent') if isinstance(mi, unreal.MaterialInstance) else None
        out['slots'].append({'slot': str(sm.get_editor_property('material_slot_name')), 'material': name_of(mi), 'parent': name_of(parent)})
        if mi is None:
            problems.append(f"{mp['name']}: slot {sm.get_editor_property('material_slot_name')} has no material")
    data = unreal.WuwaToonExtraMaterialsUserData.find_on_mesh(mesh)
    if data is None:
        problems.append(f"{mp['name']}: no WuwaToonExtraMaterialsUserData")
        return out
    secs = list(data.get_editor_property('sections'))
    out['sections'] = len(secs)
    if unit.get('legacy'):
        return out
    planned = {}
    for s in mp.get('sections', []):
        planned.setdefault((s['material'] or '').lower(), s)
    inst = {i['name']: i for i in unit.get('instances', [])}
    # surface slots
    for e in out['slots']:
        s = planned.get(e['slot'].lower())
        if s is None:
            continue
        want = s.get('surface') or 'M_Wuwa_Hidden'
        if e['material'] != want:
            problems.append(f"{mp['name']}: slot {e['slot']} material {e['material']} != planned {want}")
        elif s.get('surface'):
            wm = inst[s['surface']]['master']
            if e['parent'] != wm:
                problems.append(f"{mp['name']}: {e['material']} parent {e['parent']} != planned master {wm}")
            if not EAL.does_asset_exist(f'{master_dir}/{wm}'):
                problems.append(f"{mp['name']}: master {wm} missing")
    # extra passes
    got = 0
    for sec in secs:
        for p in sec.get_editor_property('passes'):
            got += 1
            m = p.get_editor_property('material')
            kslot = int(p.get_editor_property('kuro_material_index'))
            plan_p = next((pp for s in mp.get('sections', []) for pp in s['passes'] if pp['slot'] == kslot), None)
            if plan_p is None:
                problems.append(f"{mp['name']}: unplanned pass {p.get_editor_property('kuro_slot_name')}")
            elif (plan_p.get('instance') or None) != name_of(m):
                problems.append(f"{mp['name']}: pass {plan_p['slot_name']} material {name_of(m)} != planned {plan_p.get('instance')}")
    want_passes = sum(len(s['passes']) for s in mp.get('sections', []))
    out['passes'] = got
    if got < want_passes and len(secs) < len({s['material'] for s in mp.get('sections', [])}):
        problems.append(f"{mp['name']}: {got} passes in user data, plan {want_passes}")
    return out


def main():
    cfg = C.jload(os.environ['WUWA_ROSTER_VERIFY'])
    master_dir = '/Game/WuWa/Materials/Masters/Roster'
    res_dir = os.path.dirname(cfg['result'])
    out = {'units': {}}
    for unit in cfg['units']:
        problems = []
        ue_res = {} if unit.get('legacy') else (C.jload(os.path.join(res_dir, unit['key'] + '.json'))
                                                if os.path.exists(os.path.join(res_dir, unit['key'] + '.json')) else {})
        meshes = {}
        for mp in unit['meshes']:
            try:
                meshes[mp['name']] = verify_mesh(unit, mp, ue_res, problems, master_dir)
            except Exception as e:
                problems.append(f"{mp['name']}: verify exception {e}")
        for i in unit.get('instances', []):
            path = f"{unit['materials_dir']}/{i['name']}"
            mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else None
            if mi is None:
                problems.append(f"MI {i['name']} missing")
                continue
            parent = name_of(mi.get_editor_property('parent'))
            if parent != i['master'] and not (i['mode'] != 'fallback' and parent == 'M_Wuwa_Unported'):
                problems.append(f"MI {i['name']}: parent {parent} != {i['master']}")
        out['units'][unit['key']] = {'ok': not problems, 'problems': problems, 'meshes': meshes}
        C.log(f"verify {unit['key']}: {'OK' if not problems else 'PROBLEMS ' + '; '.join(problems[:5])}")
    out['ok'] = sum(1 for u in out['units'].values() if u['ok'])
    out['failed'] = sum(1 for u in out['units'].values() if not u['ok'])
    C.jsave(cfg['result'], out)
    C.log(f"verify done: {out['ok']} ok, {out['failed']} with problems")


C.run_guarded(main)
