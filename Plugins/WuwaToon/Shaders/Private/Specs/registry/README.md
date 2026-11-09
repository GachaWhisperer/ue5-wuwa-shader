# Family registry (contract between shader porting and the roster importer)

One JSON file per root Material (top of an MI parent chain), e.g. `M_Char_Com.json`:

```json
{
  "root_material": "M_Char_Com",
  "variants": [
    {
      "spec": "ToonCommon_BodyUp.json",
      "match": {"base_pass_ps_hash": ["<archive hash of TBasePassPSFNoLightMapPolicy on FGPUSkinPassthroughVertexFactory>", "..."],
                "static_switches": {"UseStocking": false}},
      "verified": "research/validation/ShaderDiff_*.md#section"
    }
  ]
}
```

A root material's variants may be split across several files (e.g. `M_CharV2_Com.json` and
`M_CharV2_Com_HairFace.json`) so porting agents never edit the same file; the importer merges every registry file
by its `root_material` field.

Matching order used by the importer (owned by the roster import pipeline):
1. `base_pass_ps_hash` — the MI's own SM5 shader map, base-pass PS archive hash (authoritative: identical hash = identical compiled code).
2. otherwise `static_switches` subset match on the MI's merged static switch values.
An MI that matches no variant gets the fallback material `M_Wuwa_Unported` and import_status "material_unported:<root>".

Porting agents own the .ush files, `Specs/*.json` specs and the registry entries for their families. The importer
(tools/gen_wuwa_specs.py, Content/Python/wuwa_generate_materials.py, wuwa_import_character.py) only reads the registry.
