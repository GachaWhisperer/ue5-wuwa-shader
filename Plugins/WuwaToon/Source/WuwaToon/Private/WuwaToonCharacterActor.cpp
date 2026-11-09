#include "WuwaToonCharacterActor.h"

#include "WuwaToonCharacterComponent.h"
#include "WuwaToonExtraMaterials.h"
#include "WuwaToonViewTracker.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Materials/MaterialInterface.h"

DEFINE_LOG_CATEGORY_STATIC(LogWuwaToonCharacter, Log, All);

namespace WuwaToonCharacter
{
	static const TCHAR* HiddenPath = TEXT("/Game/WuWa/Materials/Masters/M_Wuwa_Hidden.M_Wuwa_Hidden");
}

AWuwaToonCharacterActor::AWuwaToonCharacterActor(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;   // after animation: head position and morphs are current

	ToonCharacter = CreateDefaultSubobject<UWuwaToonCharacterComponent>(TEXT("ToonCharacter"));

	auto MakeFollower = [this](const TCHAR* Name)
	{
		USkeletalMeshComponent* C = CreateDefaultSubobject<USkeletalMeshComponent>(Name);
		C->SetupAttachment(GetSkeletalMeshComponent());
		// Every Kuro _OL / HET MI sets bDisableCastDynamicShadows. FS casts in Kuro (M_FaceShadowMesh has ShadowDepth shaders);
		// the plugin reproduces that in its own light-space toon shadow capture (AWuwaToonEnvironment), not in UE's shadow
		// maps, which the toon materials do not read.
		C->SetCastShadow(false);
		C->bCastDynamicShadow = false;
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetGenerateOverlapEvents(false);
		C->bReceivesDecals = false;
		return C;
	};
	OutlineMesh = MakeFollower(TEXT("OutlineMesh"));
	HETMaskMesh = MakeFollower(TEXT("HETMaskMesh"));
	HETOccluderMesh = MakeFollower(TEXT("HETOccluderMesh"));
	FaceShadowMesh = MakeFollower(TEXT("FaceShadowMesh"));
	HETAMesh = MakeFollower(TEXT("HETAMesh"));
	HETMaskMesh->bVisibleInSceneCaptureOnly = true;
	HETOccluderMesh->bVisibleInSceneCaptureOnly = true;
	FaceShadowMesh->bVisibleInSceneCaptureOnly = true;
	HETAMesh->TranslucencySortPriority = 10;   // HETA is the last character pass (RenderQueue 300)
}

void AWuwaToonCharacterActor::ConfigureFollower(USkeletalMeshComponent* Follower, bool bCaptureOnly) const
{
	USkeletalMeshComponent* Body = GetSkeletalMeshComponent();
	if (Follower->GetSkeletalMeshAsset() != Body->GetSkeletalMeshAsset())
	{
		Follower->SetSkeletalMeshAsset(Body->GetSkeletalMeshAsset());
	}
	Follower->SetLeaderPoseComponent(Body);
	Follower->SetVisibleInSceneCaptureOnly(bCaptureOnly);
}

void AWuwaToonCharacterActor::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	AssignExtraMaterials();
}

