"""Import one exported Wuthering Waves character (glTF + decoded textures) into the project.

Texture settings come from textures.json written by tools/decode_textures.py, which records the
original pixel format / sRGB flag / compression settings read from the game's UTexture assets.
Mesh normals and tangents are imported as authored (outlines decode a smoothed normal stored
in UV1 against the skinned tangent basis, so recomputing tangents would break them).

Run (paths with spaces can't go through -script, so arguments come from the environment):
  set WUWA_IMPORT_SRC=<src dir>  &  set WUWA_IMPORT_DEST=/Game/WuWa/Characters/<Name>
  UnrealEditor-Cmd.exe WuwaRender.uproject -run=pythonscript -script="import wuwa_import_character"
"""
import json
import os
import sys

import unreal

# Original format -> UE compression: keep block-compressed where the game did, uncompressed where it did.
COMPRESSION = {
    'PF_BC7': unreal.TextureCompressionSettings.TC_BC7,
    'PF_DXT1': unreal.TextureCompressionSettings.TC_DEFAULT,
    'PF_DXT5': unreal.TextureCompressionSettings.TC_DEFAULT,
    'PF_B8G8R8A8': unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP,
    'PF_FloatRGBA': unreal.TextureCompressionSettings.TC_HDR,
    'PF_G8': unreal.TextureCompressionSettings.TC_GRAYSCALE,   # single-channel noise (e.g. T_XingHenSoundNoise)
}


ADDRESS = {'TA_Wrap': unreal.TextureAddress.TA_WRAP, 'TA_Clamp': unreal.TextureAddress.TA_CLAMP,
           'TA_Mirror': unreal.TextureAddress.TA_MIRROR}


def log(msg):
    unreal.log('[WuwaImport] ' + msg)


def import_files(files, dest):
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f
        t.destination_path = dest
        t.automated = True
        t.replace_existing = True
        t.save = False
        tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    return [p for t in tasks for p in t.imported_object_paths]


def configure_texture(path, meta):
    tex = unreal.load_asset(path)
    if tex is None:
        log(f'MISSING texture asset {path}')
        return
    tex.set_editor_property('srgb', bool(meta['SRGB']))
    tex.set_editor_property('compression_settings', COMPRESSION[meta['Format']])
    # Address modes come from the game asset: cooked "from texture asset" samplers inherit them, and Kuro clamps
    # e.g. the eye highlight/EM textures, the face SDF and the ramp (others default to wrap).
    for axis in ('X', 'Y'):
        mode = meta.get('Address' + axis, 'TA_Wrap')
        tex.set_editor_property('address_' + axis.lower(), ADDRESS[mode])
    if meta['Name'].endswith('_Skin'):
        # 512x25 ramp: sampled per band row; mips would bleed rows into each other.
        tex.set_editor_property('mip_gen_settings', unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    log(f"texture {meta['Name']}: sRGB={meta['SRGB']} {meta['Format']} -> {COMPRESSION[meta['Format']]}, "
        f"address {meta.get('AddressX', 'TA_Wrap')}/{meta.get('AddressY', 'TA_Wrap')}")


def main(argv):
    src, dest = argv[0], argv[1]
    meta = json.load(open(os.path.join(src, 'textures.json')))
    tex_dest = dest + '/Textures'
    configure_only = bool(os.environ.get('WUWA_IMPORT_CONFIGURE_ONLY'))   # re-apply settings, no re-import
    if not configure_only:
        files = [os.path.join(src, m['Decoded']) for m in meta if 'Decoded' in m]
        import_files(files, tex_dest)
    for m in meta:
        if 'Decoded' in m:
            configure_texture(f"{tex_dest}/{m['Name']}.{m['Name']}", m)

    if configure_only:
        return
    glbs = [os.path.join(src, f) for f in os.listdir(src) if f.lower().endswith('.glb')]
    imported = import_files(glbs, dest + '/Mesh')
    for p in imported:
        log('imported ' + p)
    for p in imported:
        asset = unreal.load_asset(p)
        if isinstance(asset, unreal.SkeletalMesh):
            box = asset.get_bounds().box_extent
            log(f'skeletal mesh {p}: bounds extent {box.x:.2f},{box.y:.2f},{box.z:.2f}; '
                f'materials {len(asset.materials)}; morph targets {len(asset.morph_targets)}')
    unreal.EditorAssetLibrary.save_directory(dest, only_if_is_dirty=True, recursive=True)


main([os.environ['WUWA_IMPORT_SRC'], os.environ['WUWA_IMPORT_DEST']])
