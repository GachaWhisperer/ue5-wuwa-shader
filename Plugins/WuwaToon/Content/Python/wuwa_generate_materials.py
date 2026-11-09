"""Generate WuwaToon master materials from Shaders/Private/Specs/*.json and a character's material instances
from Specs/<Character>_MIs.json, then assign them to the character mesh (and its outline mesh).

Each master is Unlit. One pixel Custom node runs the ported Kuro base pass (-> virtual GBuffer), emulates the
8-bit GBuffer storage, then runs the in-material FKuroToonShadingPS resolve (WuwaToonResolve.ush). The spec's
WPO / vertex-interpolator blocks become vertex-stage Custom nodes. See research/FINDINGS.md for deviations.

Kuro's per-section extra materials (outline / HET / HETA / FS; Specs/<Character>_ExtraMaterials.json, exported from the
cooked mesh's LODSectionExtraMaterialMap by tools/export_mesh_extra_materials.py) decide which master *mode* each spec is
built in and are written onto the mesh as UWuwaToonExtraMaterialsUserData, from which AWuwaToonCharacterActor builds its
follower meshes (research/shaders/HETPasses.md §4):
  HET_  -> mask mode   (Masked, emissive = capture mask, OpacityMask = WriteStencil clip input)   -> HET capture
  FS_   -> mask mode   (Opaque, emissive = capture mask, WPO = Face_FS PositionOffset)             -> FS capture
  HETA_ -> translucent (full hair resolve, Opacity = HET cut * saturate(MainTex.a*OpacityIntensity))
  base MI of a section carrying HETA_ -> "<spec>_HETCut" variant (Masked, OpacityMask = 1 - HET cut)
  base MIs drawn before the FS pass (RenderQueue < FS queue) -> FS receive (A.z replaced under the FS shell)
  slots whose MI chain ends in a bUsedWithEmpty material (Kuro M_Empty, e.g. MI_Eye_OL) -> not drawn

Run (paths with spaces can't go through -script):
  set WUWA_CHARACTER=Yangyang
  UnrealEditor.exe WuwaRender.uproject -ExecutePythonScript="import wuwa_generate_materials"   (offscreen editor compiles shaders)
"""
import json
import os
import re

import unreal

import wuwa_material_lib as W

PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SPEC_DIR = os.path.join(PLUGIN_DIR, 'Shaders', 'Private', 'Specs')
MASTER_DIR = '/Game/WuWa/Materials/Masters'
RT_DIR = '/Game/WuWa/Validation/Yangyang'
# 'twosidedsign': Parameters.TwoSidedSign inlined from the spec's ue_expr (two-sided V2 bodies); 'frontface' = graph node.
# engine_texture inputs read from the UE translucent base pass: name -> (texture, sampler, node flagging the usage)
SCENE_TEXTURES = {
    'SceneColor': ('SceneColorCopyTexture', 'SceneColorCopySampler',
                   lambda mat, x, y: W.node(mat, unreal.MaterialExpressionSceneColor, x, y)),
    'SceneDepth': ('SceneTexturesStruct.SceneDepthTexture', 'View.SharedPointClampedSampler',
                   lambda mat, x, y: W.node(mat, unreal.MaterialExpressionSceneDepth, x, y)),
}
INLINE_KINDS = {'worldnormal', 'worldtangent', 'worldbitangent', 'worldposition', 'cameravector', 'view', 'primitive', 'svposition',
                'twosidedsign'}
# 'constant': a fixed value the Kuro permutation hard-wires (e.g. ForDragon_Outline_Second VertexColor = 0, no VG stream);
# inlined as an HLSL literal of the spec `value`
CMOT = {'float': unreal.CustomMaterialOutputType.CMOT_FLOAT1, 'float2': unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        'float3': unreal.CustomMaterialOutputType.CMOT_FLOAT3, 'float4': unreal.CustomMaterialOutputType.CMOT_FLOAT4}
WIDTH = {'float': 1, 'float2': 2, 'float3': 3, 'float4': 4}
DEFAULT_CUBE = '/Engine/EngineResources/DefaultTextureCube'
_MPC_NAMES = {}


def MPC_NAMES():
    """Parameter names of MPC_WuwaToon by kind (cached); an unknown name must fail the build, not bind 'None'."""
    if not _MPC_NAMES:
        lay = W.mpc_layout()
        _MPC_NAMES.update(scalar=set(lay['scalar']), vector=set(lay['vector']))
    return _MPC_NAMES

MESH_PATHS = {'Yangyang': '/Game/WuWa/Characters/Yangyang/Mesh/R2T1YangyangMd10011/SkeletalMeshes/R2T1YangyangMd10011'}
MASK_RTS = {  # custom input -> (material texture parameter, render target asset under RT_DIR)
    'Wuwa_HETMask': ('WuwaHETMask', 'RT_WuwaHETMask'),
    'Wuwa_FSMask': ('WuwaFaceShadowMask', 'RT_WuwaFaceShadowMask'),
}
EXTRA_MPC = {'Wuwa_HETEnable': 'HETEnable', 'Wuwa_HETMaxBehind': 'HETMaxBehind', 'Wuwa_HETAOpacityScale': 'HETAOpacityScale',
             'Wuwa_FSEnable': 'FSEnable', 'Wuwa_FSDepthEps': 'FSDepthEps'}
EXTRA_INCLUDE = '/Plugin/WuwaToon/Private/WuwaToonExtraPasses.ush'
# Plugin-side per-character mask ID (UWuwaToonCharacterComponent::MaskID, CPD slot 35; Kuro's CPD rows cover 0..31, slot 26 = wet). Mask materials
# write it into the capture's G channel, readers only accept their own ID (cross-character HET cut / FS shadow guard).
MASK_ID_CPD = 35
SLOT_TYPE_NAMES = {0: 'UNKNOWN', 1: 'BODY', 2: 'OUTLINE', 3: 'EYE_MASK', 4: 'HAIR_EYE_TRANSPARENT', 5: 'FACE_SHADOW'}
# The star mark (M_Char_XinHen, bit-exact port) has emissive exactly 0 with the MI's own values, so it would draw a black
# clipped silhouette; its colours are driven at runtime by gameplay (Unknown). Hidden unless WUWA_SHOW_STAR=1.
HIDDEN_UNLESS_ENV = {'ToonStar_XinHen.json': 'WUWA_SHOW_STAR'}

# Kuro FS_Face (RenderQueue 190) writes A.z after the 180-queue receivers: replace A.z under the shifted bangs shell.
FS_RECEIVE_CODE = r'''
G.A.z = WuwaFS_ApplyRT(G.A.z, Wuwa_FSMask, Wuwa_ViewportUV, Wuwa_Depth, Wuwa_FSDepthEps, Wuwa_FSSolidShadowStrength,
	Wuwa_FSEnable, ResolvedView.ViewToClip[3][3], Wuwa_CharacterID);
'''
# Kuro 195: bangs skip HET-stencil pixels -> Opacity Mask (clip 0.5).
HET_CUT_CODE = r'''
OutHETKeep = 1.0 - WuwaHET_CutRT(Wuwa_HETMask, Wuwa_ViewportUV, Wuwa_Depth, Wuwa_HETMaxBehind, Wuwa_HETEnable,
	ResolvedView.ViewToClip[3][3], Wuwa_CharacterID);
'''
# Kuro 300: HETA redraws the bangs on HET pixels; per-texel weight = the GBufferC.a value HETA tags (pre-store G.C.a).
HETA_CODE = r'''
OutOpacity = WuwaHETA_OpacityRT(Wuwa_HETMask, Wuwa_ViewportUV, Wuwa_Depth, Wuwa_HETMaxBehind, Wuwa_HETEnable, G.C.a,
	Wuwa_HETAOpacityScale, ResolvedView.ViewToClip[3][3], Wuwa_CharacterID);
'''

RESOLVE_INPUTS = [  # (custom input name, MPC parameter or special source)
    ('Wuwa_AOStrength', 'ToonAOStrength'), ('Wuwa_GIEnable', 'ToonGIEnable'), ('Wuwa_AmbientParams', 'ToonAmbientParams'),
    ('Wuwa_AmbA_Far', 'ToonAmbientA_Far'), ('Wuwa_AmbB_Far', 'ToonAmbientB_Far'), ('Wuwa_LightColor', 'ToonMainLightColor'),
    ('Wuwa_LightDir', 'ToonMainLightDir'), ('Wuwa_AORemap', 'ToonAORemap'), ('Wuwa_DepthGradient', 'ToonDepthGradient'),
    ('Wuwa_AmbB_Near', 'ToonAmbientB_Near'), ('Wuwa_AmbA_Near', 'ToonAmbientA_Near'), ('Wuwa_RimPass', 'ToonRimPass'),
    ('Wuwa_RimTint', 'ToonRimTint'), ('Wuwa_ShadowOrigin', 'ToonShadowOrigin'), ('Wuwa_ShadowForward', 'ToonShadowForward'),
    ('Wuwa_ShadowRight', 'ToonShadowRight'), ('Wuwa_ShadowUp', 'ToonShadowUp'),
]

