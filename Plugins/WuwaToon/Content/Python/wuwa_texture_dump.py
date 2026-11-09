"""Dump texture asset settings and export their source images (WUWA_TEXDUMP=<cfg json>: {'textures': [paths], 'out': dir,
'result': json}). Diagnostic for textures that render differently from their decoded PNG."""
import os

import unreal

import wuwa_roster_common as C


def main():
    cfg = C.jload(os.environ['WUWA_TEXDUMP'])
    os.makedirs(cfg['out'], exist_ok=True)
    res = {}
    props = ('compression_settings', 'srgb', 'lod_group', 'mip_gen_settings', 'filter', 'address_x', 'address_y',
             'compression_no_alpha', 'never_stream', 'virtual_texture_streaming', 'lod_bias', 'max_texture_size',
             'adjust_brightness', 'adjust_saturation', 'adjust_vibrance', 'adjust_rgb_curve', 'adjust_min_alpha',
             'adjust_max_alpha', 'flip_green_channel', 'chroma_key_texture', 'downscale', 'compress_final')
    for p in cfg['textures']:
        t = unreal.load_asset(p)
        r = {'class': t.get_class().get_name() if t else None}
        if t:
            for k in props:
                try:
                    r[k] = str(t.get_editor_property(k))
                except Exception as e:
                    r[k] = f'n/a ({type(e).__name__})'
            r['size'] = [t.blueprint_get_size_x(), t.blueprint_get_size_y()]
            task = unreal.AssetExportTask()
            task.object = t
            task.filename = os.path.join(cfg['out'], p.rsplit('/', 1)[1] + '.png')
            task.automated = True
            task.replace_identical = True
            task.prompt = False
            r['exported'] = bool(unreal.Exporter.run_asset_export_task(task))
        res[p] = r
    C.jsave(cfg['result'], res)


C.run_guarded(main)
