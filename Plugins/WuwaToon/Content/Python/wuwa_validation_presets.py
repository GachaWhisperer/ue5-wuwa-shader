"""Lighting presets for the Yangyang validation map, driven by values recovered from the game.

Toon character lighting values come from KuroWeatherDataAsset CharacterSetting groups (via BP_GlobalGI.UpdateCharacterGI,
CustomCharacterLightingIntensity = 1), extracted to data/kuro_toon_lighting_presets.json - see
research/shaders/ToonLightingData.md. Fields an asset does not override use native defaults that are not recoverable;
for those the plugin keeps its documented neutral choice (near colours = far colours so the unrecovered depth-gradient
distance has no effect; AmbientParams.y GlobalShadowIntensity = 1; rim width/tint = 1).

One source of truth: the JSON (presets + scenario aliases). The values are applied by the C++
AWuwaToonEnvironment::ApplyLightingPreset (also behind the LightingPreset dropdown in the editor); this module calls it
and independently re-derives the expected values from the same JSON (`expected`, `check`) so the two stay consistent.

Usage in the editor Python console:
    import wuwa_validation_presets as P; P.list_presets(); P.apply('OpenWorld_Suibo_Day_12h')
    P.rotate_light(step_degrees=15)   # one-shot rotating light-direction test (continuous: env ValidationLightRotation...)
The UE sun only drives the toon shadow capture and the base-pass light direction; toon colours come from the preset.
"""
import json
import os

import unreal

_DATA = json.load(open(os.path.join(os.path.dirname(__file__), 'data', 'kuro_toon_lighting_presets.json'), encoding='utf-8'))
PRESETS = _DATA['presets']
# Scenario name (master prompt section 8) -> recovered preset; day/indoor/night/warm/cool map to presets whose lit and
# ambient colours are both overridden by the asset.
SCENARIOS = _DATA['scenarios']
CUSTOM = 'Custom'


def _actors(world=None):
    if world is not None:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    else:
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    find = lambda cls: next((a for a in actors if isinstance(a, cls)), None)
    env = find(unreal.WuwaToonEnvironment)
    # Same choice as the C++ side: the environment's MainLight / SkyLight, else the first one in the world.
    sun = (env.get_editor_property('main_light') if env else None) or find(unreal.DirectionalLight)
    sky = (env.get_editor_property('sky_light') if env else None) or find(unreal.SkyLight)
    return sun, sky, env


def list_presets():
    for name, p in PRESETS.items():
        unreal.log(f"[WuwaPreset] {name}: {p.get('note', '')}  ({p.get('source', '')})")
    for alias, target in SCENARIOS.items():
        unreal.log(f'[WuwaPreset] scenario {alias} -> {target}')


def expected(name):
    """Values a preset sets: {environment property: value, 'sun_color': [...], 'sky_intensity': x}. Absent fields are kept."""
    if name == CUSTOM:
        return {}
    p = PRESETS[SCENARIOS.get(name, name)]
    lc = lambda c: (list(c) + [0.0])[:4]
    out = {}
    if p.get('AmbientA_Far'):
        out['ambient_a_far'] = lc(p['AmbientA_Far'])
        out['ambient_a_near'] = lc(p.get('AmbientA_Near', p['AmbientA_Far']))
    if p.get('AmbientB_Far'):
        out['ambient_b_far'] = lc(p['AmbientB_Far'])
        out['ambient_b_near'] = lc(p.get('AmbientB_Near', p['AmbientB_Far']))
    if 'MainLightColor' in p:          # View[301] = CharacterRimColor
        out['rim_color'] = lc(p['MainLightColor'])
    if 'MainLightDir' in p:            # View[302] = KuroCharRimDir
        out['rim_direction'] = list(p['MainLightDir'])
        out['rim_direction_from_main_light'] = False
    for axis, v in p.get('AmbientParamsPartial', {}).items():
        out[f'ambient_params.{axis}'] = float(v)
    if 'AORemap' in p:
        out['ao_remap'] = list(p['AORemap'])
    rel = p.get('related_inputs', {})
    if 'MainLightTint' in rel:
        out['sun_color'] = lc(rel['MainLightTint'])
    if 'SkyLightIntensity' in rel:
        out['sky_intensity'] = float(rel['SkyLightIntensity'])
    return out


def _vals(v):
    if isinstance(v, unreal.LinearColor):
        return [v.r, v.g, v.b, v.a]
    if isinstance(v, unreal.Vector):
        return [v.x, v.y, v.z]
    return v


def check(name, world=None, tol=1e-4):
    """Compare the actors' current values with expected(name); returns a list of mismatch strings (empty = consistent)."""
    sun, sky, env = _actors(world)
    bad = []
    for key, want in expected(name).items():
        if key == 'sun_color':
            got, t = _vals(sun.light_component.get_light_color()) if sun else None, 0.01   # stored as 8-bit sRGB FColor
            got, want = (got[:3] if got else None), want[:3]
        elif key == 'sky_intensity':
            got, t = (sky.light_component.get_editor_property('intensity') if sky else None), tol
        elif key.startswith('ambient_params.'):
            got, t = getattr(env.get_editor_property('ambient_params'), key.split('.')[1]), tol
        else:
            got, t = _vals(env.get_editor_property(key)), tol
        same = (got == want) if isinstance(want, bool) else (
            got is not None and all(abs(a - b) <= t for a, b in zip(got if isinstance(got, list) else [got],
                                                                     want if isinstance(want, list) else [want])))
        if not same:
            bad.append(f'{key}: got {got}, expected {want}')
    return bad


def apply(name, world=None):
    """Apply through AWuwaToonEnvironment::ApplyLightingPreset (same JSON), then verify against expected(name)."""
    sun, sky, env = _actors(world)
    if env is None:
        raise RuntimeError('no WuwaToonEnvironment in the world')
    if not env.apply_lighting_preset(name):
        raise RuntimeError(f'ApplyLightingPreset({name}) failed (unknown preset or JSON not found)')
    bad = check(name, world)
    if bad:
        raise RuntimeError(f'[WuwaPreset] C++ preset {name} disagrees with the JSON: ' + '; '.join(bad))
    p = PRESETS.get(SCENARIOS.get(name, name), {})
    unreal.log(f"[WuwaPreset] applied {name} <- {p.get('source', 'custom')} (C++ ApplyLightingPreset, checked against JSON: "
               f'{len(expected(name))} fields)')


def rotate_light(step_degrees=15.0):
    sun, _, _ = _actors()
    r = sun.get_actor_rotation()
    sun.set_actor_rotation(unreal.Rotator(roll=r.roll, pitch=r.pitch, yaw=r.yaw + step_degrees), False)
