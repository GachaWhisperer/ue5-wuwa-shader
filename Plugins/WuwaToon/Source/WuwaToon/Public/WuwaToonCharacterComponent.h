#pragma once

#include "Components/ActorComponent.h"
#include "WuwaToonCharacterComponent.generated.h"

class USkeletalMeshComponent;

/**
 * Fills the CustomPrimitiveData slots that Kuro's character base passes read (Primitive rows 27..34
 * in the 4.26 layout). Slot roles are taken from the decompiled shaders:
 *   research/shaders/ToonFace.md §head frame, ToonCommon.md §CB2, ToonHair.md §light direction.
 * Which game system fills them is not recoverable from the shaders (packed executable), so slots whose
 * *source* is unknown are exposed as properties instead of guessed.
 */
UCLASS(ClassGroup = (WuwaToon), meta = (BlueprintSpawnableComponent))
class WUWATOON_API UWuwaToonCharacterComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UWuwaToonCharacterComponent();

	/** Mesh components whose materials read the toon CPD (body, face, hair, outline sections share one mesh). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TArray<TObjectPtr<USkeletalMeshComponent>> Meshes;

	/** Bone whose frame provides the face-SDF head axes (CPD 3/6/9 forward, 4/7/10 side, 23..25 position). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	FName HeadBone = TEXT("Bip001Head");

	/** Head-bone local axes that correspond to the character's face forward / right. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	FVector HeadForwardLocal = FVector(0, 1, 0);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	FVector HeadSideLocal = FVector(1, 0, 0);

	/** CPD0: yaw base in degrees added to LightOffset_Yaw for the fixed-angle VS light direction. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Light")
	float YawBaseDegrees = 0.f;

	/** CPD1: weight toward the fixed-angle VS light direction (saturated in the PS). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Light")
	float FixedDirectionWeight = 0.f;

	/** When true, CPD0 follows the actor yaw each frame (inferred role; see ToonHair.md unknowns). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Light")
	bool bYawFollowsActor = true;

	/** CPD22: pitch base in degrees (used when UseLightOffset_Pitch_DYN >= 0.5). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Light")
	float PitchBaseDegrees = 0.f;

	/** CPD11: face SDF forced flip (integer part bit 0) + threshold (fraction). CPD12: its weight. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Face")
	float SDFForcedFlipAndThreshold = 0.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Face")
	float SDFForcedWeight = 0.f;

	/** CPD13: toon local light anchor blend (0 = object position + 100z, 1 = head position CPD23..25). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Light")
	float LightAnchorBlend = 0.f;

	/** Stocking knee masks (Down material): CPD14..16 / CPD18..20 centres, CPD17 / CPD21 weights. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Stocking")
	FName LeftKneeBone = TEXT("Bip001_L_Knee_F");   // front-knee helper bone in Kuro rigs (choice inferred)

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Stocking")
	FName RightKneeBone = TEXT("Bip001_R_Knee_F");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Stocking")
	float KneeWeight = 1.f;

	/**
	 * CPD slot 35 (plugin-side; Kuro's CPD rows cover 0..31 and slot 26 is its wet factor): small per-character ID for the HET / FS mask captures.
	 * The capture-side mask materials write it into the spare G channel (G = R * ID, so the ratio survives capture
	 * pre-exposure); the HETCut bangs, the HETA copy and the FS receivers only react to mask texels whose ID equals their
	 * own CPD 35, so one character's HET mask / face-shadow shell never cuts or shadows another character.
	 * 0 = assigned by AWuwaToonEnvironment (unique per character in its Characters list, explicit IDs reserved first).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes", meta = (ClampMin = "0", ClampMax = "255"))
	int32 MaskID = 0;

	static constexpr int32 MaskIDSlot = 35;   // outside Kuro's CPD 0..31 (Kuro uses 26 for wet, research/roster/Port_CharV2_HairFace.md)

	/** MaskID if set, else the environment-assigned ID (0 when no environment manages this character). */
	UFUNCTION(BlueprintPure, Category = "WuwaToon|Extra Passes")
	int32 GetEffectiveMaskID() const { return MaskID > 0 ? MaskID : AssignedMaskID; }

	/** Called by AWuwaToonEnvironment; writes CPD 35 immediately when the effective ID changes. */
	void SetAssignedMaskID(int32 InID);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

protected:
	virtual void OnRegister() override;

private:
	void Push(USkeletalMeshComponent* Mesh) const;

	UPROPERTY(VisibleAnywhere, Transient, Category = "WuwaToon|Extra Passes")
	int32 AssignedMaskID = 0;
};
