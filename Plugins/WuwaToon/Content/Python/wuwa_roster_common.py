"""Shared helpers of the roster import scripts (wuwa_roster_setup / _import / _verify / _gallery).

Texture settings follow wuwa_import_character.py (original sRGB / compression / address modes recorded by RosterExport),
with two roster-specific choices so that one master can serve every MI (texture sampler types must agree with the
master's Color / LinearColor parameter): single-channel and two-channel formats (G8, BC4, BC5) import as colour textures
instead of Grayscale / Normalmap compression.
"""
import json
import os
import traceback

import unreal

COMPRESSION = {
    'PF_BC7': unreal.TextureCompressionSettings.TC_BC7,
    'PF_DXT1': unreal.TextureCompressionSettings.TC_DEFAULT,
    'PF_DXT5': unreal.TextureCompressionSettings.TC_DEFAULT,
    'PF_B8G8R8A8': unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP,
    'PF_R8G8B8A8': unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP,
    'PF_FloatRGBA': unreal.TextureCompressionSettings.TC_HDR,
    'PF_BC6H': unreal.TextureCompressionSettings.TC_HDR,
    'PF_G8': unreal.TextureCompressionSettings.TC_DEFAULT,
    'PF_BC4': unreal.TextureCompressionSettings.TC_BC7,
    'PF_BC5': unreal.TextureCompressionSettings.TC_BC7,
}
ADDRESS = {'TA_Wrap': unreal.TextureAddress.TA_WRAP, 'TA_Clamp': unreal.TextureAddress.TA_CLAMP,
           'TA_Mirror': unreal.TextureAddress.TA_MIRROR}
EAL = unreal.EditorAssetLibrary


def log(msg):
    unreal.log('[WuwaRoster] ' + msg)


def warn(msg):
    unreal.log_warning('[WuwaRoster] ' + msg)


def jload(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def jsave(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(path + '.tmp', path)


def asset_path(object_path):
    """'/Game/A/B.B' -> '/Game/A/B'"""
    return object_path.split('.')[0] if object_path else object_path


def import_files(files, dest, replace=True):
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f
        t.destination_path = dest
        t.automated = True
        t.replace_existing = replace
        t.save = False
        tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    return [[str(p) for p in t.imported_object_paths] for t in tasks]


def is_ramp(meta):
    n = meta['Name']
    return n.endswith('_Skin') or 'Ramp' in n or (meta.get('SizeY', 999) <= 32 and meta.get('SizeX', 0) >= 128)


def configure_texture(tex, meta):
    tex.set_editor_property('srgb', bool(meta['SRGB']))
    comp = COMPRESSION.get(meta['Format'])
    if comp is not None:
        tex.set_editor_property('compression_settings', comp)
    if isinstance(tex, unreal.Texture2D):
        for axis in ('X', 'Y'):
            tex.set_editor_property('address_' + axis.lower(), ADDRESS.get(meta.get('Address' + axis, 'TA_Wrap'), unreal.TextureAddress.TA_WRAP))
    if is_ramp(meta):
        tex.set_editor_property('mip_gen_settings', unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    EAL.save_loaded_asset(tex, only_if_is_dirty=False)


def import_textures(items, skip_existing=True):
    """items: [{'file', 'folder', 'name', 'asset_name', 'meta', 'package'}]. Imports by folder, renames clashing names,
    applies the original settings. Returns (imported count, errors list)."""
    errors, done = [], 0
    by_folder = {}
    for it in items:
        if not it.get('file') or not os.path.exists(it['file']):
            errors.append({'package': it.get('package'), 'error': it.get('error') or 'decoded file missing'})
            continue
        target = f"{it['folder']}/{it['asset_name']}"
        if skip_existing and EAL.does_asset_exist(target):
            continue
        by_folder.setdefault(it['folder'], []).append(it)
    for folder, its in by_folder.items():
        # a renamed (clashing) texture is imported alone so its default name cannot collide in the folder
        plain = [i for i in its if i['asset_name'] == i['name']]
        renamed = [i for i in its if i['asset_name'] != i['name']]
        batches = ([plain] if plain else []) + [[i] for i in renamed]
        for batch in batches:
            try:
                res = import_files([i['file'] for i in batch], folder)
            except Exception as e:
                for i in batch:
                    errors.append({'package': i['package'], 'error': f'import: {e}'})
                continue
            for i, paths in zip(batch, res):
                try:
                    src = f"{folder}/{i['name']}"
                    if not EAL.does_asset_exist(src) and paths:
                        src = asset_path(paths[0])
                    if i['asset_name'] != i['name']:
                        dst = f"{folder}/{i['asset_name']}"
                        if EAL.does_asset_exist(dst):
                            EAL.delete_asset(dst)
                        EAL.rename_asset(src, dst)
                        src = dst
                    tex = unreal.load_asset(src)
                    if tex is None:
                        raise RuntimeError(f'no asset at {src} after import')
                    configure_texture(tex, i['meta'])
                    done += 1
                except Exception as e:
                    errors.append({'package': i['package'], 'error': str(e)})
    return done, errors


def run_guarded(fn):
    try:
        fn()
    except Exception:
        unreal.log_error('[WuwaRoster] ' + traceback.format_exc())
    if os.environ.get('WUWA_QUIT_AFTER'):
        unreal.SystemLibrary.quit_editor()
