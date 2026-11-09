#pragma once

#include "Modules/ModuleInterface.h"

// Maps the plugin Shaders directory to the virtual path /Plugin/WuwaToon so that material
// Custom nodes and global shaders can include the reconstructed Kuro toon library.
class FWuwaToonModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