void AWuwaToonCharacterActor::AssignExtraMaterials()
{
	bExtraConfigured = true;
	USkeletalMeshComponent* Body = GetSkeletalMeshComponent();
	// Animation-driven morph curves (eye blink etc.) must reach the followers, or the HET mask / outline would not follow.
	Body->bPropagateCurvesToFollowers = true;
	ConfigureFollower(OutlineMesh, false);
	ConfigureFollower(HETMaskMesh, true);
	ConfigureFollower(HETOccluderMesh, true);
	ConfigureFollower(FaceShadowMesh, true);
	ConfigureFollower(HETAMesh, false);

	UMaterialInterface* Hidden = LoadObject<UMaterialInterface>(nullptr, WuwaToonCharacter::HiddenPath, nullptr, LOAD_NoWarn);
	USkeletalMeshComponent* Followers[] = { OutlineMesh, HETMaskMesh, HETOccluderMesh, FaceShadowMesh, HETAMesh };
	const int32 NumSlots = Body->GetNumMaterials();
	for (USkeletalMeshComponent* F : Followers)
	{
		for (int32 Slot = 0; Slot < NumSlots; ++Slot)
		{
			F->SetMaterial(Slot, Hidden);
		}
	}
	MaxLODOutline = MaxLODHET = MaxLODHETA = MaxLODFaceShadow = -1;

	const UWuwaToonExtraMaterialsUserData* Data = UWuwaToonExtraMaterialsUserData::FindOnMesh(Body->GetSkeletalMeshAsset());
	if (!Data)
	{
		if (Body->GetSkeletalMeshAsset())
		{
			UE_LOG(LogWuwaToonCharacter, Warning, TEXT("%s: mesh %s has no WuwaToon extra-material data (run wuwa_generate_materials.py); "
				"outline / HET / HETA / FS passes disabled"), *GetName(), *Body->GetSkeletalMeshAsset()->GetName());
		}
		UpdateGating();
		return;
	}
	EyeTransparentDrawDistance = Data->EyeTransparentDrawDistance;
	FaceShadowMeshDrawDistance = Data->FaceShadowMeshDrawDistance;
	OutlineDrawDistance = Data->OutlineDrawDistance;

	for (const FWuwaToonSectionPasses& Section : Data->Sections)
	{
		if (Section.MaterialSlot < 0 || Section.MaterialSlot >= NumSlots)
		{
			continue;
		}
		for (const FWuwaToonExtraPass& Pass : Section.Passes)
		{
			if (Pass.bEmpty || !Pass.Material)
			{
				continue;   // Kuro M_Empty (e.g. MI_Eye_OL on the eye / star sections): nothing drawn
			}
			USkeletalMeshComponent* Target = nullptr;
			int32* MaxLOD = nullptr;
			switch (Pass.Type)
			{
			case EWuwaToonSlotType::Outline:            Target = OutlineMesh;    MaxLOD = &MaxLODOutline;    break;
			case EWuwaToonSlotType::EyeMask:            Target = HETMaskMesh;    MaxLOD = &MaxLODHET;        break;
			case EWuwaToonSlotType::HairEyeTransparent: Target = HETAMesh;       MaxLOD = &MaxLODHETA;       break;
			case EWuwaToonSlotType::FaceShadow:         Target = FaceShadowMesh; MaxLOD = &MaxLODFaceShadow; break;
			default:
				UE_LOG(LogWuwaToonCharacter, Warning, TEXT("%s: slot %d pass %s has unsupported type %d"), *GetName(),
					Section.MaterialSlot, *Pass.KuroSlotName.ToString(), int32(Pass.Type));
				continue;
			}
			Target->SetMaterial(Section.MaterialSlot, Pass.Material);
			*MaxLOD = FMath::Max(*MaxLOD, Pass.MaxKuroLOD);
		}
	}
	if (MaxLODHET >= 0 && Data->HETOccluderMaterial)
	{
		for (int32 Slot : Data->HETOccluderSlots)
		{
			if (Slot >= 0 && Slot < NumSlots)
			{
				HETOccluderMesh->SetMaterial(Slot, Data->HETOccluderMaterial);
			}
		}
	}
	UpdateGating();
}

void AWuwaToonCharacterActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bExtraConfigured || HETMaskMesh->GetSkeletalMeshAsset() != GetSkeletalMeshComponent()->GetSkeletalMeshAsset())
	{
		AssignExtraMaterials();   // first tick in this process (no construction script when cooked) or mesh swapped
	}
	UpdateGating();
	SyncFollowerMorphs();
}