RESOLVE_CODE = r'''
G = WuwaToonGBufferStore(G);
FWuwaToonAmbientParams P;
P.AOStrength = Wuwa_AOStrength;        P.GIEnable = Wuwa_GIEnable.xy;       P.AmbientParams = Wuwa_AmbientParams.xyz;
P.AmbientA_Far = Wuwa_AmbA_Far.rgb;    P.AmbientB_Far = Wuwa_AmbB_Far.rgb;  P.MainLightColor = Wuwa_LightColor.rgb;
P.MainLightDir = Wuwa_LightDir.xyz;    P.AORemap = Wuwa_AORemap.xyz;        P.DepthGradient = Wuwa_DepthGradient.xy;
P.AmbientB_Near = Wuwa_AmbB_Near.rgb;  P.AmbientA_Near = Wuwa_AmbA_Near.rgb;
FWuwaToonResolveInputs I;
I.Depth = Wuwa_Depth;
I.WorldPos = WSHackToFloat(GetWorldPosition(Parameters));
I.V = Parameters.CameraVector;
I.WorldToView = (float3x3)ResolvedView.TranslatedWorldToView;
I.ViewportUV = Wuwa_ViewportUV;
I.FOVRelated = 2.0 * atan(1.0 / ResolvedView.ViewToClip[1][1]);
// t5 producer: Kuro single-pass CSM math (5x5 soft-compare PCF, N.L transition, sharpen/fade/sqrt encode) on the
// plugin light-space capture. N = decoded toon GBuffer normal, as Kuro's projection shaders use. Toon CSM ends at
// cascade 1 (WUWA_KURO_CSM1_DISTANCE). .z = sqrt(light function) = 1 (no light function). research/shaders/ToonShadow.md
I.ShadowMaskXZ = WuwaToonShadowMaskKuroSingle(Wuwa_ToonShadow, I.WorldPos, Wuwa_Depth, WuwaOctDecode(G.A.xy),
	Wuwa_LightDir.xyz, Wuwa_ShadowOrigin, Wuwa_ShadowForward, Wuwa_ShadowRight.xyz, Wuwa_ShadowUp.xyz, 1.0 / 1024.0,
	Wuwa_ShadowRight.w, WUWA_KURO_CSM1_DISTANCE);
I.Exposure = Wuwa_Exposure;
I.IndirectDiffuse = 0; I.GITint = 0; I.PassGIEnable = false;   // t7/t9 screen GI not available (FINDINGS.md deviation 4)
I.RimWidthScale = Wuwa_RimPass.x; I.RimTint = Wuwa_RimTint.rgb;
FWuwaToonResolveState St = WuwaToonResolveBegin(G, P, I);
%LIGHTS%
// Kuro writes base-pass emissive (o0) before FKuroToonShadingPS; the toon pass is assumed additive (blend state not in DXBC).
return WuwaToonResolveEnd(St, P, I, Wuwa_ToonDepth, Wuwa_ToonDepthSampler) + G.Emissive;
'''


_DF_VIEW = r'(PreViewTranslation|PrevPreViewTranslation|WorldCameraOrigin|PrevWorldCameraOrigin|WorldViewOrigin|WorldToClip|ClipToWorld|PrevWorldToClip|PrevClipToWorld)'
# FPrimitiveSceneData members that are double-float in UE 5.8 (SceneData.ush): FDFMatrix / FDFInverseMatrix / FDFVector3
_DF_PRIM = r'(?:LocalToWorld|WorldToLocal|PreviousLocalToWorld|PreviousWorldToLocal|ActorWorldPosition|ObjectWorldPosition)'
# calls that already take a DF / LWC / WS value and return a float type
_DEMOTED_BY = r'(?:WSHackToFloat|LWCHackToFloat|DFHackToFloat|LWCToFloat|DFDemote|WSDemote|DFToFloat3x3)'


def _wrap_bare(expr, target, wrapper):
    """Wrap every match of `target` that is not already the argument of a demotion call in `wrapper(...)`."""
    out, last = [], 0
    for m in re.finditer(target, expr):
        if re.search(_DEMOTED_BY + r'[(]\s*$', expr[:m.start()]):
            continue
        out += [expr[last:m.start()], f'{wrapper}({m.group(0)})']
        last = m.end()
    return ''.join(out) + expr[last:]


def lwc_fix(expr):
    """UE 5.8 large-world-coordinate types in inline spec expressions: ResolvedView DF vectors / matrices and the primitive
    DF members (LocalToWorld / WorldToLocal FDFMatrix / FDFInverseMatrix, ActorWorldPosition FDFVector3) are not float types.
    Demote them exactly as the hand-written bindings do (WSHackToFloat / DFHackToFloat = DFDemote: absolute-world float
    matrices / positions, as UE 4.26 Primitive.* were); occurrences already demoted are left alone. Only the binding
    expression changes."""
    if not expr:
        return expr
    # a row of the DF LocalToWorld cannot be indexed before demotion, whichever wrapper the spec used
    expr = re.sub(r'(?:WSHackToFloat|LWCHackToFloat|DFHackToFloat|LWCToFloat)[(]GetPrimitiveData[(]Parameters[)][.]LocalToWorld\x5b([0-9])\x5d[)]',
                  lambda m: 'DFHackToFloat(GetPrimitiveData(Parameters).LocalToWorld)[' + m.group(1) + '].xyz', expr)
    # bare DF primitive members / view members (indexing of a matrix row then applies to the demoted float4x4)
    expr = _wrap_bare(expr, r'GetPrimitiveData[(]Parameters[)][.]' + _DF_PRIM + r'(?![A-Za-z0-9_])', 'DFHackToFloat')
    expr = _wrap_bare(expr, r'ResolvedView[.]' + _DF_VIEW + r'(?![A-Za-z0-9_])', 'DFHackToFloat')
    # a bare FWSVector3 position accessor bound to a float3
    if re.fullmatch(r'Get(?:Actor|Object)?WorldPosition(?:_NoMaterialOffsets)?[(]Parameters[)]', expr.strip()):
        expr = f'WSHackToFloat({expr.strip()})'
    return expr


# Annotations that some generated specs carried inside ue_expr (Round 4 compile failures): never valid HLSL. A spec whose
# inline binding still contains one fails the master build with a clear message instead of a shader-compile error.
_PROSE = re.compile(r'[.][.][.]|->|\bLWC:|[(]LWC|material node|ActorPosition node|\[U\]|[(]VS\b|\bnot\b|;')


def inline_expr(inp):
    expr = lwc_fix(inp.get('ue_expr'))
    if expr and _PROSE.search(expr):
        raise ValueError(f"input {inp['name']}: ue_expr is an annotation, not HLSL: {expr!r} (fix the spec binding)")
    return expr


def hlsl_literal(t, v):
    if v is None:
        v = 0.0
    if isinstance(v, (int, float)):
        v = [float(v)] * WIDTH.get(t, 1) if t != 'float' else float(v)
    if t == 'float':
        return repr(float(v if not isinstance(v, list) else v[0]))
    if t == 'uint':
        return f'{int(v)}u'
    if t.startswith('float') and len(t) == 6:
        vals = (list(v) + [0.0] * 4)[:WIDTH[t]]
        return f'{t}(' + ', '.join(repr(float(x)) for x in vals) + ')'
    if t.startswith('float') and 'x' in t:
        return f'({t})0'
    return f'({t})0'


def mask(mat, expr, out, comps, x, y):
    """Return an expression producing exactly `comps` channels of (expr, out)."""
    m = W.node(mat, unreal.MaterialExpressionComponentMask, x + 150, y,
               r='r' in comps, g='g' in comps, b='b' in comps, a='a' in comps)
    W.MEL.connect_material_expressions(expr, out, m, '')
    return m, ''


