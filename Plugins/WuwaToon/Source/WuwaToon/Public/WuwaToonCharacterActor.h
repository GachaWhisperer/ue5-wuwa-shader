#pragma once

#include "Animation/SkeletalMeshActor.h"
#include "WuwaToonCharacterActor.generated.h"

class UWuwaToonCharacterComponent;
class UWuwaToonExtraMaterialsUserData;
class UMaterialInterface;
class UPrimitiveComponent;

/**
 * Skeletal mesh actor pre-configured for WuwaToon materials (fills Kuro CustomPrimitiveData each frame).
 *
 * Kuro draws extra materials on each mesh section (FSkeletalMeshLODInfo::LODSectionExtraMaterialMap; research/shaders/
 * HETPasses.md §1). The plugin reads that map from the mesh's UWuwaToonExtraMaterialsUserData (generated from the cooked
 * mesh) and reproduces each pass type with a follower mesh (same asset, leader-posed to the body):
 *   OutlineMesh     OL_   inverted-hull outline (main view)
 *   HETMaskMesh     HET_  eye / brow mask        (scene-capture only -> RT_WuwaHETMask)
 *   HETOccluderMesh       depth occluders for the HET capture (slots drawn before the HET pass)
 *   FaceShadowMesh  FS_   shifted bangs shell    (scene-capture only -> RT_WuwaFaceShadowMask)
 *   HETAMesh        HETA_ see-through bangs      (main view, translucent)
 * Slots without a pass of a component's type get M_Wuwa_Hidden; a component with no pass at all is not rendered.
 * Gating as Kuro: HET/HETA within EyeTransparentDrawDistance, FS within FaceShadowMeshDrawDistance, outlines within
 * OutlineDrawDistance, and each pass only up to the last Kuro LOD that lists it (LOD from KuroLODDistance).
 */
UCLASS(ClassGroup = (WuwaToon))
class WUWATOON_API AWuwaToonCharacterActor : public ASkeletalMeshActor
{
	GENERATED_BODY()

public:
	AWuwaToonCharacterActor(const FObjectInitializer& ObjectInitializer);

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon")
	TObjectPtr<UWuwaToonCharacterComponent> ToonCharacter;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USkeletalMeshComponent> OutlineMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USkeletalMeshComponent> HETMaskMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USkeletalMeshComponent> HETOccluderMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USkeletalMeshComponent> FaceShadowMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USkeletalMeshComponent> HETAMesh;

	/** Master switches (debug); the per-pass data comes from the mesh. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") bool bEnableOutline = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") bool bEnableEyeTransparent = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") bool bEnableFaceShadowMesh = true;

	/** Distance (cm) from the tracked main view to the head bone, and the emulated Kuro LOD, as of the last tick. */
	UPROPERTY(VisibleAnywhere, Transient, Category = "WuwaToon|Extra Passes") float ViewDistance = 0.f;
	UPROPERTY(VisibleAnywhere, Transient, Category = "WuwaToon|Extra Passes") int32 KuroLOD = 0;

	virtual void OnConstruction(const FTransform& Transform) override;
	virtual void Tick(float DeltaSeconds) override;
	virtual bool ShouldTickIfViewportsOnly() const override { return true; }

	/** Components the toon depth / toon shadow captures must skip (capture-only masks and the translucent HETA copy). */
	void GetExtraPassComponents(TArray<UPrimitiveComponent*>& Out) const;

	/** HET mask + occluder components currently active (empty when gated off). */
	void GetActiveHETCaptureComponents(TArray<UPrimitiveComponent*>& Out) const;

	/** Face-shadow shell component when active. */
	void GetActiveFaceShadowCaptureComponents(TArray<UPrimitiveComponent*>& Out) const;

	/** Face-shadow shell when active (it also casts into the light-space toon shadow capture), else null. */
	UPrimitiveComponent* GetActiveFaceShadowCaster() const;

private:
	void ConfigureFollower(USkeletalMeshComponent* Follower, bool bCaptureOnly) const;
	void AssignExtraMaterials();
	void UpdateGating();
	void SyncFollowerMorphs();

	/** Max Kuro LOD that still draws each component's passes (-1 = component has no pass). */
	int32 MaxLODOutline = -1, MaxLODHET = -1, MaxLODHETA = -1, MaxLODFaceShadow = -1;
	float EyeTransparentDrawDistance = 800.f, FaceShadowMeshDrawDistance = 800.f, OutlineDrawDistance = 2000.f;
	bool bActiveHET = false, bActiveFaceShadow = false;
	/** Set once AssignExtraMaterials ran in this process (cooked placed actors do not run construction scripts). */
	bool bExtraConfigured = false;
};
