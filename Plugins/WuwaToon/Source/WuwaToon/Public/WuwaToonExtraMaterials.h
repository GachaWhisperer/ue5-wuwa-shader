#pragma once

#include "Engine/AssetUserData.h"
#include "WuwaToonExtraMaterials.generated.h"

class UMaterialInterface;
class USkeletalMesh;

/**
 * Kuro material slot type. Numbering follows Game/Render/Config/RenderConfig.js GetMaterialSlotType (slot-name prefix
 * MI_ 1, OL_ 2, HET_ 3, HETA_ 4, FS_ 5); labels follow the exe enum EKuroCharSlotType (research/shaders/HETPasses.md §1.2).
 */
UENUM(BlueprintType)
enum class EWuwaToonSlotType : uint8
{
	Unknown = 0,
	Body = 1,                // MI_   surface
	Outline = 2,             // OL_   inverted hull
	EyeMask = 3,             // HET_  StencilOnlyWrite (eye / brow mask)
	HairEyeTransparent = 4,  // HETA_ see-through bangs redraw
	FaceShadow = 5,          // FS_   face shadow mesh (A.z only)
};

/** One extra material drawn on a section's geometry (Kuro LODSectionExtraMaterialMap entry). */
USTRUCT(BlueprintType)
struct FWuwaToonExtraPass
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") EWuwaToonSlotType Type = EWuwaToonSlotType::Unknown;
	/** Kuro SkeletalMaterials slot name / index of the extra material (e.g. HET_Eye, 17). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") FName KuroSlotName;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") int32 KuroMaterialIndex = INDEX_NONE;
	/** Kuro MI name (for reports). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") FName KuroMaterialName;
	/** UE material emulating the pass; null = nothing to draw (e.g. Kuro M_Empty / MATUSAGE_Empty, or not generated). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") TObjectPtr<UMaterialInterface> Material;
	/** True when the Kuro MI's chain ends in a bUsedWithEmpty material (slot intentionally not drawn). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") bool bEmpty = false;
	/** Highest Kuro LOD whose LODSectionExtraMaterialMap still lists this pass (HET/HETA/FS: 3, outlines: 4). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") int32 MaxKuroLOD = 0;
	/** Kuro RenderQueue resolved through the MI chain (base-pass sort key [I]). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") int32 RenderQueue = 0;
};

/** The extra passes of one mesh section, keyed by the UE material slot that carries the section's base material. */
USTRUCT(BlueprintType)
struct FWuwaToonSectionPasses
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") int32 MaterialSlot = INDEX_NONE;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") FName KuroBaseSlotName;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") int32 BaseRenderQueue = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") TArray<FWuwaToonExtraPass> Passes;
};

/**
 * Kuro per-section extra materials of a character mesh, stored on the UE skeletal mesh as asset user data (Kuro keeps
 * them on the mesh too: FSkeletalMeshLODInfo::LODSectionExtraMaterialMap). Written by Content/Python/
 * wuwa_generate_materials.py from Specs/<Character>_ExtraMaterials.json (tools/export_mesh_extra_materials.py);
 * AWuwaToonCharacterActor builds its outline / HET / HETA / face-shadow components from it.
 */
UCLASS(BlueprintType, meta = (DisplayName = "WuwaToon Extra Materials"))
class WUWATOON_API UWuwaToonExtraMaterialsUserData : public UAssetUserData
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TArray<FWuwaToonSectionPasses> Sections;

	/** UE slots drawn into the HET capture as depth occluders (base RenderQueue below the HET pass: "HET is depth
	 *  tested against the 180 depth", HETPasses.md §2.2). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TArray<int32> HETOccluderSlots;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TObjectPtr<UMaterialInterface> HETOccluderMaterial;

	/** Kuro LODInfo[].KuroLODDistance (cm, bUseKuroLODDistance) used to emulate "LOD4 keeps only outlines". */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TArray<float> KuroLODDistances;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	bool bUseKuroLODDistance = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	FName HeadBoneName = TEXT("Bip001Head");

	/** r.Kuro.ToonEyeTransparentDrawDistancePc (HET + HETA), r.Kuro.ToonFaceShadowMeshDrawDistancePc, r.Kuro.ToonOutlineDrawDistancePc. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") float EyeTransparentDrawDistance = 800.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") float FaceShadowMeshDrawDistance = 800.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon") float OutlineDrawDistance = 2000.f;

	/** Kuro LOD for a camera distance (KuroLODDistance thresholds; 0 when disabled / no data). */
	int32 KuroLODForDistance(float Distance) const;

	/** Finds the user data on a mesh, or creates and attaches an empty one (editor scripting; marks the mesh dirty). */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon")
	static UWuwaToonExtraMaterialsUserData* FindOrAddToMesh(USkeletalMesh* Mesh);

	UFUNCTION(BlueprintCallable, BlueprintPure, Category = "WuwaToon")
	static UWuwaToonExtraMaterialsUserData* FindOnMesh(const USkeletalMesh* Mesh);
};