class Builder:
    def __init__(self, mat, character_textures):
        self.mat, self.textures, self.row = mat, character_textures, 0
        self.params = {}          # parameter name -> expression (shared between stages)

    def pos(self):
        self.row += 1
        return -2400, self.row * 70

    def texture(self, name, cube=False):
        """Master default texture of a parameter. The default's class decides the Custom-node argument type (Texture2D /
        TextureCube), so a TextureCube input (e.g. M_CharMonster PBRCubeMap, Goblet ReflectCubemap) needs a cube default."""
        path = self.textures.get(name)
        if path and unreal.EditorAssetLibrary.does_asset_exist(path):
            tex = unreal.load_asset(path)
            if isinstance(tex, unreal.TextureCube) == cube:
                return tex
        return unreal.load_asset(DEFAULT_CUBE if cube else '/Engine/EngineResources/WhiteSquareTexture')

    def param_node(self, cls, name, **props):
        key = (cls.__name__, name, tuple(sorted(props.items())) if cls is unreal.MaterialExpressionScalarParameter and 'use_custom_primitive_data' in props else ())
        if key not in self.params:
            self.params[key] = W.node(self.mat, cls, *self.pos(), parameter_name=name, **props)
        return self.params[key]

    def make(self, inp, interp_nodes):
        """Return (expression, output pin) for a graph-fed input, or None when the input is inlined."""
        k, t, x, y = inp['kind'], inp.get('type', 'float'), *self.pos()
        if k in INLINE_KINDS or k in ('sampler', 'output', 'engine_sampler', 'kuro_light_buffer', 'constant'):
            return None
        if k in ('engine_texture_load', 'kuro_forward') and inp['name'] == 'EyeAdaptation':
            return W.node(self.mat, unreal.MaterialExpressionEyeAdaptation, x, y), ''
        if k == 'kuro_forward':
            return None   # no UE source (Kuro forward shadow factor / light list): inlined as the spec default
        if k == 'engine_texture' and inp['name'] in SCENE_TEXTURES:
            return None   # aliased to the translucent pass's scene textures in the Custom-node prelude
        if k == 'engine_texture':
            tex = unreal.load_asset(inp.get('asset') or '/Engine/EngineMaterials/' + str(inp.get('default')))
            return W.node(self.mat, unreal.MaterialExpressionTextureObject, x, y, texture=tex), ''
        if k == 'material_texture':
            # texture object of the root material (no MI parameter): a parameter named after the input, filled from the
            # character's texture map when the importer staged it, else white
            n = self.param_node(unreal.MaterialExpressionTextureObjectParameter, inp['name'])
            tex = self.texture(inp['name'])
            n.set_editor_property('texture', tex)
            n.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if tex.get_editor_property('srgb')
                                  else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
            return n, ''
        if k == 'texture' and not inp.get('param'):
            # engine texture that is not a material parameter (e.g. UE DitherTemporalAA noise): plain Texture Object
            tex = unreal.load_asset(inp.get('engine_texture') or '/Engine/EngineResources/WhiteSquareTexture')
            return W.node(self.mat, unreal.MaterialExpressionTextureObject, x, y, texture=tex), ''
        if k == 'texture':
            tex = self.texture(inp['param'], cube=t == 'TextureCube')
            n = self.param_node(unreal.MaterialExpressionTextureObjectParameter, inp['param'])
            n.set_editor_property('texture', tex)
            n.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if tex.get_editor_property('srgb')
                                  else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
            return n, ''
        if k == 'scalar':
            return self.param_node(unreal.MaterialExpressionScalarParameter, inp['param'],
                                   default_value=float(inp.get('default') or 0.0)), ''
        if k == 'uniform_expression':
            # CPU-evaluated preshader (e.g. cos/sin of Second_Rotation): a material parameter named after the input,
            # evaluated per MI by tools/gen_wuwa_specs_roster.py (spec `expr` over `params`); default = spec default.
            d = inp.get('default')
            if WIDTH.get(t, 1) == 1:
                return self.param_node(unreal.MaterialExpressionScalarParameter, inp['name'],
                                       default_value=float(d if isinstance(d, (int, float)) else 0.0)), ''
            dv = (list(d) if isinstance(d, list) else [0.0] * 4) + [0.0] * 4
            n = self.param_node(unreal.MaterialExpressionVectorParameter, inp['name'],
                                default_value=unreal.LinearColor(*map(float, dv[:4])))
            if WIDTH.get(t) == 4:
                a = W.node(self.mat, unreal.MaterialExpressionAppendVector, x + 150, y)
                W.MEL.connect_material_expressions(n, '', a, 'A'); W.MEL.connect_material_expressions(n, 'A', a, 'B')
                return a, ''
            return (n, 'RGB') if WIDTH.get(t) == 3 else mask(self.mat, n, '', 'rgba'[:WIDTH[t]], x, y)
        if k in ('vector', 'toonlight'):
            name = inp.get('param') or f"ToonShadowLight{inp.get('index', 0)}"
            d = (list(inp.get('default') or [0, 0, 0, 0]) + [0, 0, 0, 0])[:4]
            n = self.param_node(unreal.MaterialExpressionVectorParameter, name, default_value=unreal.LinearColor(*map(float, d)))
            if WIDTH.get(t) == 4:   # the default pin is RGB only; float4 arguments need RGB + A assembled
                a = W.node(self.mat, unreal.MaterialExpressionAppendVector, x + 150, y)
                W.MEL.connect_material_expressions(n, '', a, 'A'); W.MEL.connect_material_expressions(n, 'A', a, 'B')
                return a, ''
            return (n, 'RGB') if WIDTH.get(t) == 3 else mask(self.mat, n, '', 'rgba'[:WIDTH[t]], x, y)
        if k == 'uv':
            n = W.node(self.mat, unreal.MaterialExpressionTextureCoordinate, x, y, coordinate_index=int(inp['index']))
            return (n, '') if not inp.get('channel') or inp['channel'] == 'xy' else mask(self.mat, n, '', inp['channel'].replace('x', 'r').replace('y', 'g'), x, y)
        if k == 'vertexcolor':
            n = W.node(self.mat, unreal.MaterialExpressionVertexColor, x, y)
            ch = inp.get('channel')
            if not ch and WIDTH.get(t, 1) == 1:   # e.g. 'VertexColorA' (float) without an explicit channel
                ch = inp['name'][-1].lower() if inp['name'][-1] in 'RGBA' else 'r'
            if ch:
                return n, ch.upper()
            if WIDTH.get(t) == 4:
                a = W.node(self.mat, unreal.MaterialExpressionAppendVector, x + 150, y)
                W.MEL.connect_material_expressions(n, '', a, 'A'); W.MEL.connect_material_expressions(n, 'A', a, 'B')
                return a, ''
            return n, ''
        if k == 'cpd':
            idx = inp['index'] if isinstance(inp['index'], list) else [inp['index']]
            nodes = [self.param_node(unreal.MaterialExpressionScalarParameter, f'CPD{i}', use_custom_primitive_data=True,
                                     primitive_data_index=int(i)) for i in idx]
            out = nodes[0]
            for nxt in nodes[1:]:
                a = W.node(self.mat, unreal.MaterialExpressionAppendVector, x + 150, y)
                W.MEL.connect_material_expressions(out, '', a, 'A'); W.MEL.connect_material_expressions(nxt, '', a, 'B')
                out = a
            return out, ''
        if k == 'mpc':
            name = inp['mpc_param']
            if inp.get('mpc') == 'MPC_Cloth':   # hosted in MPC_WuwaToon as Cloth_* vectors (wuwa_create_mpc.CLOTH_VECTORS)
                name = 'Cloth_' + name
            if name not in MPC_NAMES()['scalar'] | MPC_NAMES()['vector']:
                raise ValueError(f"{inp['name']}: MPC parameter {name} is not in MPC_WuwaToon (re-run wuwa_create_mpc)")
            n = W.mpc_param(self.mat, x, y, name)
            if t == 'float':
                return (n, '') if name in MPC_NAMES()['scalar'] else mask(self.mat, n, '', 'r', x, y)
            return (n, '') if WIDTH[t] == 4 else mask(self.mat, n, '', 'rgba'[:WIDTH[t]], x, y)
        if k == 'interpolator':
            return interp_nodes[inp['name']], ''
        if k == 'frontface':
            return W.node(self.mat, unreal.MaterialExpressionTwoSidedSign, x, y), ''
        raise ValueError(f"unhandled input kind {k} for {inp['name']}")

    def custom(self, inputs, code, out_type, includes, interp_nodes, extra=(), additional_outputs=(), desc='WuwaToon'):
        prelude, graph, postlude = [], [], []
        scene = sorted({inp['name'] for inp in inputs if inp['kind'] == 'engine_texture' and inp['name'] in SCENE_TEXTURES})
        if scene:
            # Kuro samples the opaque scene colour / device depth directly; UE exposes them to translucent base-pass
            # materials as SceneColorCopyTexture (same EncodeSceneColorForMaterialNode encoding as UE 4.26) and
            # SceneTexturesStruct.SceneDepthTexture. Other passes of the material (hit proxy, velocity) get a dummy.
            for name in scene:
                tex, smp, fallback = SCENE_TEXTURES[name]
                prelude += [f'#if defined({tex.split(".")[0]})', f'#define {name} {tex}', f'#define {name}Sampler {smp}',
                            '#else', f'#define {name} View.PreIntegratedBRDF', f'#define {name}Sampler View.PreIntegratedBRDFSampler',
                            '#endif']
                postlude += [f'#undef {name}', f'#undef {name}Sampler']
                # a real scene-texture node flags the material (bUsesSceneColor / scene depth) so UE makes the copy
                graph.append((f'Wuwa_Uses{name}', fallback(self.mat, *self.pos()), ''))
        for inp in inputs:
            made = self.make(inp, interp_nodes)
            if made is None:
                if inp['kind'] in ('sampler', 'engine_sampler') and inp['name'] in {f'{s}Sampler' for s in scene}:
                    continue
                if inp['kind'] == 'constant':
                    prelude.append(f"{inp['type']} {inp['name']} = {hlsl_literal(inp['type'], inp.get('value', inp.get('default')))};")
                    continue
                if inp['kind'] in ('kuro_forward', 'kuro_light_buffer'):
                    d = inp.get('default')
                    expr = hlsl_literal(inp['type'], d) if d is not None else f"({inp['type']})0"
                    prelude.append(f"{inp['type']} {inp['name']} = {expr};")
                    continue
                if inp['kind'] == 'engine_sampler':
                    prelude.append(f"#define {inp['name']} View.SharedBilinearClampedSampler")
                    postlude.append(f"#undef {inp['name']}")
                    continue
                if inp['kind'] == 'sampler' and inp['name'] != inp.get('texture', '') + 'Sampler' and inp.get('ue_expr'):
                    # Non-default sampler (e.g. Kuro's shared clamp sampler for the face SDF): alias the UE shared sampler.
                    prelude.append(f"#define {inp['name']} {inp['ue_expr']}")
                    continue
                if inp['kind'] in INLINE_KINDS:
                    expr = inline_expr(inp) or hlsl_literal(inp.get('type', 'float'), inp.get('default'))
                    if expr == 'Parameters.TangentToWorldSign' and inp.get('stage') != 'vs':
                        # UE 5.8 pixel parameters drop TangentToWorldSign; row 1 (bitangent) already carries the sign.
                        expr = ('(dot(cross(Parameters.TangentToWorld[2], Parameters.TangentToWorld[0]), '
                                'Parameters.TangentToWorld[1]) < 0 ? -1.0 : 1.0)')
                    prelude.append(f"{inp['type']} {inp['name']} = {expr};")
                continue
            graph.append((inp['name'], made[0], made[1]))
        graph.extend(extra)
        seen = set()   # a shared extra input (e.g. Wuwa_CharacterID for FS receive + HET cut) is wired once
        graph = [g for g in graph if not (g[0] in seen or seen.add(g[0]))]
        c = W.custom(self.mat, -600, 0 if out_type != CMOT['float3'] or desc != 'WuwaToon' else 300,
                     '\n'.join(prelude) + '\n' + code + ('\n' + '\n'.join(postlude) if postlude else ''), graph, out_type, [i.split('/Private/')[-1] for i in includes], (), desc)
        if additional_outputs:
            outs = []
            for name, t in additional_outputs:
                o = unreal.CustomOutput()
                o.set_editor_property('output_name', name)
                o.set_editor_property('output_type', CMOT[t])
                outs.append(o)
            c.set_editor_property('additional_outputs', outs)
        return c


