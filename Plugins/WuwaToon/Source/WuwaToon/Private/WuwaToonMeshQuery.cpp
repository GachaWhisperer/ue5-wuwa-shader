#include "WuwaToonMeshQuery.h"

#include "Engine/SkeletalMesh.h"
#include "Rendering/SkeletalMeshRenderData.h"
#include "Rendering/SkeletalMeshLODRenderData.h"

static const FSkeletalMeshLODRenderData* WuwaLOD(const USkeletalMesh* Mesh, int32 LODIndex)
{
	if (!Mesh)
	{
		return nullptr;
	}
	const FSkeletalMeshRenderData* RD = const_cast<USkeletalMesh*>(Mesh)->GetResourceForRendering();
	return (RD && RD->LODRenderData.IsValidIndex(LODIndex)) ? &RD->LODRenderData[LODIndex] : nullptr;
}

int32 UWuwaToonMeshQuery::GetSkeletalMeshNumUVChannels(const USkeletalMesh* Mesh, int32 LODIndex)
{
	const FSkeletalMeshLODRenderData* LOD = WuwaLOD(Mesh, LODIndex);
	return LOD ? (int32)LOD->GetNumTexCoords() : -1;
}

int32 UWuwaToonMeshQuery::GetSkeletalMeshNumColorVertices(const USkeletalMesh* Mesh, int32 LODIndex)
{
	const FSkeletalMeshLODRenderData* LOD = WuwaLOD(Mesh, LODIndex);
	return LOD ? (int32)LOD->StaticVertexBuffers.ColorVertexBuffer.GetNumVertices() : -1;
}

int32 UWuwaToonMeshQuery::GetSkeletalMeshNumRenderLODs(const USkeletalMesh* Mesh)
{
	const FSkeletalMeshRenderData* RD = Mesh ? const_cast<USkeletalMesh*>(Mesh)->GetResourceForRendering() : nullptr;
	return RD ? RD->LODRenderData.Num() : -1;
}