void AWuwaToonCharacterActor::UpdateGating()
{
	USkeletalMeshComponent* Body = GetSkeletalMeshComponent();
	const UWuwaToonExtraMaterialsUserData* Data = UWuwaToonExtraMaterialsUserData::FindOnMesh(Body->GetSkeletalMeshAsset());

	// Kuro measures the draw distances from the camera; the head is where the HET / FS passes live.
	FVector Anchor = Body->Bounds.Origin;
	const FName Head = Data ? Data->HeadBoneName : FName(TEXT("Bip001Head"));
	if (Body->GetBoneIndex(Head) != INDEX_NONE)
	{
		Anchor = Body->GetBoneLocation(Head);
	}
	// Current frame's view (player camera / active editor viewport), same source as the environment's captures.
	const FWuwaToonTrackedView View = FWuwaToonViewTracker::ResolveCurrent(GetWorld());
	ViewDistance = View.bValid ? float(FVector::Dist(View.Location, Anchor)) : 0.f;
	KuroLOD = Data ? Data->KuroLODForDistance(ViewDistance) : 0;

	const bool bBodyVisible = Body->IsVisible();
	auto Active = [&](int32 MaxLOD, float DrawDistance, bool bEnabled)
	{
		return bEnabled && bBodyVisible && MaxLOD >= 0 && KuroLOD <= MaxLOD && ViewDistance <= DrawDistance;
	};
	const bool bOutline = Active(MaxLODOutline, OutlineDrawDistance, bEnableOutline);
	const bool bHETA = Active(MaxLODHETA, EyeTransparentDrawDistance, bEnableEyeTransparent);
	// HET masks only matter when a HETA pass consumes them (bangs cut + HETA redraw).
	bActiveHET = bHETA && Active(MaxLODHET, EyeTransparentDrawDistance, bEnableEyeTransparent);
	bActiveFaceShadow = Active(MaxLODFaceShadow, FaceShadowMeshDrawDistance, bEnableFaceShadowMesh);

	auto Set = [](USkeletalMeshComponent* C, bool bVisible) { if (C->IsVisible() != bVisible) { C->SetVisibility(bVisible); } };
	Set(OutlineMesh, bOutline);
	Set(HETMaskMesh, bActiveHET);
	Set(HETOccluderMesh, bActiveHET);
	Set(HETAMesh, bActiveHET);
	Set(FaceShadowMesh, bActiveFaceShadow);
}

void AWuwaToonCharacterActor::SyncFollowerMorphs()
{
	// Script-set morph targets (SetMorphTarget on the body) are not propagated to leader-posed followers by the engine.
	const TMap<FName, float>& Curves = GetSkeletalMeshComponent()->GetMorphTargetCurves();
	if (Curves.IsEmpty())
	{
		return;
	}
	USkeletalMeshComponent* Followers[] = { OutlineMesh, HETMaskMesh, HETOccluderMesh, FaceShadowMesh, HETAMesh };
	for (USkeletalMeshComponent* F : Followers)
	{
		if (F->IsVisible())
		{
			for (const TPair<FName, float>& Curve : Curves)
			{
				F->SetMorphTarget(Curve.Key, Curve.Value);
			}
		}
	}
}

void AWuwaToonCharacterActor::GetExtraPassComponents(TArray<UPrimitiveComponent*>& Out) const
{
	Out.Add(HETMaskMesh);
	Out.Add(HETOccluderMesh);
	Out.Add(FaceShadowMesh);
	Out.Add(HETAMesh);
}

void AWuwaToonCharacterActor::GetActiveHETCaptureComponents(TArray<UPrimitiveComponent*>& Out) const
{
	if (bActiveHET)
	{
		Out.Add(HETMaskMesh);
		Out.Add(HETOccluderMesh);
	}
}

void AWuwaToonCharacterActor::GetActiveFaceShadowCaptureComponents(TArray<UPrimitiveComponent*>& Out) const
{
	if (bActiveFaceShadow)
	{
		Out.Add(FaceShadowMesh);
	}
}

UPrimitiveComponent* AWuwaToonCharacterActor::GetActiveFaceShadowCaster() const
{
	return bActiveFaceShadow ? FaceShadowMesh.Get() : nullptr;
}
