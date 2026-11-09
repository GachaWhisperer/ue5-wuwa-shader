"""Roster setup session: shared textures, roster masters, fallback masters (tools/roster/run_roster_import.py ue-setup).

  /Game/WuWa/Shared/Textures                 textures referenced by more than one entry or living outside the entry's own
                                             model folders (CommonTexture SDFs / eyes / matcaps, Render/Common defaults)
  /Game/WuWa/Materials/Masters/Roster/M_WuwaRoster_<spec>[_mode][_HETCut][_FSRecv]
                                             generated from Specs/<spec>.json by wuwa_generate_materials.build_master
                                             (the same builder as the validated Yangyang masters; graphs not edited here)
  /Game/WuWa/Materials/Masters/Roster/M_Wuwa_Unported[_Masked|_Translucent]
                                             FLAGGED FALLBACK for MIs whose family / permutation is not in the registry:
                                             unlit MainTex x BaseColor, magenta debug tint (DebugTint 1 = on). Not a port.
Run: set WUWA_ROSTER_SETUP=<json>; UnrealEditor.exe WuwaRender.uproject -ExecutePythonScript="import wuwa_roster_setup"
     -RenderOffscreen -unattended -nosplash -nop4   (offscreen editor: commandlets don't compile shaders)
"""
import json
import os

import unreal

os.environ['WUWA_GENERATE_AS_LIBRARY'] = '1'
import wuwa_generate_materials as G   # noqa: E402
import wuwa_material_lib as W         # noqa: E402
import wuwa_roster_common as C        # noqa: E402

FALLBACK_CODE = r'''
float3 c = lerp(Base.rgb, Tex.rgb * Base.rgb, UseTex);
return lerp(c, c * 0.5 + TintColor.rgb * 0.5, saturate(DebugTint));
'''


