"""Compile gate for the generated WuwaToon masters, run in a fresh offscreen editor (commandlets don't compile shaders).

wuwa_generate_materials.py rebuilds existing masters in place; while their graphs are being rewired the editor compiles
the half-built graphs and logs transient "Failed to compile Material ... missing input" warnings. This script touches no
graph: it loads every master under /Game/WuWa/Materials/Masters, recompiles it synchronously for the running shader
platform (D3D12 / PCD3D_SM6 by default), and reports per-material stats. Gate: the log of this run must contain no
"Failed to compile Material" line.

Run:  set WUWA_QUIT_AFTER=1
      UnrealEditor.exe WuwaRender.uproject -ExecutePythonScript="import wuwa_compile_check" -RenderOffscreen -unattended -nosplash -nop4 -log
"""
import os

import unreal

MASTER_DIR = '/Game/WuWa/Materials/Masters'
MEL = unreal.MaterialEditingLibrary

# WUWA_COMPILE_RECURSIVE=1 also checks the roster masters (Masters/Roster: M_WuwaRoster_* and the M_Wuwa_Unported* fallback).
paths = sorted(p.split('.')[0] for p in unreal.EditorAssetLibrary.list_assets(
    MASTER_DIR, recursive=bool(os.environ.get('WUWA_COMPILE_RECURSIVE'))))
unreal.log(f'[WuwaCompile] {len(paths)} masters')
for p in paths:
    mat = unreal.load_asset(p)
    if not isinstance(mat, unreal.Material):
        continue
    MEL.recompile_material(mat)
    unreal.SystemLibrary.execute_console_command(None, 'recompileshaders material ' + mat.get_name())
    s = MEL.get_statistics(mat)
    unreal.log(f'[WuwaCompile] {mat.get_name()}: blend {mat.get_editor_property("blend_mode")}, pixel {s.num_pixel_shader_instructions}, '
               f'vertex {s.num_vertex_shader_instructions}, samplers {s.num_samplers}')
unreal.log('[WuwaCompile] done')
if os.environ.get('WUWA_QUIT_AFTER'):
    unreal.SystemLibrary.quit_editor()
