using UnrealBuildTool;

public class WuwaRenderTarget : TargetRules
{
	public WuwaRenderTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WuwaRender");
	}
}
