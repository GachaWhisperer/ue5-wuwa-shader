#include "WuwaToonExtraMaterials.h"

#include "Engine/SkeletalMesh.h"

int32 UWuwaToonExtraMaterialsUserData::KuroLODForDistance(float Distance) const
{
	int32 LOD = 0;
	if (bUseKuroLODDistance)
	{
		for (int32 I = 1; I < KuroLODDistances.Num(); ++I)
		{
			if (Distance >= KuroLODDistances[I])
			{
				LOD = I;
			}
		}
	}
	return LOD;
}

UWuwaToonExtraMaterialsUserData* UWuwaToonExtraMaterialsUserData::FindOnMesh(const USkeletalMesh* Mesh)
{
	return Mesh ? const_cast<USkeletalMesh*>(Mesh)->GetAssetUserData<UWuwaToonExtraMaterialsUserData>() : nullptr;
}

UWuwaToonExtraMaterialsUserData* UWuwaToonExtraMaterialsUserData::FindOrAddToMesh(USkeletalMesh* Mesh)
{
	if (!Mesh)
	{
		return nullptr;
	}
	Mesh->Modify();
	UWuwaToonExtraMaterialsUserData* Data = FindOnMesh(Mesh);
	if (!Data)
	{
		Data = NewObject<UWuwaToonExtraMaterialsUserData>(Mesh, NAME_None, RF_Public | RF_Transactional);
		Mesh->AddAssetUserData(Data);
	}
	Data->Modify();
	Mesh->MarkPackageDirty();
	return Data;
}
