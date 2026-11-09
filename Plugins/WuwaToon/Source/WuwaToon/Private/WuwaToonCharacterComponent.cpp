#include "WuwaToonCharacterComponent.h"

#include "Components/SkeletalMeshComponent.h"
#include "GameFramework/Actor.h"

UWuwaToonCharacterComponent::UWuwaToonCharacterComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PostUpdateWork;   // after animation, so the head frame is current
	bTickInEditor = true;
}

void UWuwaToonCharacterComponent::OnRegister()
{
	Super::OnRegister();
	if (Meshes.IsEmpty() && GetOwner())
	{
		TArray<USkeletalMeshComponent*> Found;
		GetOwner()->GetComponents(Found);
		Meshes.Append(Found);
	}
}

void UWuwaToonCharacterComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	for (USkeletalMeshComponent* Mesh : Meshes)
	{
		if (Mesh)
		{
			Push(Mesh);
		}
	}
}

void UWuwaToonCharacterComponent::SetAssignedMaskID(int32 InID)
{
	const int32 Before = GetEffectiveMaskID();
	AssignedMaskID = FMath::Clamp(InID, 0, 255);
	if (GetEffectiveMaskID() != Before)
	{
		for (USkeletalMeshComponent* Mesh : Meshes)
		{
			if (Mesh)
			{
				Mesh->SetCustomPrimitiveDataFloat(MaskIDSlot, float(GetEffectiveMaskID()));
			}
		}
	}
}

void UWuwaToonCharacterComponent::Push(USkeletalMeshComponent* Mesh) const
{
	TArray<float> Data;
	Data.SetNumZeroed(26);   // Kuro slots 0..25 written here; 26..31 (e.g. wet) belong to gameplay/effects drivers

	Data[0] = bYawFollowsActor && GetOwner() ? GetOwner()->GetActorRotation().Yaw + YawBaseDegrees : YawBaseDegrees;
	Data[1] = FixedDirectionWeight;

	const bool bHasHead = Mesh->GetBoneIndex(HeadBone) != INDEX_NONE;
	const FTransform Head = bHasHead ? Mesh->GetBoneTransform(Mesh->GetBoneIndex(HeadBone)) : Mesh->GetComponentTransform();
	const FVector Forward = Head.TransformVectorNoScale(HeadForwardLocal).GetSafeNormal();
	const FVector Side = Head.TransformVectorNoScale(HeadSideLocal).GetSafeNormal();
	const FVector Up = FVector::CrossProduct(Forward, Side).GetSafeNormal();
	// Shader reads forward as (3,6,9) and side as (4,7,10); slots (2,5,8) complete the 3x3 basis.
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		Data[2 + Axis * 3] = Up[Axis];
		Data[3 + Axis * 3] = Forward[Axis];
		Data[4 + Axis * 3] = Side[Axis];
	}
	Data[11] = SDFForcedFlipAndThreshold;
	Data[12] = SDFForcedWeight;
	Data[13] = LightAnchorBlend;

	auto Knee = [Mesh](FName Bone) { const int32 I = Mesh->GetBoneIndex(Bone); return I != INDEX_NONE ? Mesh->GetBoneLocation(Bone) : FVector::ZeroVector; };
	const FVector L = Knee(LeftKneeBone), R = Knee(RightKneeBone);
	Data[14] = L.X; Data[15] = L.Y; Data[16] = L.Z; Data[17] = KneeWeight;
	Data[18] = R.X; Data[19] = R.Y; Data[20] = R.Z; Data[21] = KneeWeight;

	Data[22] = PitchBaseDegrees;
	Data[23] = Head.GetLocation().X; Data[24] = Head.GetLocation().Y; Data[25] = Head.GetLocation().Z;

	for (int32 I = 0; I < Data.Num(); ++I)
	{
		Mesh->SetCustomPrimitiveDataFloat(I, Data[I]);
	}
	Mesh->SetCustomPrimitiveDataFloat(MaskIDSlot, float(GetEffectiveMaskID()));
}
