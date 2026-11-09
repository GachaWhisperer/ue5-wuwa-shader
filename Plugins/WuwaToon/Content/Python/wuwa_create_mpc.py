"""Create /Game/WuWa/Materials/MPC_WuwaToon.

Contents:
  * every parameter of Kuro's MPC_GlobalShaderParameters and MPC_Global_Char_Parameters with the shipped
    defaults (data/kuro_mpc_defaults.json), so ported base passes bind by the original names;
  * the toon View-uniform additions and the 16 x 9 toon local light records published each frame by
    AWuwaToonEnvironment (names must match WuwaToonEnvironment.cpp).
Run:  UnrealEditor-Cmd.exe WuwaRender.uproject -run=pythonscript -script="import wuwa_create_mpc"
"""
import json
import os

import unreal

ASSET_DIR, ASSET_NAME = '/Game/WuWa/Materials', 'MPC_WuwaToon'

TOON_SCALARS = {'ToonAOStrength': 1.0, 'ToonLightCount': 0.0,
                # Kuro extra-pass emulation (HETPasses.md §4.3; published by AWuwaToonEnvironment)
                'HETEnable': 1.0, 'HETMaxBehind': 30.0, 'HETAOpacityScale': 1.0, 'FSEnable': 1.0, 'FSDepthEps': 0.5}
TOON_VECTORS = {
    'ToonMainLightDir': [0, 0, 1, 0], 'ToonMainLightColor': [1, 1, 1, 1], 'ToonGIEnable': [0, 0, 0, 0],
    'ToonAmbientParams': [1, 1, 0, 0], 'ToonAmbientA_Near': [0.3, 0.3, 0.32, 0], 'ToonAmbientA_Far': [0.3, 0.3, 0.32, 0],
    'ToonAmbientB_Near': [0.5, 0.5, 0.52, 0], 'ToonAmbientB_Far': [0.5, 0.5, 0.52, 0], 'ToonAORemap': [0, 1, 1, 0],
    'ToonDepthGradient': [10000, 1, 0, 0], 'ToonRimPass': [1, 0, 0, 0], 'ToonRimTint': [1, 1, 1, 1],
    # light-space toon shadow basis (origin.w = ortho width, 0 disables; forward.w = depth bias)
    'ToonShadowOrigin': [0, 0, 0, 0], 'ToonShadowForward': [0, 0, -1, 2], 'ToonShadowRight': [0, 1, 0, 0], 'ToonShadowUp': [1, 0, 0, 0],
}
for light in range(16):
    for row in range(9):
        TOON_VECTORS[f'ToonLight{light}_L{row}'] = [0, 0, 0, 0]
# Kuro's separate MPC_Cloth (VS CB4 of the M_Char_Com_Special fabric WPO; defaults from the cooked
# Aki/Render/Data/MPC_Cloth asset). Hosted here as vectors APPENDED after every other parameter, so no existing packed
# index moves (the light loop hard-codes MaterialCollection0 indices); DirectAnimAmount lives in .x.
CLOTH_VECTORS = {'Cloth_DirectAnimAmount': [0, 0, 0, 0], 'Cloth_Direction': [1, 1, 1, 0], 'Cloth_DirectionAnim': [0, 0, 0, 0]}


def main():
    kuro = json.load(open(os.path.join(os.path.dirname(__file__), 'data', 'kuro_mpc_defaults.json')))
    scalars = {**kuro['scalars'], **TOON_SCALARS}
    vectors = {**kuro['vectors'], **TOON_VECTORS, **CLOTH_VECTORS}
    clash = set(scalars) & set(vectors)
    assert not clash, clash

    path = f'{ASSET_DIR}/{ASSET_NAME}'
    mpc = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else \
        unreal.AssetToolsHelpers.get_asset_tools().create_asset(ASSET_NAME, ASSET_DIR, unreal.MaterialParameterCollection,
                                                                 unreal.MaterialParameterCollectionFactoryNew())
    # Reuse existing parameter entries (and so their Ids) so materials compiled against the MPC keep binding by Id.
    old_s = {str(p.get_editor_property('parameter_name')): p for p in mpc.get_editor_property('scalar_parameters')}
    old_v = {str(p.get_editor_property('parameter_name')): p for p in mpc.get_editor_property('vector_parameters')}

    def scalar(name, value):
        p = old_s.get(name) or unreal.CollectionScalarParameter()
        p.set_editor_property('parameter_name', name)
        p.set_editor_property('default_value', float(value))
        return p

    def vector(name, value):
        p = old_v.get(name) or unreal.CollectionVectorParameter()
        p.set_editor_property('parameter_name', name)
        p.set_editor_property('default_value', unreal.LinearColor(*map(float, value)))
        return p

    mpc.set_editor_property('scalar_parameters', [scalar(n, v) for n, v in scalars.items()])
    mpc.set_editor_property('vector_parameters', [vector(n, v) for n, v in vectors.items()])
    unreal.EditorAssetLibrary.save_loaded_asset(mpc)
    unreal.log(f'[WuwaMPC] {path}: {len(scalars)} scalars, {len(vectors)} vectors')


main()
