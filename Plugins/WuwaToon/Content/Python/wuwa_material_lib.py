"""Helpers for generating WuwaToon materials from Python (UE 5.8 editor scripting)."""
import math

import unreal

MEL = unreal.MaterialEditingLibrary
MPC_PATH = '/Game/WuWa/Materials/MPC_WuwaToon'
INCLUDE_ROOT = '/Plugin/WuwaToon/Private/'


def log(msg):
    unreal.log('[WuwaMat] ' + msg)


def new_material(path, shading_model=unreal.MaterialShadingModel.MSM_UNLIT, blend=unreal.BlendMode.BLEND_OPAQUE, two_sided=False):
    """Create the material, or rebuild an existing one in place. Deleting a master that meshes / MIs / loaded components
    still reference fails in ForceDeleteObjects (seen with M_Wuwa_Hidden), so existing assets keep their identity and
    only lose their expression graph."""
    folder, name = path.rsplit('/', 1)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mat = unreal.load_asset(path)
        MEL.delete_all_material_expressions(mat)
    else:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property('shading_model', shading_model)
    mat.set_editor_property('blend_mode', blend)
    mat.set_editor_property('two_sided', two_sided)
    # Kuro character MIs set bUsedWithSkeletalMesh / bUsedWithMorphTargets; without the flags UE renders the
    # default (checkerboard) material on skinned meshes until it patches the flag and recompiles in the editor.
    mat.set_editor_property('used_with_skeletal_mesh', True)
    mat.set_editor_property('used_with_morph_targets', True)
    return mat


def render_target(path, size, fmt, clear_color):
    """Load or create a TextureRenderTarget2D (size / format / clear colour are (re)applied either way)."""
    folder, name = path.rsplit('/', 1)
    rt = unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else         unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.TextureRenderTarget2D,
                                                                 unreal.TextureRenderTargetFactoryNew())
    rt.set_editor_property('size_x', size[0]); rt.set_editor_property('size_y', size[1])
    rt.set_editor_property('render_target_format', fmt)
    rt.set_editor_property('clear_color', clear_color)
    unreal.EditorAssetLibrary.save_loaded_asset(rt, only_if_is_dirty=False)
    return rt


def node(mat, cls, x, y, **props):
    n = MEL.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def mpc_layout():
    """Uniform-buffer layout of MPC_WuwaToon as UE packs it: scalars first (4 per float4), then vectors."""
    mpc = unreal.load_asset(MPC_PATH)
    scalars = [p.get_editor_property('parameter_name') for p in mpc.get_editor_property('scalar_parameters')]
    vectors = [p.get_editor_property('parameter_name') for p in mpc.get_editor_property('vector_parameters')]
    base = int(math.ceil(len(scalars) / 4.0))
    return {
        'scalar': {str(n): (i // 4, 'xyzw'[i % 4]) for i, n in enumerate(scalars)},
        'vector': {str(n): base + i for i, n in enumerate(vectors)},
    }


def light_loop_code(layout, state='St', params='P', inputs='I'):
    """HLSL that feeds the 16 toon light records from MPC_WuwaToon (collection 0) into WuwaToonResolveLight.
    Indices are literals computed from the MPC's packed layout (scalars first, then vectors)."""
    first = layout['vector']['ToonLight0_L0']
    for l in range(16):
        for r in range(9):
            assert layout['vector'][f'ToonLight{l}_L{r}'] == first + l * 9 + r, 'MPC light rows are not contiguous'
    row, comp = layout['scalar']['ToonLightCount']
    rows = ', '.join(f'MaterialCollection0.Vectors[{first} + L * 9 + {r}]' for r in range(9))
    return '\n'.join([
        f'int WuwaLightCount = min((int)MaterialCollection0.Vectors[{row}].{comp}, 16);',
        '[loop] for (int L = 0; L < WuwaLightCount; ++L)',
        f'    WuwaToonResolveLight({state}, {params}, {inputs}, {rows});',
    ])


def custom(mat, x, y, code, inputs, output_type, includes, defines=(), description='WuwaToon'):
    """inputs: list of (name, expression, output_name). Returns the Custom expression."""
    c = node(mat, unreal.MaterialExpressionCustom, x, y)
    c.set_editor_property('code', code)
    c.set_editor_property('description', description)
    c.set_editor_property('output_type', output_type)
    c.set_editor_property('include_file_paths', [INCLUDE_ROOT + i for i in includes])
    ds = []
    for name, value in defines:
        d = unreal.CustomDefine()
        d.set_editor_property('define_name', name)
        d.set_editor_property('define_value', value)
        ds.append(d)
    c.set_editor_property('additional_defines', ds)
    ci = []
    for name, _, _ in inputs:
        i = unreal.CustomInput()
        i.set_editor_property('input_name', name)
        ci.append(i)
    c.set_editor_property('inputs', ci)
    for name, expr, out in inputs:
        MEL.connect_material_expressions(expr, out, c, name)
    return c


def mpc_param(mat, x, y, name):
    return node(mat, unreal.MaterialExpressionCollectionParameter, x, y,
                collection=unreal.load_asset(MPC_PATH), parameter_name=name)


def compile_and_report(mat):
    MEL.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    # Commandlets don't flush async shader jobs; this console command compiles the material synchronously
    # and logs any HLSL errors (LogShaderCompilers) for the current shader platform.
    unreal.SystemLibrary.execute_console_command(None, 'recompileshaders material ' + mat.get_name())
    stats = MEL.get_statistics(mat)
    log(f'{mat.get_path_name()}: pixel instructions {stats.num_pixel_shader_instructions}, '
        f'vertex {stats.num_vertex_shader_instructions}, samplers {stats.num_samplers}')
    return stats
