"""Compile check: a material whose Custom node includes WuwaToonResolve.ush and runs the full resolve on a
synthetic toon GBuffer, with MPC-backed toon parameters and light records. Verifies the plugin shader library
compiles inside UE 5.8's material pipeline (stricter than standalone dxc)."""
import unreal

import wuwa_material_lib as W

CODE = r'''
FWuwaToonGBuffer G;
G.Emissive = 0;
G.A = float4(WuwaOctEncode(normalize(N)), ShadowFactor, 0.99999);
G.B = float4(sqrt(float3(0.6, 0.5, 0.5)), WuwaPackShadingModel(12, 1));
G.C = float4(BaseColor, 1);
G.D = float4(0.03, 240.0 / 255.0, 0, 0);
G = WuwaToonGBufferStore(G);

FWuwaToonAmbientParams P;
P.AOStrength = AOStrength;          P.GIEnable = GIEnable.xy;           P.AmbientParams = AmbientParams.xyz;
P.AmbientA_Far = AmbA_Far.rgb;      P.AmbientB_Far = AmbB_Far.rgb;      P.MainLightColor = LightColor.rgb;
P.MainLightDir = LightDir.xyz;      P.AORemap = AORemap.xyz;            P.DepthGradient = DepthGradient.xy;
P.AmbientB_Near = AmbB_Near.rgb;    P.AmbientA_Near = AmbA_Near.rgb;

FWuwaToonResolveInputs I;
I.Depth = Depth;  I.WorldPos = WorldPos;  I.V = normalize(CameraVec);
I.WorldToView = (float3x3)ResolvedView.TranslatedWorldToView;
I.ViewportUV = ViewportUV;  I.FOVRelated = 2.0 * atan(1.0 / ResolvedView.ViewToClip[1][1]);
I.ShadowMaskXZ = WuwaToonShadowMask(ShadowDepth, ShadowDepthSampler, WorldPos, ShadowOrigin, ShadowForward,
	ShadowRight.xyz, ShadowUp.xyz, 1.0 / 1024.0);
I.Exposure = Exposure;  I.IndirectDiffuse = 0;  I.GITint = 0;  I.PassGIEnable = false;
I.RimWidthScale = RimPass.x;  I.RimTint = RimTint.rgb;
FWuwaToonResolveState St = WuwaToonResolveBegin(G, P, I);
%LIGHTS%
return WuwaToonResolveEnd(St, P, I, ToonDepth, ToonDepthSampler);
'''


def main():
    mat = W.new_material('/Game/WuWa/Materials/Tests/M_WuwaToon_ResolveTest')
    layout = W.mpc_layout()
    x = -1400
    inputs = []

    def add(name, expr, out=''):
        inputs.append((name, expr, out))

    add('N', W.node(mat, unreal.MaterialExpressionVertexNormalWS, x, 0))
    add('ShadowFactor', W.node(mat, unreal.MaterialExpressionScalarParameter, x, 60, parameter_name='ShadowFactor', default_value=1.0))
    add('BaseColor', W.node(mat, unreal.MaterialExpressionVectorParameter, x, 120, parameter_name='BaseColor',
                            default_value=unreal.LinearColor(0.9, 0.8, 0.75, 1)))
    for i, (pin, name) in enumerate([('AOStrength', 'ToonAOStrength'), ('GIEnable', 'ToonGIEnable'), ('AmbientParams', 'ToonAmbientParams'),
                                     ('AmbA_Far', 'ToonAmbientA_Far'), ('AmbB_Far', 'ToonAmbientB_Far'), ('LightColor', 'ToonMainLightColor'),
                                     ('LightDir', 'ToonMainLightDir'), ('AORemap', 'ToonAORemap'), ('DepthGradient', 'ToonDepthGradient'),
                                     ('AmbB_Near', 'ToonAmbientB_Near'), ('AmbA_Near', 'ToonAmbientA_Near'), ('RimPass', 'ToonRimPass'),
                                     ('RimTint', 'ToonRimTint'), ('ShadowOrigin', 'ToonShadowOrigin'), ('ShadowForward', 'ToonShadowForward'),
                                     ('ShadowRight', 'ToonShadowRight'), ('ShadowUp', 'ToonShadowUp')]):
        add(pin, W.mpc_param(mat, x, 200 + i * 60, name))
    add('Depth', W.node(mat, unreal.MaterialExpressionPixelDepth, x, 1300))
    add('WorldPos', W.node(mat, unreal.MaterialExpressionWorldPosition, x, 1360))
    add('CameraVec', W.node(mat, unreal.MaterialExpressionCameraVectorWS, x, 1420))
    add('ViewportUV', W.node(mat, unreal.MaterialExpressionScreenPosition, x, 1480), 'ViewportUV')
    add('Exposure', W.node(mat, unreal.MaterialExpressionEyeAdaptation, x, 1540))
    add('ToonDepth', W.node(mat, unreal.MaterialExpressionTextureObjectParameter, x, 1600, parameter_name='ToonDepth'))
    add('ShadowDepth', W.node(mat, unreal.MaterialExpressionTextureObjectParameter, x, 1660, parameter_name='ShadowDepth'))

    c = W.custom(mat, -400, 400, CODE.replace('%LIGHTS%', W.light_loop_code(layout)), inputs,
                 unreal.CustomMaterialOutputType.CMOT_FLOAT3, ['WuwaToonResolve.ush'], (), 'WuwaToonResolve')
    W.MEL.connect_material_property(c, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    W.compile_and_report(mat)


main()

# When launched in a full (offscreen) editor for a compile check, exit afterwards.
import os
if os.environ.get('WUWA_QUIT_AFTER'):
    unreal.SystemLibrary.quit_editor()