def fallback_master(path, blend):
    mat = W.new_material(path, blend=blend)
    tex = W.node(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 0, parameter_name='MainTex',
                 texture=unreal.load_asset('/Engine/EngineResources/WhiteSquareTexture'))
    tex.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    base = W.node(mat, unreal.MaterialExpressionVectorParameter, -900, 250, parameter_name='BaseColor',
                  default_value=unreal.LinearColor(1, 1, 1, 1))
    use = W.node(mat, unreal.MaterialExpressionScalarParameter, -900, 400, parameter_name='UseMainTex', default_value=1.0)
    tint = W.node(mat, unreal.MaterialExpressionScalarParameter, -900, 500, parameter_name='DebugTint', default_value=1.0)
    tcol = W.node(mat, unreal.MaterialExpressionVectorParameter, -900, 600, parameter_name='DebugTintColor',
                  default_value=unreal.LinearColor(1, 0, 1, 1))
    c = W.custom(mat, -400, 0, FALLBACK_CODE, [('Tex', tex, 'RGB'), ('Base', base, 'RGB'), ('UseTex', use, ''),
                                               ('DebugTint', tint, ''), ('TintColor', tcol, 'RGB')],
                 unreal.CustomMaterialOutputType.CMOT_FLOAT3, [], (), 'WuwaUnportedFallback')
    W.MEL.connect_material_property(c, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if blend != unreal.BlendMode.BLEND_OPAQUE:
        a = W.node(mat, unreal.MaterialExpressionMultiply, -400, 300)
        W.MEL.connect_material_expressions(tex, 'A', a, 'A')
        W.MEL.connect_material_expressions(base, 'A', a, 'B')
        prop = unreal.MaterialProperty.MP_OPACITY_MASK if blend == unreal.BlendMode.BLEND_MASKED else unreal.MaterialProperty.MP_OPACITY
        W.MEL.connect_material_property(a, '', prop)
    W.compile_and_report(mat)
    return mat


def main():
    cfg = C.jload(os.environ['WUWA_ROSTER_SETUP'])
    res = {'masters_ok': [], 'masters_failed': {}, 'textures_imported': 0, 'texture_errors': []}
    n, errs = C.import_textures(cfg['shared_textures'], skip_existing=not os.environ.get('WUWA_ROSTER_REIMPORT'))
    res['textures_imported'], res['texture_errors'] = n, errs
    C.log(f'shared textures: imported {n}, errors {len(errs)}')
    unreal.EditorAssetLibrary.save_directory('/Game/WuWa/Shared', only_if_is_dirty=True, recursive=True)

    mdir = cfg['master_dir']
    for name, blend in (('M_Wuwa_Unported', unreal.BlendMode.BLEND_OPAQUE), ('M_Wuwa_Unported_Masked', unreal.BlendMode.BLEND_MASKED),
                        ('M_Wuwa_Unported_Translucent', unreal.BlendMode.BLEND_TRANSLUCENT)):
        try:
            fallback_master(f'{mdir}/{name}', blend)
            res['masters_ok'].append(name)
        except Exception as e:
            res['masters_failed'][name] = str(e)
    # slot-not-drawn material (rebuilt in place: meshes and followers keep referencing the same asset)
    try:
        hidden = G.invisible_material()
        res['masters_ok'].append('M_Wuwa_Hidden')
        res['hidden_blend_mode'] = str(hidden.get_editor_property('blend_mode'))
    except Exception as e:
        res['masters_failed']['M_Wuwa_Hidden'] = str(e)
    layout = W.mpc_layout()
    spec_dir = G.SPEC_DIR
    only = set(filter(None, os.environ.get('WUWA_ROSTER_MASTERS', '').split(',')))
    rebuild = bool(os.environ.get('WUWA_ROSTER_REBUILD_MASTERS'))
    # WUWA_ROSTER_REBUILD_OLDER_THAN=<epoch s>: rebuild only masters saved before the cutoff (resume a rebuild pass)
    older_than = float(os.environ.get('WUWA_ROSTER_REBUILD_OLDER_THAN') or 0)
    for name, m in sorted(cfg['masters'].items()):
        if only and name not in only:
            continue
        if older_than and unreal.EditorAssetLibrary.does_asset_exist(f'{mdir}/{name}'):
            f = os.path.join(unreal.Paths.project_content_dir(), *f'{mdir}/{name}'.split('/')[2:]) + '.uasset'
            if os.path.exists(f) and os.path.getmtime(f) >= older_than:
                res['masters_ok'].append(name)   # already rebuilt after the cutoff (resumed setup session)
                continue
        elif not rebuild and unreal.EditorAssetLibrary.does_asset_exist(f'{mdir}/{name}'):
            res['masters_ok'].append(name)   # deterministic from the spec; WUWA_ROSTER_REBUILD_MASTERS=1 rebuilds
            continue
        try:
            spec = json.load(open(os.path.join(spec_dir, m['spec'])))
            G.build_master(spec, {}, layout, m['mode'], fs_receive=m['fs_recv'], het_cut=m['het_cut'], path=f'{mdir}/{name}')
            res['masters_ok'].append(name)
            C.log(f"master {name}: {m['spec']} mode {m['mode']} het_cut {m['het_cut']} fs_recv {m['fs_recv']}")
        except Exception as e:
            res['masters_failed'][name] = str(e)
            C.warn(f'FAILED master {name}: {e}')
            # a half-built graph left in memory has crashed the next compile: empty it and save
            try:
                half = unreal.load_asset(f'{mdir}/{name}')
                if half:
                    W.MEL.delete_all_material_expressions(half)
                    W.MEL.recompile_material(half)
                    unreal.EditorAssetLibrary.save_loaded_asset(half, only_if_is_dirty=False)
            except Exception as e2:
                C.warn(f'could not empty {name}: {e2}')
        C.jsave(cfg['result'], res)   # partial results survive a crash later in the session
    C.jsave(cfg['result'], res)
    C.log(f"setup done: masters {len(res['masters_ok'])} ok, {len(res['masters_failed'])} failed")


C.run_guarded(main)