def resolve_extra(b):
    extra = [(name, W.mpc_param(b.mat, *b.pos(), mpc), '') for name, mpc in RESOLVE_INPUTS]
    extra.append(('Wuwa_Depth', W.node(b.mat, unreal.MaterialExpressionPixelDepth, *b.pos()), ''))
    extra.append(('Wuwa_ViewportUV', W.node(b.mat, unreal.MaterialExpressionScreenPosition, *b.pos()), 'ViewportUV'))
    extra.append(('Wuwa_Exposure', W.node(b.mat, unreal.MaterialExpressionEyeAdaptation, *b.pos()), ''))
    for name, rt in (('Wuwa_ToonDepth', 'RT_ToonDepth'), ('Wuwa_ToonShadow', 'RT_ToonShadow')):
        n = W.node(b.mat, unreal.MaterialExpressionTextureObjectParameter, *b.pos(), parameter_name=name,
                   texture=unreal.load_asset(f'{RT_DIR}/{rt}'), sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        extra.append((name, n, ''))
    return extra


def extra_inputs(b, names, scalars=None):
    """Graph inputs for the extra-pass helpers: mask RTs (texture objects defaulting to the capture targets), MPC globals,
    and per-material scalars given as {input name: (parameter name, default)}."""
    out = []
    for name in names:
        if name in MASK_RTS:
            param, rt = MASK_RTS[name]
            n = W.node(b.mat, unreal.MaterialExpressionTextureObjectParameter, *b.pos(), parameter_name=param,
                       texture=unreal.load_asset(f'{RT_DIR}/{rt}'), sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
            out.append((name, n, ''))
        elif name in EXTRA_MPC:
            out.append((name, W.mpc_param(b.mat, *b.pos(), EXTRA_MPC[name]), ''))
        elif name == 'Wuwa_CharacterID':
            out.append((name, b.param_node(unreal.MaterialExpressionScalarParameter, f'CPD{MASK_ID_CPD}',
                                           use_custom_primitive_data=True, primitive_data_index=MASK_ID_CPD), ''))
    for name, (param, default) in (scalars or {}).items():
        out.append((name, b.param_node(unreal.MaterialExpressionScalarParameter, param, default_value=float(default)), ''))
    return out


def gbuffer_split(spec):
    code = spec['custom_node_code']
    m = re.search(r'FWuwaToonGBuffer\s+G\s*=\s*[^;]*;', code)
    if not m:
        raise ValueError(f"{spec['name']}: no FWuwaToonGBuffer construction in custom_node_code")
    return code, m


def pixel_code(spec, layout, pre_resolve=''):
    """Spec base-pass call + spec extra outputs, then `pre_resolve` (extra-pass code operating on the raw G), then the
    GBuffer store + in-material FKuroToonShadingPS resolve. The verified base pass itself is untouched."""
    code, m = gbuffer_split(spec)
    tail = code[m.end():]
    keep = [l for l in tail.splitlines() if l.strip() and not re.match(r'\s*Out[ABCD]\s*=', l) and 'return G.Emissive' not in l
            and not re.match(r'\s*(OutA|OutB|OutC|OutD)', l)]
    keep = [re.sub(r'\bOutA = G.A; OutB = G.B; OutC = G.C; OutD = G.D;', '', l) for l in keep]
    return code[:m.end()] + '\n' + '\n'.join(keep) + pre_resolve + RESOLVE_CODE.replace('%LIGHTS%', W.light_loop_code(layout))


def het_mask_code(spec):
    """HET capture material: the verified WriteStencil base pass only supplies its clip input; colour = capture mask."""
    code, m = gbuffer_split(spec)
    if 'OpacityMask' not in code[:m.end()]:
        raise ValueError(f"{spec['name']}: HET spec without an OpacityMask output")
    return (code[:m.end()] + '\nOutOpacityMask = WuwaHET_MaskOpacity(OpacityMask, Wuwa_InvertHETMask);\n'
            'return WuwaExtra_EncodeMask(Wuwa_CharacterID);')


def normalize_wpo(spec):
    """Some generated specs give the wpo block as entry + inputs only: synthesize its Custom-node code."""
    wp = spec.get('wpo')
    if wp and 'custom_node_code' not in wp:
        # out parameters (kind output, e.g. WaterSword MotionEmissiveMask) are passed too: they are the node's own outputs
        args = ', '.join(i['name'] for i in wp['inputs'])
        spec = dict(spec, wpo=dict(wp, custom_node_code=f"return {wp['entry']}({args});"))
    return spec


def with_vertex_blocks(spec):
    """A spec that names an interpolator (e.g. LightDirVS from WuwaToonBaseVS_LightDir) without its VS block borrows the
    shared M_Char_Com block from ToonCommon_BodyUp.json (same VS structure; its parameters keep their Material defaults).
    Used by the toon and the resolve:false (FX / glass) templates alike."""
    have = {vi['name'] for vi in spec.get('vertex_interpolators', [])}
    missing = [i for i in spec['inputs'] if i['kind'] == 'interpolator' and i['name'] not in have and not i.get('output')]
    if not missing:
        return spec
    own = spec.get('wpo')
    # an interpolator the spec's own wpo entry writes as an out parameter (Char_Com_WaterSword: MotionEmissiveMask)
    own_outs = {i['name']: i.get('type', 'float') for i in (own or {}).get('inputs', []) if i['kind'] == 'output'}
    added = [dict(name=i['name'], type=own_outs[i['name']], output=i['name'], entry=own['entry']) for i in missing if i['name'] in own_outs]
    rest = {i['name'] for i in missing} - own_outs.keys()
    donor = json.load(open(os.path.join(SPEC_DIR, 'ToonCommon_BodyUp.json')))
    borrowed = [vi for vi in donor.get('vertex_interpolators', []) if vi['name'] in rest]
    unknown = rest - {vi['name'] for vi in borrowed}
    if unknown:
        raise ValueError(f"{spec['name']}: interpolator(s) {sorted(unknown)} have no vertex_interpolators block and no donor")
    if own:
        # the spec has its own WPO (e.g. Zani fire hair): a donor interpolator written by the base-pass WPO node
        # (MotionEmissiveMask of WuwaToonBaseVS_WPO) comes from a separate vertex Custom node of that block, not the WPO pin
        borrowed = [dict(vi, wpo_block=donor['wpo']) if vi.get('output') and vi.get('entry') != own['entry'] else vi for vi in borrowed]
    spec = dict(spec, vertex_interpolators=list(spec.get('vertex_interpolators', [])) + added + borrowed)
    if any(vi.get('output') for vi in borrowed) and not own:
        # MotionEmissiveMask is an extra output of the shared base-pass WPO node (WuwaToonBaseVS_WPO): borrow it too
        spec['wpo'] = donor['wpo']
    return spec


def wpo_node(b, spec, with_outputs=True):
    """Vertex-stage Custom node of the spec's wpo block (+ the interpolators it outputs), or None."""
    wp = spec.get('wpo')
    if not wp:
        return None
    outs = [(i['name'], i['type']) for i in spec.get('vertex_interpolators', []) if i.get('output') and i.get('entry') == wp['entry']]
    # the entry's own out parameters always exist as node outputs (the synthesized call passes them, normalize_wpo)
    outs += [(i['name'], i.get('type', 'float')) for i in wp['inputs'] if i['kind'] == 'output' and i['name'] not in dict(outs)]
    return b.custom(wp['inputs'], wp['custom_node_code'], CMOT['float3'], [wp['include']], {},
                    additional_outputs=outs if with_outputs else [], desc='WuwaToonWPO')


def interpolator_nodes(b, spec, wpo):
    """{interpolator name: VertexInterpolator node} for the spec's vertex_interpolators blocks."""
    nodes, blocks = {}, {}
    for vi in spec.get('vertex_interpolators', []):
        if vi.get('output') and vi.get('wpo_block'):
            wb = vi['wpo_block']
            if wb['entry'] not in blocks:   # output-only copy of the block (its offset is not connected)
                outs = [(v['name'], v['type']) for v in spec['vertex_interpolators']
                        if v.get('output') and (v.get('wpo_block') or {}).get('entry') == wb['entry']]
                blocks[wb['entry']] = b.custom(wb['inputs'], wb['custom_node_code'], CMOT['float3'], [wb['include']], {},
                                               additional_outputs=outs, desc='WuwaToonVS_' + wb['entry'])
            src, pin = blocks[wb['entry']], vi['output']
        elif vi.get('output'):
            src, pin = wpo, vi['output']
        else:
            src, pin = b.custom(vi['inputs'], vi['custom_node_code'], CMOT[vi.get('returns', vi['type'])], [vi['include']], {},
                                desc='WuwaToonVS_' + vi['name']), ''
        vin = W.node(b.mat, unreal.MaterialExpressionVertexInterpolator, -900, -300 - 80 * len(nodes))
        W.MEL.connect_material_expressions(src, pin, vin, '')
        nodes[vi['name']] = vin
    return nodes


UNLIT_BLEND = {'BLEND_Opaque': unreal.BlendMode.BLEND_OPAQUE, 'BLEND_Masked': unreal.BlendMode.BLEND_MASKED,
               'BLEND_Translucent': unreal.BlendMode.BLEND_TRANSLUCENT, 'BLEND_Additive': unreal.BlendMode.BLEND_ADDITIVE,
               'BLEND_Modulate': unreal.BlendMode.BLEND_MODULATE}


FX_SHADING = {'MSM_Unlit': unreal.MaterialShadingModel.MSM_UNLIT, 'MSM_DefaultLit': unreal.MaterialShadingModel.MSM_DEFAULT_LIT}
# material attribute pins a resolve:false spec may connect to a Custom-node output (ue_material.connect)
FX_ATTR_PINS = {'BaseColor': unreal.MaterialProperty.MP_BASE_COLOR, 'Metallic': unreal.MaterialProperty.MP_METALLIC,
                'Roughness': unreal.MaterialProperty.MP_ROUGHNESS, 'Normal': unreal.MaterialProperty.MP_NORMAL,
                'Specular': unreal.MaterialProperty.MP_SPECULAR}
FX_TLM = {'TLM_VolumetricNonDirectional': 'TLM_VOLUMETRIC_NON_DIRECTIONAL', 'TLM_VolumetricDirectional': 'TLM_VOLUMETRIC_DIRECTIONAL',
          'TLM_VolumetricPerVertexNonDirectional': 'TLM_VOLUMETRIC_PER_VERTEX_NON_DIRECTIONAL',
          'TLM_VolumetricPerVertexDirectional': 'TLM_VOLUMETRIC_PER_VERTEX_DIRECTIONAL', 'TLM_Surface': 'TLM_SURFACE',
          'TLM_SurfacePerPixelLighting': 'TLM_SURFACE_PER_PIXEL_LIGHTING'}


def fx_contract(spec):
    """Custom-node code, additional outputs and attribute-pin wiring of a resolve:false spec.

    ue_material.connect maps material pins to the entry's results: EmissiveColor / Opacity / OpacityMask to an expression over
    X (FWuwaFXOutput) and the entry's out parameters (e.g. Char_Glass 'X.Emissive + ForwardLighting'), the lit-translucent
    attribute pins (BaseColor / Metallic / Roughness / Normal / Specular) to an out parameter. An attribute pin whose source
    is not an out parameter (Char_Translucent 'Specular': '0.5 (default)') keeps the engine default. Out parameters are
    spec inputs of kind 'output'; a Custom-node output is named Out<name> (or <name> if it already starts with 'Out')."""
    um = spec.get('ue_material') or {}
    connect = um.get('connect') or {}
    outs = [i for i in spec['inputs'] if i['kind'] == 'output']
    otype = {i['name']: i.get('type', 'float') for i in outs}
    for k, v in (spec.get('outputs') or {}).items():
        otype.setdefault(k, (v or {}).get('type', 'float'))
    attr = {}
    for pin, src in connect.items():
        src = str(src).strip()
        if pin in FX_ATTR_PINS and re.fullmatch(r'[A-Za-z_]\w*', src) and src in otype:
            attr[pin] = src if src.startswith('Out') else 'Out' + src
    code = spec.get('custom_node_code')
    if code:
        for pin, o in attr.items():
            if not re.search(r'\b' + o + r'\s*=', code):
                raise ValueError(f"{spec['name']}: ue_material.connect {pin} -> {o}, but custom_node_code never writes {o}")
    else:
        emissive = str(connect.get('EmissiveColor', 'X.Emissive')).strip()
        if not re.fullmatch(r'[\w\s.+*()-]+', emissive):
            raise ValueError(f"{spec['name']}: EmissiveColor connect {emissive!r} is not an HLSL expression")
        direct = set(attr.values())   # Out* parameters are passed straight through as the Custom node's own outputs
        decl = ''.join(f"{otype[i['name']]} {i['name']}; " for i in outs if i['name'] not in direct)
        copies = ''.join(f'{o} = {o[3:]};\n' for o in attr.values() if o not in otype)
        args = ', '.join(i['name'] for i in spec['inputs'])
        code = (f"{decl}FWuwaFXOutput X = {spec['entry']}({args});\n{copies}"
                f"OutOpacity = X.Opacity;\nreturn {emissive};")
    extra = [(o, otype.get(o) or otype[o[3:]]) for o in attr.values()]
    return code, [('OutOpacity', 'float')] + extra, attr


def build_unlit_master(spec, textures, path):
    """Specs with "resolve": false (effect / weapon FX / forward-translucent materials, Specs/*.json `ue_material`): the entry
    returns FWuwaFXOutput {Emissive, Opacity}; master with the spec's blend mode, Emissive -> Emissive Color, Opacity ->
    Opacity (translucent / additive) or Opacity Mask (masked). No toon GBuffer store, no WuwaToonResolve.
    ue_material.shading_model MSM_DefaultLit = lit-translucent template (Char_Translucent, Outline_Translucent): DefaultLit,
    the spec's translucency lighting mode, the entry's out parameters on the attribute pins (fx_contract); UE lights it."""
    spec = with_vertex_blocks(normalize_wpo(spec))
    um = spec.get('ue_material') or {}
    blend = UNLIT_BLEND.get(um.get('blend_mode') or spec.get('blend_mode'), unreal.BlendMode.BLEND_TRANSLUCENT)
    shading = FX_SHADING.get(um.get('shading_model'), unreal.MaterialShadingModel.MSM_UNLIT)
    code, additional, attr = fx_contract(spec)
    mat = W.new_material(path, shading_model=shading, blend=blend, two_sided=bool(um.get('two_sided', spec.get('two_sided'))))
    if blend == unreal.BlendMode.BLEND_MASKED and um.get('opacity_mask_clip_value') is not None:
        mat.set_editor_property('opacity_mask_clip_value', float(um['opacity_mask_clip_value']))
    tlm = FX_TLM.get(str(um.get('translucency_lighting_mode') or '').split(' ')[0])
    if shading != unreal.MaterialShadingModel.MSM_UNLIT and tlm and hasattr(unreal.TranslucencyLightingMode, tlm):
        mat.set_editor_property('translucency_lighting_mode', getattr(unreal.TranslucencyLightingMode, tlm))
    b = Builder(mat, textures)
    # ported vertex position offset (e.g. M_AdvancedEffect_CM_VSWPO, WuwaToonBasePass_WeaponFXVS.ush) and vertex
    # interpolators (own blocks, or the borrowed M_Char_Com LightDirVS / MotionEmissiveMask): same wiring as the toon masters
    wpo = wpo_node(b, spec)
    if wpo:
        W.MEL.connect_material_property(wpo, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    interp_nodes = interpolator_nodes(b, spec, wpo)
    ps = b.custom(spec['inputs'], code, CMOT['float3'], [spec['include']], interp_nodes, additional_outputs=additional,
                  desc='WuwaFX')
    W.MEL.connect_material_property(ps, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if blend == unreal.BlendMode.BLEND_MASKED:
        W.MEL.connect_material_property(ps, 'OutOpacity', unreal.MaterialProperty.MP_OPACITY_MASK)
    elif blend != unreal.BlendMode.BLEND_OPAQUE:
        W.MEL.connect_material_property(ps, 'OutOpacity', unreal.MaterialProperty.MP_OPACITY)
    if shading != unreal.MaterialShadingModel.MSM_UNLIT:
        for pin, o in attr.items():
            W.MEL.connect_material_property(ps, o, FX_ATTR_PINS[pin])
    W.compile_and_report(mat)
    return mat


def build_master(spec, textures, layout, mode='surface', fs_receive=False, het_cut=False, fs_strength=0.5, suffix='',
                 path=None):
    """mode: surface | outline | het_mask | fs_mask | heta (see module docstring). `path` overrides the asset path
    (roster masters live in MASTER_DIR/Roster with their own names, wuwa_roster_import.py)."""
    if spec.get('resolve') is False:
        return build_unlit_master(spec, textures, path or f"{MASTER_DIR}/M_Wuwa_{spec['name']}{suffix}")
    spec = with_vertex_blocks(normalize_wpo(spec))
    if 'custom_node_code' not in spec:
        # some generated specs (tools/shaderdiff/weapons/make_specs.py) omit it: same form as gen_wuwa_specs.custom_node_code
        outs = [i for i in spec['inputs'] if i['kind'] == 'output']
        args = ', '.join(i['name'] for i in spec['inputs'])
        spec = dict(spec, custom_node_code=''.join(f"{i.get('type', 'float')} {i['name']}; " for i in outs) +
                    f"FWuwaToonGBuffer G = {spec['entry']}({args});\nOutA = G.A; OutB = G.B; OutC = G.C; OutD = G.D;\n" +
                    ''.join(f"Out{i['name']} = {i['name']};\n" for i in outs) + 'return G.Emissive;')
    outline = mode == 'outline'
    blend = unreal.BlendMode.BLEND_OPAQUE
    if outline or het_cut or mode == 'het_mask' or (mode == 'surface' and spec['blend_mode'] == 'BLEND_Masked'):
        blend = unreal.BlendMode.BLEND_MASKED
    if mode == 'heta':
        blend = unreal.BlendMode.BLEND_TRANSLUCENT
    mat = W.new_material(path or f"{MASTER_DIR}/M_Wuwa_{spec['name']}{suffix}", blend=blend,
                         two_sided=bool(spec['two_sided']) or outline)
    if blend == unreal.BlendMode.BLEND_MASKED:
        clip = 0.5 if het_cut else float(spec.get('opacity_mask_clip_value', 0.5))
        mat.set_editor_property('opacity_mask_clip_value', clip)
    if mode == 'heta':
        # Kuro HETA is an opaque base-pass redraw at RenderQueue 300 on HET-stencil pixels; here a translucent copy whose
        # opacity is the HETA weight on cut pixels (0 elsewhere). Kuro's opaque redraw writes velocity like any base-pass
        # draw, so the copy outputs depth + motion vectors (UMaterial::bOutputTranslucentVelocity, "Output Depth and
        # Velocity"): the translucent velocity pass writes them where opacity >= the clip value, so TSR reprojects the
        # see-through bangs instead of ghosting them.
        mat.set_editor_property('output_translucent_velocity', True)
    b = Builder(mat, textures)
    wpo = wpo_node(b, spec, with_outputs=mode not in ('het_mask', 'fs_mask'))
    if wpo and mode in ('het_mask', 'fs_mask'):
        W.MEL.connect_material_property(wpo, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)

    if mode == 'fs_mask':
        # Face_FS capture material: geometry (bangs section + PositionOffset WPO) is all that matters; colour = mask.
        ps = W.custom(mat, -600, 0, 'return WuwaExtra_EncodeMask(Wuwa_CharacterID);', extra_inputs(b, ['Wuwa_CharacterID']),
                      CMOT['float3'], [EXTRA_INCLUDE.split('/Private/')[-1]], (), 'WuwaToonFSMask')
        W.MEL.connect_material_property(ps, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        W.compile_and_report(mat)
        return mat

    if mode == 'het_mask':
        extra = extra_inputs(b, ['Wuwa_CharacterID'], {'Wuwa_InvertHETMask': ('InvertHETMask', 0.0)})
        ps = b.custom(spec['inputs'], het_mask_code(spec), CMOT['float3'], [spec['include'], EXTRA_INCLUDE], {},
                      extra=extra, additional_outputs=[('OutOpacityMask', 'float')])
        W.MEL.connect_material_property(ps, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        W.MEL.connect_material_property(ps, 'OutOpacityMask', unreal.MaterialProperty.MP_OPACITY_MASK)
        W.compile_and_report(mat)
        return mat

    interp_nodes = interpolator_nodes(b, spec, wpo)

    extra_outputs = [(o, spec['outputs'][o]['type']) for o in spec['outputs'] if o not in ('Emissive', 'A', 'B', 'C', 'D')]
    additional = [(f'Out{o}', t) for o, t in extra_outputs]
    pre, extra = '', resolve_extra(b)
    if fs_receive:
        pre += FS_RECEIVE_CODE
        extra += extra_inputs(b, ['Wuwa_FSMask', 'Wuwa_FSEnable', 'Wuwa_FSDepthEps', 'Wuwa_CharacterID'],
                              {'Wuwa_FSSolidShadowStrength': ('FSSolidShadowStrength', fs_strength)})
    if het_cut:
        pre += HET_CUT_CODE
        additional.append(('OutHETKeep', 'float'))
    if mode == 'heta':
        pre += HETA_CODE
        additional.append(('OutOpacity', 'float'))
    if het_cut or mode == 'heta':
        extra += extra_inputs(b, ['Wuwa_HETMask', 'Wuwa_HETEnable', 'Wuwa_HETMaxBehind', 'Wuwa_CharacterID'] +
                              (['Wuwa_HETAOpacityScale'] if mode == 'heta' else []))
    includes = [spec['include'], '/Plugin/WuwaToon/Private/WuwaToonResolve.ush', '/Plugin/WuwaToon/Private/WuwaToonShadow.ush']
    if pre:
        includes.append(EXTRA_INCLUDE)
    ps = b.custom(spec['inputs'], pixel_code(spec, layout, pre), CMOT['float3'], includes, interp_nodes, extra=extra,
                  additional_outputs=additional)
    pins = {'EmissiveColor': (ps, '')}
    if wpo:
        pins['WorldPositionOffset'] = (wpo, '')
    if outline:
        # Inverted hull: Kuro culls front faces (pipeline state). Masked + back-face-only opacity also keeps the depth prepass honest.
        sign = W.node(mat, unreal.MaterialExpressionTwoSidedSign, -900, 600)
        neg = W.node(mat, unreal.MaterialExpressionMultiply, -750, 600, const_b=-1.0)
        W.MEL.connect_material_expressions(sign, '', neg, 'A')
        pins['OpacityMask'] = (neg, '')
    elif het_cut:
        pins['OpacityMask'] = (ps, 'OutHETKeep')
    elif mode == 'heta':
        pins['Opacity'] = (ps, 'OutOpacity')
    elif extra_outputs and blend == unreal.BlendMode.BLEND_MASKED:
        named = [o for o, _ in extra_outputs if o == 'OpacityMask']
        pins['OpacityMask'] = (ps, f'Out{(named or [extra_outputs[0][0]])[0]}')
    if mode == 'surface':
        for o, _ in extra_outputs:
            if spec['outputs'][o].get('material_pin') == 'PixelDepthOffset':
                pins['PixelDepthOffset'] = (ps, f'Out{o}')   # fur parallax (UseFurry): UE ApplyPixelDepthOffset
    connect_pins(mat, pins)
    W.compile_and_report(mat)
    return mat


MATERIAL_PROPERTY = {'EmissiveColor': unreal.MaterialProperty.MP_EMISSIVE_COLOR,
                     'WorldPositionOffset': unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET,
                     'OpacityMask': unreal.MaterialProperty.MP_OPACITY_MASK, 'Opacity': unreal.MaterialProperty.MP_OPACITY}


def connect_pins(mat, pins):
    """{material pin: (expression, output)}. MP_PixelDepthOffset is hidden from Python: a material that needs it routes
    every pin through Make Material Attributes (as occluder_material does)."""
    if 'PixelDepthOffset' not in pins:
        for pin, (expr, out) in pins.items():
            W.MEL.connect_material_property(expr, out, MATERIAL_PROPERTY[pin])
        return
    mat.set_editor_property('use_material_attributes', True)
    make = W.node(mat, unreal.MaterialExpressionMakeMaterialAttributes, -200, 0)
    for pin, (expr, out) in pins.items():
        if not W.MEL.connect_material_expressions(expr, out, make, pin):
            raise RuntimeError(f'{mat.get_name()}: Make Material Attributes pin {pin} not found')
    W.MEL.connect_material_property(make, '', unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)


def build_instance(name, info, master, folder, extra_scalars=None):
    """Create or update the MI in place (deleting an MI that the mesh / loaded components reference is unreliable)."""
    path = f'{folder}/{name}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mi = unreal.load_asset(path)
        W.MEL.clear_all_material_instance_parameters(mi)
    else:
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant,
                                                                     unreal.MaterialInstanceConstantFactoryNew())
    W.MEL.set_material_instance_parent(mi, master)
    for pname, p in info.get('parameters', {}).items():
        v = p.get('value')
        if v is None:
            continue
        if isinstance(v, list):
            W.MEL.set_material_instance_vector_parameter_value(mi, pname, unreal.LinearColor(*(list(map(float, v)) + [0, 0, 0, 1])[:4]))
        else:
            W.MEL.set_material_instance_scalar_parameter_value(mi, pname, float(v))
    for pname, v in (extra_scalars or {}).items():
        W.MEL.set_material_instance_scalar_parameter_value(mi, pname, float(v))
    for pname, t in info.get('textures', {}).items():
        if t.get('asset') and unreal.EditorAssetLibrary.does_asset_exist(t['asset']):
            W.MEL.set_material_instance_texture_parameter_value(mi, pname, unreal.load_asset(t['asset']))
        else:
            W.log(f"{name}: texture {pname} -> {t.get('asset')} missing; master default kept")
    W.MEL.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi, only_if_is_dirty=False)
    return mi


def invisible_material():
    """Slot not drawn: M_Empty base slots and every section a follower (outline / HETA / HET / FS) does not own.
    Additive unlit with zero emissive: writes no depth and adds nothing. The former zero-opacity masked version could
    still draw unlit black at the body's depth on the whole-mesh followers and win the depth tie (black parts in the
    editor, draw-order dependent; the same fix as Snowbreak's M_SectionDisabled)."""
    mat = W.new_material(f'{MASTER_DIR}/M_Wuwa_Hidden', blend=unreal.BlendMode.BLEND_ADDITIVE)
    zero = W.node(mat, unreal.MaterialExpressionConstant, -300, 0, r=0.0)
    W.MEL.connect_material_property(zero, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    W.compile_and_report(mat)
    return mat


def occluder_material():
    """HET capture depth occluder (HETPasses.md Â§4.3): black, pushed back by HETOccluderPDO so the coplanar Face_HET /
    Eye_HET surface wins while eyelid skin still hides the covered eyeball ("HET depth-tested against the 180 depth")."""
    mat = W.new_material(f'{MASTER_DIR}/M_Wuwa_CaptureOccluder')
    # MP_PixelDepthOffset is hidden from Python, so the outputs go through Make Material Attributes.
    mat.set_editor_property('use_material_attributes', True)
    make = W.node(mat, unreal.MaterialExpressionMakeMaterialAttributes, -200, 0)
    black = W.node(mat, unreal.MaterialExpressionConstant3Vector, -500, 0, constant=unreal.LinearColor(0, 0, 0, 0))
    pdo = W.node(mat, unreal.MaterialExpressionScalarParameter, -500, 150, parameter_name='HETOccluderPDO', default_value=0.05)
    if not W.MEL.connect_material_expressions(black, '', make, 'EmissiveColor'):
        raise RuntimeError('occluder: EmissiveColor pin not found')
    if not W.MEL.connect_material_expressions(pdo, '', make, 'PixelDepthOffset'):
        raise RuntimeError('occluder: PixelDepthOffset pin not found')
    W.MEL.connect_material_property(make, '', unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    W.compile_and_report(mat)
    return mat


# ------------------------------------------------------------------------------------------------ extra-material data
def load_extra(character):
    path = os.path.join(SPEC_DIR, f'{character}_ExtraMaterials.json')
    if not os.path.exists(path):
        raise RuntimeError(f'{path} missing: run tools/export_mesh_extra_materials.py --character {character}')
    return json.load(open(path))


def plan_modes(extra, mapping):
    """Master mode per spec, HETCut variants and FS receivers, all from the mesh's extra-material map."""
    slots = extra['slots']
    mi_types = {}                                        # MI -> set of slot types it is used as
    for s in extra['sections']:
        mi_types.setdefault(slots[s['material_index']]['material'], set()).add(1)
        for p in s['extra']:
            if not p['empty']:
                mi_types.setdefault(p['material'], set()).add(p['slot_type'])
    spec_mode = {}
    for mi, types in mi_types.items():
        if mi not in mapping:
            W.log(f'extra-material MI {mi} has no entry in the MI mapping; its pass is skipped')
            continue
        if len(types) > 1:
            raise RuntimeError(f'{mi} used as several slot types {types}')
        spec = mapping[mi]['spec']
        mode = {2: 'outline', 3: 'het_mask', 4: 'heta', 5: 'fs_mask'}.get(max(types), 'surface')
        if spec_mode.setdefault(spec, mode) != mode:
            raise RuntimeError(f'spec {spec} needed in modes {spec_mode[spec]} and {mode}')
    # Base MIs of sections that carry a HETA pass are cut where HET pixels lie behind them (Kuro 195 skip-HET).
    het_cut_mis = {slots[s['material_index']]['material'] for s in extra['sections']
                   if any(p['slot_type'] == 4 and not p['empty'] for p in s['extra'])}
    # FS receivers: surface MIs whose RenderQueue is below the FS pass (drawn before it).
    fs_queues = [slots[p['slot']]['render_queue'] for s in extra['sections'] for p in s['extra'] if p['slot_type'] == 5 and not p['empty']]
    fs_receive_specs = set()
    if fs_queues:
        fs_q = min(fs_queues)
        by_spec = {}
        for s in extra['sections']:
            base = slots[s['material_index']]
            if base['material'] in mapping:
                by_spec.setdefault(mapping[base['material']]['spec'], []).append(base['render_queue'] or 0)
        fs_receive_specs = {sp for sp, qs in by_spec.items() if spec_mode.get(sp) == 'surface' and max(qs) < fs_q}
    fs_strength = 0.5
    for s in extra['sections']:
        for p in s['extra']:
            if p['slot_type'] == 5 and p['material'] in mapping:
                v = mapping[p['material']]['parameters'].get('SolidShadowStrength', {}).get('value')
                fs_strength = float(v) if v is not None else fs_strength
    return spec_mode, het_cut_mis, fs_receive_specs, fs_strength


def write_mesh_data(mesh, extra, mapping, instances, hidden, occluder):
    """Surface MIs on the mesh slots + UWuwaToonExtraMaterialsUserData (sections / passes / gating) on the mesh asset."""
    slots = extra['slots']
    mats = list(mesh.get_editor_property('materials'))
    ue_slot_names = [str(sm.get_editor_property('material_slot_name')) for sm in mats]
    kuro_base = {}                                       # UE slot index -> Kuro section
    for s in extra['sections']:
        mi = slots[s['material_index']]['material']
        ue = ue_slot_names.index(mi) if mi in ue_slot_names else (s['material_index'] if s['material_index'] < len(mats) else -1)
        if ue < 0:
            W.log(f"section {s['section']} ({mi}) has no UE slot; skipped")
            continue
        kuro_base[ue] = s

    sections, occluder_slots = [], []
    het_queues = [slots[p['slot']]['render_queue'] for s in extra['sections'] for p in s['extra'] if p['slot_type'] == 3 and not p['empty']]
    het_q = min(het_queues) if het_queues else None
    for i, sm in enumerate(mats):
        s = kuro_base.get(i)
        surf = slots[s['material_index']]['material'] if s else None
        info = mapping.get(surf, {}) if surf else {}
        env = HIDDEN_UNLESS_ENV.get(info.get('spec'))
        if env and not os.environ.get(env):
            W.log(f'{surf}: kept hidden (set {env}=1 to show)')
            surf = None
        sm.set_editor_property('material_interface', instances.get(surf, hidden) if surf else hidden)
        mats[i] = sm
        if not s:
            continue
        base_q = slots[s['material_index']]['render_queue'] or 0
        if surf in instances and het_q is not None and base_q < het_q:
            occluder_slots.append(i)
        sec = unreal.WuwaToonSectionPasses()
        sec.set_editor_property('material_slot', i)
        sec.set_editor_property('kuro_base_slot_name', s['base_slot_name'])
        sec.set_editor_property('base_render_queue', int(base_q))
        passes = []
        for p in s['extra']:
            ps = unreal.WuwaToonExtraPass()
            ps.set_editor_property('type', getattr(unreal.WuwaToonSlotType, SLOT_TYPE_NAMES.get(p['slot_type'], 'UNKNOWN')))
            ps.set_editor_property('kuro_slot_name', p['slot_name'])
            ps.set_editor_property('kuro_material_index', int(p['slot']))
            ps.set_editor_property('kuro_material_name', p['material'] or '')
            ps.set_editor_property('empty', bool(p['empty']))
            ps.set_editor_property('max_kuro_lod', int(p['max_lod']))
            ps.set_editor_property('render_queue', int(slots[p['slot']]['render_queue'] or 0))
            ps.set_editor_property('material', None if p['empty'] else instances.get(p['material']))
            passes.append(ps)
            W.log(f"{mesh.get_name()} slot {i} {ue_slot_names[i]}: pass {p['slot_name']} ({p['slot_type_name']}) -> "
                  f"{'<empty: not drawn>' if p['empty'] else p['material']} LOD0-{p['max_lod']}")
        sec.set_editor_property('passes', passes)
        sections.append(sec)
        W.log(f'{mesh.get_name()} slot {i} {ue_slot_names[i]}: surface={surf}')
    mesh.set_editor_property('materials', mats)

    data = unreal.WuwaToonExtraMaterialsUserData.find_or_add_to_mesh(mesh)
    data.set_editor_property('sections', sections)
    data.set_editor_property('het_occluder_slots', occluder_slots)
    data.set_editor_property('het_occluder_material', occluder)
    data.set_editor_property('kuro_lod_distances', [float(l['kuro_lod_distance'] or 0.0) for l in extra['lods']])
    data.set_editor_property('use_kuro_lod_distance', bool(extra.get('use_kuro_lod_distance', True)))
    data.set_editor_property('head_bone_name', extra.get('head_bone') or 'Bip001Head')
    dd = extra.get('draw_distances_pc', {})
    data.set_editor_property('eye_transparent_draw_distance', float(dd.get('EyeTransparent', 800.0)))
    data.set_editor_property('face_shadow_mesh_draw_distance', float(dd.get('FaceShadowMesh', 800.0)))
    data.set_editor_property('outline_draw_distance', float(dd.get('Outline', 2000.0)))
    W.log(f'{mesh.get_name()}: extra-material data {len(sections)} sections, HET occluder slots {occluder_slots}, '
          f'LOD distances {[l["kuro_lod_distance"] for l in extra["lods"]]}, draw distances {dd}')
    unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)


def main():
    character = os.environ.get('WUWA_CHARACTER', 'Yangyang')
    mapping = json.load(open(os.path.join(SPEC_DIR, f'{character}_MIs.json')))['mis']
    extra = load_extra(character)
    textures = {p: t['asset'] for info in mapping.values() for p, t in info.get('textures', {}).items() if t.get('asset')}
    layout = W.mpc_layout()
    for param, rt in MASK_RTS.values():
        W.render_target(f'{RT_DIR}/{rt}', (1920, 1080), unreal.TextureRenderTargetFormat.RTF_RGBA32F,
                        unreal.LinearColor(0, 0, 0, 65504))

    spec_mode, het_cut_mis, fs_receive_specs, fs_strength = plan_modes(extra, mapping)
    W.log(f'modes {spec_mode}; HETCut base MIs {sorted(het_cut_mis)}; FS receivers {sorted(fs_receive_specs)} '
          f'(SolidShadowStrength {fs_strength})')
    het_cut_specs = {mapping[mi]['spec'] for mi in het_cut_mis if mi in mapping}

    masters, failed = {}, []
    # Only the specs this character's MIs use (Specs/ now also holds the roster families). WUWA_ONLY_SPECS=a.json,b.json
    # rebuilds just those masters; the others are reused as they are (MIs and mesh data are always rebuilt).
    used_specs = {info['spec'] for info in mapping.values()}
    only = set(filter(None, os.environ.get('WUWA_ONLY_SPECS', '').split(',')))
    for f in sorted(used_specs):
        spec = json.load(open(os.path.join(SPEC_DIR, f)))
        mode = spec_mode.get(f, 'outline' if spec['name'].startswith('Outline') else 'surface')
        variants = [('', False)] + ([('_HETCut', True)] if f in het_cut_specs else [])
        for suffix, cut in variants:
            existing = f"{MASTER_DIR}/M_Wuwa_{spec['name']}{suffix}"
            if only and f not in only and unreal.EditorAssetLibrary.does_asset_exist(existing):
                masters[f + suffix] = unreal.load_asset(existing)
                continue
            try:
                masters[f + suffix] = build_master(spec, textures, layout, mode, fs_receive=f in fs_receive_specs,
                                                   het_cut=cut, fs_strength=fs_strength, suffix=suffix)
                W.log(f'master {spec["name"]}{suffix}: mode {mode}{", FS receive" if f in fs_receive_specs else ""}'
                      f'{", HET cut" if cut else ""}')
            except Exception as e:  # keep going; report every failing family
                failed.append(f + suffix)
                W.log(f'FAILED master {f}{suffix}: {e}')

    folder = f'/Game/WuWa/Characters/{character}/Materials'
    instances = {}
    for name, info in mapping.items():
        key = info['spec'] + ('_HETCut' if name in het_cut_mis else '')
        if key in masters:
            # per-MI textures override the shared map used for master defaults
            extra_scalars = {'FSSolidShadowStrength': fs_strength} if info['spec'] in fs_receive_specs else None
            instances[name] = build_instance(name, info, masters[key], folder, extra_scalars)

    hidden = invisible_material()
    occluder = occluder_material()
    mesh = unreal.load_asset(os.environ.get('WUWA_MESH', MESH_PATHS[character]))
    write_mesh_data(mesh, extra, mapping, instances, hidden, occluder)
    W.log(f'generated {len(masters)} masters (+ hidden, occluder), {len(instances)} instances; failed masters: {failed}')


# WUWA_GENERATE_AS_LIBRARY=1: imported for its builders (wuwa_roster_import.py); the Yangyang generation does not run.
if not os.environ.get('WUWA_GENERATE_AS_LIBRARY'):
    main()
    if os.environ.get('WUWA_QUIT_AFTER'):
        unreal.SystemLibrary.quit_editor()
