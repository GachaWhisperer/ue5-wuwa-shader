#include "WuwaToonModule.h"

#include "WuwaToonViewTracker.h"

#include "Interfaces/IPluginManager.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Paths.h"
#include "SceneViewExtension.h"
#include "ShaderCore.h"

static TSharedPtr<FWuwaToonViewTracker, ESPMode::ThreadSafe> GWuwaToonViewTracker;

void FWuwaToonModule::StartupModule()
{
	const FString ShaderDir = FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("WuwaToon"))->GetBaseDir(), TEXT("Shaders"));
	AddShaderSourceDirectoryMapping(TEXT("/Plugin/WuwaToon"), ShaderDir);

	// Scene view extensions need the engine to exist; this module loads at PostConfigInit for the shader mapping.
	FCoreDelegates::GetOnPostEngineInit().AddLambda([]()
	{
		GWuwaToonViewTracker = FSceneViewExtensions::NewExtension<FWuwaToonViewTracker>();
	});
}

void FWuwaToonModule::ShutdownModule()
{
	GWuwaToonViewTracker.Reset();
}

IMPLEMENT_MODULE(FWuwaToonModule, WuwaToon)
