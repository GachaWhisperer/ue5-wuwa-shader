using UnrealBuildTool;

public class WuwaToon : ModuleRules
{
	public WuwaToon(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "RenderCore", "RHI" });
		// Json: lighting presets read at runtime from Content/Python/data/kuro_toon_lighting_presets.json.
		PrivateDependencyModuleNames.AddRange(new string[] { "Projects", "Renderer", "Json" });
		if (Target.bBuildEditor)
		{
			// WITH_EDITOR only: current-frame view of the active level-editor viewport (FLevelEditorViewportClient).
			PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd", "Slate", "SlateCore" });
		}
	}
}
