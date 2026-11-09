#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "WuwaToonMeshQuery.generated.h"

class USkeletalMesh;

/**
 * Read-only stream queries for the roster import verification (tools/roster, Content/Python/wuwa_roster_verify.py):
 * UE's Python API exposes morph targets and the vertex-colour flag, but not the number of UV channels of a skeletal
 * mesh. Values come from the built render data of the given LOD (what the materials actually sample).
 */
UCLASS()
class WUWATOON_API UWuwaToonMeshQuery : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** Number of texture coordinate channels in the render data of LOD LODIndex (-1 if unavailable). */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon|Roster")
	static int32 GetSkeletalMeshNumUVChannels(const USkeletalMesh* Mesh, int32 LODIndex = 0);

	/** Vertex count of the colour vertex buffer of LOD LODIndex (0 = no vertex colours in the render data). */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon|Roster")
	static int32 GetSkeletalMeshNumColorVertices(const USkeletalMesh* Mesh, int32 LODIndex = 0);

	/** Number of render LODs (-1 if no render data). */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon|Roster")
	static int32 GetSkeletalMeshNumRenderLODs(const USkeletalMesh* Mesh);
};
