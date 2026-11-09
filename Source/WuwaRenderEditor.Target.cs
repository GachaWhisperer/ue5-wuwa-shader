using UnrealBuildTool;

public class WuwaRenderEditorTarget : TargetRules
{
	public WuwaRenderEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("WuwaRender");
	}
}
