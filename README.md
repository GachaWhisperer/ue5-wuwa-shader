# UE5 WuWa Shader

An Unreal Engine 5.8 reconstruction of the *Wuthering Waves* toon rendering, which ships on Kuro's UE 4.26 fork. Character body, face, hair, eye, outline, glass, crystal, fur, special and weapon/FX shaders are transcribed from the game's compiled base-pass shaders and ported to stock Unreal, along with toon shadows and screen-space passes.

This repository contains the **Unreal project only**: the shader library, the WuwaToon plugin and the generated master materials. It contains **no game assets**. Characters, skins, weapons and the game's shared textures are not distributed, so you need to import your own.

## What's in it

| Path | Contents |
| --- | --- |
| `Plugins/WuwaToon/Shaders/Private/*.ush` | The shader library (`/Plugin/WuwaToon`): shared base-pass helpers, `ToonCommon` / V2 body, face, hair, eye, outline (A/B/C, ghost, lite, translucent), glass and blur glass, crystal, star / XingHen, special cloth / diamond / starry, monster, motor, weapon and weapon FX, water FX, Zani fire hair, the G-buffer, toon shadow and resolve passes. |
| `Plugins/WuwaToon/Shaders/Private/Specs/` | One JSON spec per material family (entry point, inputs, outputs, blend mode). `registry/` maps the game's root materials to those families (see `Specs/registry/README.md`). |
| `Plugins/WuwaToon/Source/` | `AWuwaToonEnvironment` (toon light, ambient and per-object shadow setup), `AWuwaToonCharacterActor` / `UWuwaToonCharacterComponent`, the extra-material user data, `UWuwaToonMeshQuery`, and a view tracker scene extension. |
| `Plugins/WuwaToon/Content/Python/` | Editor scripts: generate masters from the specs, create the MPC, import characters and rosters, build validation maps, apply lighting presets. |
| `Content/WuWa/Materials/` | Generated master materials (`M_Wuwa_*`, `Masters/Roster/M_WuwaRoster_*`) and the material parameter collection. |
| `Content/WuWa/Validation/Yangyang/RT_*` | Toon depth, toon shadow, face shadow mask and HET mask render targets used by the masters. |

## Requirements

- Unreal Engine **5.8**
- Windows, DirectX 12
- Visual Studio 2022 with the *Game development with C++* workload, to build the plugin

## Getting started

1. Clone the repo.
2. Right-click `WuwaRender.uproject` → **Generate Visual Studio project files**, then build `WuwaRenderEditor` (Development Editor, Win64). You can also just open the `.uproject` and let Unreal compile the modules.
3. Open the project. Materials compile against `/Plugin/WuwaToon`.

Without character assets there is nothing to render. Imported characters are expected under `Content/WuWa/Characters/` (and `Skins/`, `Weapons/`), and the game's shared ramp / noise textures under `Content/WuWa/Shared/`. All of these are git-ignored.

## Notes

- A few master materials use a character or weapon texture as their default parameter value. Those textures are not included, so Unreal reports them as missing references until you provide your own.
- The character import scripts expect per-character material dumps (`Specs/Roster/`, `*_MIs.json`) produced from your own extraction. Those dumps are not included.
- Shader comments mention research files (`evidence/...`, `research/...`, `tools/...`) from the private workspace this project was built in. Those files are not part of this repository.

## Disclaimer

This is an unofficial fan and educational project, not affiliated with or endorsed by Kuro Games. *Wuthering Waves* and all related names are trademarks of their respective owners. No game assets are included in this repository.
