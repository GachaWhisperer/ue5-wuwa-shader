"""Headless: load a map, apply a recovered toon lighting preset to it (C++ AWuwaToonEnvironment::ApplyLightingPreset,
checked against the JSON by wuwa_validation_presets.check), save, and report the resulting values.
Env: WUWA_MAP (default validation map), WUWA_PRESET (default OutdoorDaylight)."""
import os

import unreal

import wuwa_validation_presets as P

MAP = os.environ.get('WUWA_MAP', '/Game/WuWa/Validation/Yangyang/L_YangyangShaderValidation')
NAME = os.environ.get('WUWA_PRESET', 'OutdoorDaylight')
world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
P.apply(NAME, world)
sun, sky, env = P._actors(world)
props = ['lighting_preset', 'ambient_a_near', 'ambient_a_far', 'ambient_b_near', 'ambient_b_far', 'rim_color', 'rim_direction',
         'rim_direction_from_main_light', 'ambient_params', 'ao_remap']
unreal.log('[WuwaPreset] ' + '; '.join(f'{k}={env.get_editor_property(k)}' for k in props))
unreal.log(f"[WuwaPreset] sun {sun.get_actor_label() if sun else None} colour {sun.light_component.get_light_color() if sun else None}; "
           f"sky {sky.get_actor_label() if sky else None} intensity {sky.light_component.get_editor_property('intensity') if sky else None}")
unreal.log(f'[WuwaPreset] JSON consistency check: {P.check(NAME, world) or "ok"}')
if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
    raise RuntimeError('save_map failed')
unreal.log(f'[WuwaPreset] saved {MAP}')
