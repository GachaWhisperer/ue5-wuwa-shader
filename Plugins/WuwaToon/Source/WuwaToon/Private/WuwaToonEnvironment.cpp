#include "WuwaToonEnvironment.h"

#include "WuwaToonCharacterActor.h"
#include "WuwaToonCharacterComponent.h"
#include "WuwaToonViewTracker.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/SkyLight.h"
#include "Engine/TextureRenderTarget2D.h"
#include "EngineUtils.h"
#include "Interfaces/IPluginManager.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SceneInterface.h"
#include "SceneView.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogWuwaToonEnvironment, Log, All);

namespace WuwaToonMPC
{
	// Parameter names in MPC_WuwaToon (created by Content/Python/wuwa_create_mpc.py). Keep in sync.
	static const FName LightCount(TEXT("ToonLightCount"));
	static FName LightRecord(int32 Light, int32 Row) { return FName(*FString::Printf(TEXT("ToonLight%d_L%d"), Light, Row)); }
	static constexpr int32 MaxLights = 16;
}

namespace WuwaToonExtraCapture
{
	// Capture of unlit mask materials: only the mask emissive and scene depth matter, nothing may add colour.
	static void Configure(USceneCaptureComponent2D* C)
	{
		C->CaptureSource = SCS_SceneColorSceneDepth;
		C->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
		C->bCaptureEveryFrame = false;
		C->bCaptureOnMovement = false;
		C->bAlwaysPersistRenderingState = false;
		FEngineShowFlags& F = C->ShowFlags;
		F.SetAtmosphere(false); F.SetFog(false); F.SetVolumetricFog(false); F.SetCloud(false);
		F.SetPostProcessing(false); F.SetAntiAliasing(false); F.SetTemporalAA(false); F.SetMotionBlur(false);
		F.SetBloom(false); F.SetEyeAdaptation(false); F.SetDynamicShadows(false); F.SetAmbientOcclusion(false);
		F.SetScreenSpaceReflections(false); F.SetLumenGlobalIllumination(false); F.SetLumenReflections(false);
		F.SetSkyLighting(false); F.SetTranslucency(false); F.SetParticles(false); F.SetDecals(false);
	}

	// Cleared state = "no mask anywhere": R 0, depth far.
	static const FLinearColor ClearValue(0.f, 0.f, 0.f, 65504.f);
}

namespace WuwaToonPresets
{
	static const FName Custom(TEXT("Custom"));

	/** Content/Python/data/kuro_toon_lighting_presets.json: the one data source for C++ and wuwa_validation_presets.py. */
	static TSharedPtr<FJsonObject> Load()
	{
		const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("WuwaToon"));
		if (!Plugin)
		{
			return nullptr;
		}
		const FString Path = FPaths::Combine(Plugin->GetContentDir(), TEXT("Python"), TEXT("data"), TEXT("kuro_toon_lighting_presets.json"));
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			UE_LOG(LogWuwaToonEnvironment, Warning, TEXT("lighting presets: cannot read %s"), *Path);
			return nullptr;
		}
		TSharedPtr<FJsonObject> Root;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
		{
			UE_LOG(LogWuwaToonEnvironment, Warning, TEXT("lighting presets: %s is not valid JSON"), *Path);
			return nullptr;
		}
		return Root;
	}

	static const FJsonObject* Object(const FJsonObject& O, const TCHAR* Key)
	{
		const TSharedPtr<FJsonObject>* Out = nullptr;
		return O.TryGetObjectField(Key, Out) && Out && Out->IsValid() ? Out->Get() : nullptr;
	}

	/** wuwa_validation_presets.lc(): RGB(A) list -> LinearColor, alpha 0 when absent. */
	static bool Color(const FJsonObject* O, const TCHAR* Key, FLinearColor& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
		if (!O || !O->TryGetArrayField(Key, A) || !A || A->Num() < 3)
		{
			return false;
		}
		Out = FLinearColor(float((*A)[0]->AsNumber()), float((*A)[1]->AsNumber()), float((*A)[2]->AsNumber()),
			A->Num() > 3 ? float((*A)[3]->AsNumber()) : 0.f);
		return true;
	}

	static bool Vector(const FJsonObject* O, const TCHAR* Key, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
		if (!O || !O->TryGetArrayField(Key, A) || !A || A->Num() < 3)
		{
			return false;
		}
		Out = FVector((*A)[0]->AsNumber(), (*A)[1]->AsNumber(), (*A)[2]->AsNumber());
		return true;
	}

	template <class T>
	static T* FirstInWorld(UWorld* World)
	{
		if (World)
		{
			for (TActorIterator<T> It(World); It; ++It)
			{
				return *It;
			}
		}
		return nullptr;
	}
}

AWuwaToonEnvironment::AWuwaToonEnvironment()
{
	PrimaryActorTick.bCanEverTick = true;
	// After PlayerController::UpdateCameraManager (camera cache of this frame) and, via tick prerequisites, after the
	// characters' gating; before the frame's scene captures render.
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));

	ToonDepthCapture = CreateDefaultSubobject<USceneCaptureComponent2D>(TEXT("ToonDepthCapture"));
	ToonDepthCapture->SetupAttachment(RootComponent);
	ToonDepthCapture->CaptureSource = SCS_SceneDepth;
	ToonDepthCapture->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
	ToonDepthCapture->bCaptureEveryFrame = true;
	ToonDepthCapture->bCaptureOnMovement = false;
	ToonDepthCapture->bAlwaysPersistRenderingState = true;

	ToonShadowCapture = CreateDefaultSubobject<USceneCaptureComponent2D>(TEXT("ToonShadowCapture"));
	ToonShadowCapture->SetupAttachment(RootComponent);
	ToonShadowCapture->CaptureSource = SCS_SceneDepth;
	ToonShadowCapture->ProjectionType = ECameraProjectionMode::Orthographic;
	ToonShadowCapture->bCaptureEveryFrame = true;
	ToonShadowCapture->bCaptureOnMovement = false;

	HETCapture = CreateDefaultSubobject<USceneCaptureComponent2D>(TEXT("HETCapture"));
	HETCapture->SetupAttachment(RootComponent);
	WuwaToonExtraCapture::Configure(HETCapture);
	FaceShadowCapture = CreateDefaultSubobject<USceneCaptureComponent2D>(TEXT("FaceShadowCapture"));
	FaceShadowCapture->SetupAttachment(RootComponent);
	WuwaToonExtraCapture::Configure(FaceShadowCapture);
}

// ------------------------------------------------------------------------------------------------------------ lifecycle

void AWuwaToonEnvironment::PostRegisterAllComponents()
{
	Super::PostRegisterAllComponents();
	if (!HasAnyFlags(RF_ClassDefaultObject | RF_ArchetypeObject) && GetWorld() && !PrimaryViewSetupHandle.IsValid())
	{
		PrimaryViewSetupHandle = FWuwaToonViewTracker::OnPrimaryViewSetup().AddUObject(this, &AWuwaToonEnvironment::HandlePrimaryViewSetup);
	}
	UpdateTickPrerequisites();
}

void AWuwaToonEnvironment::PostUnregisterAllComponents()
{
	if (PrimaryViewSetupHandle.IsValid())
	{
		FWuwaToonViewTracker::OnPrimaryViewSetup().Remove(PrimaryViewSetupHandle);
		PrimaryViewSetupHandle.Reset();
	}
	Super::PostUnregisterAllComponents();
}

void AWuwaToonEnvironment::BeginPlay()
{
	Super::BeginPlay();
	UpdateTickPrerequisites();
	AssignCharacterMaskIds();
}

void AWuwaToonEnvironment::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	UpdateTickPrerequisites();
	AssignCharacterMaskIds();
}

void AWuwaToonEnvironment::UpdateTickPrerequisites()
{
	// The captures read each character's gating (AWuwaToonCharacterActor::Tick, same tick group): tick after them.
	RefreshManagedCharacters();
	for (AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (C)
		{
			AddTickPrerequisiteActor(C);
		}
	}
}

void AWuwaToonEnvironment::RefreshManagedCharacters()
{
	TArray<TObjectPtr<AWuwaToonCharacterActor>> Out;
	TSet<AWuwaToonCharacterActor*> Seen;
	auto Add = [&](AActor* A)
	{
		if (AWuwaToonCharacterActor* C = Cast<AWuwaToonCharacterActor>(A))
		{
			if (!Seen.Contains(C))
			{
				Seen.Add(C);
				Out.Add(C);
			}
		}
	};
	for (AActor* A : Characters)
	{
		if (!A)
		{
			continue;
		}
		Add(A);
		TArray<AActor*> ChildActors;
		A->GetAllChildActors(ChildActors, true);  // ChildActorComponents (generated character Blueprints), recursive
		for (AActor* Child : ChildActors)
		{
			Add(Child);
		}
	}
	if (bAutoCollectCharacters && GetWorld())
	{
		for (TActorIterator<AWuwaToonCharacterActor> It(GetWorld()); It; ++It)
		{
			Add(*It);
		}
	}
	ManagedCharacters = MoveTemp(Out);
}

FBox AWuwaToonEnvironment::FocusedShadowBounds() const
{
	// Group = top-level actor (a child actor's owning actor chain); pick the group whose bounds centre lies closest to
	// the view ray (ahead of the camera), and return that group's bounds.
	TMap<const AActor*, FBox> Groups;
	for (const AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (!C)
		{
			continue;
		}
		const AActor* Top = C;
		while (Top->GetParentActor())
		{
			Top = Top->GetParentActor();
		}
		FBox& B = Groups.FindOrAdd(Top, FBox(ForceInit));
		B += C->GetComponentsBoundingBox();
	}
	const FVector O = CurrentView.Location;
	const FVector D = CurrentView.Rotation.Vector();
	FBox Best(ForceInit);
	double BestScore = TNumericLimits<double>::Max();
	for (const TPair<const AActor*, FBox>& G : Groups)
	{
		if (!G.Value.IsValid)
		{
			continue;
		}
		const FVector P = G.Value.GetCenter() - O;
		const double Along = FVector::DotProduct(P, D);
		if (Along <= 0.0)
		{
			continue;   // behind the camera
		}
		const double Score = (P - D * Along).Size() + 0.05 * Along;   // off-axis distance, slight preference for nearer
		if (Score < BestScore)
		{
			BestScore = Score;
			Best = G.Value;
		}
	}
	return Best;
}

#if WITH_EDITOR
void AWuwaToonEnvironment::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);
	const FName Name = PropertyChangedEvent.GetMemberPropertyName();
	if (Name == GET_MEMBER_NAME_CHECKED(AWuwaToonEnvironment, LightingPreset))
	{
		ApplyLightingPreset(LightingPreset);
	}
	else if (Name == GET_MEMBER_NAME_CHECKED(AWuwaToonEnvironment, Characters))
	{
		UpdateTickPrerequisites();
		AssignCharacterMaskIds();
	}
}
#endif

// ------------------------------------------------------------------------------------------------------- lighting preset

TArray<FString> AWuwaToonEnvironment::GetLightingPresetNames()
{
	TArray<FString> Names;
	Names.Add(WuwaToonPresets::Custom.ToString());
	if (const TSharedPtr<FJsonObject> Root = WuwaToonPresets::Load())
	{
		for (const FJsonObject* Group : { WuwaToonPresets::Object(*Root, TEXT("scenarios")), WuwaToonPresets::Object(*Root, TEXT("presets")) })
		{
			if (Group)
			{
				for (const TPair<FString, TSharedPtr<FJsonValue>>& It : Group->Values)
				{
					Names.AddUnique(It.Key);
				}
			}
		}
	}
	return Names;
}

bool AWuwaToonEnvironment::ApplyLightingPreset(FName Preset)
{
	using namespace WuwaToonPresets;
	if (Preset.IsNone() || Preset == Custom)
	{
		LightingPreset = Custom;   // no-op: keep the current values
		return true;
	}
	const TSharedPtr<FJsonObject> Root = Load();
	if (!Root)
	{
		return false;
	}
	FString Key = Preset.ToString();
	if (const FJsonObject* Scenarios = Object(*Root, TEXT("scenarios")))
	{
		FString Target;   // scenario alias -> recovered preset (master prompt §8 names)
		if (Scenarios->TryGetStringField(Key, Target))
		{
			Key = Target;
		}
	}
	const FJsonObject* Presets = Object(*Root, TEXT("presets"));
	const FJsonObject* P = Presets ? Object(*Presets, *Key) : nullptr;
	if (!P)
	{
		UE_LOG(LogWuwaToonEnvironment, Warning, TEXT("%s: unknown lighting preset %s"), *GetName(), *Preset.ToString());
		return false;
	}
#if WITH_EDITOR
	Modify();
#endif
	// Exactly the fields wuwa_validation_presets.apply() sets; absent fields keep their current value.
	FLinearColor C, Near;
	if (Color(P, TEXT("AmbientA_Far"), C))
	{
		AmbientA_Far = C;
		AmbientA_Near = Color(P, TEXT("AmbientA_Near"), Near) ? Near : C;   // near = far: unrecovered gradient distance has no effect
	}
	if (Color(P, TEXT("AmbientB_Far"), C))
	{
		AmbientB_Far = C;
		AmbientB_Near = Color(P, TEXT("AmbientB_Near"), Near) ? Near : C;
	}
	if (Color(P, TEXT("MainLightColor"), C))   // View[301] = CharacterRimColor
	{
		RimColor = C;
	}
	FVector V;
	if (Vector(P, TEXT("MainLightDir"), V))    // View[302] = KuroCharRimDir
	{
		RimDirection = V;
		bRimDirectionFromMainLight = false;
	}
	if (const FJsonObject* Partial = Object(*P, TEXT("AmbientParamsPartial")))
	{
		double X;
		if (Partial->TryGetNumberField(TEXT("x"), X)) { AmbientParams.X = X; }
		if (Partial->TryGetNumberField(TEXT("y"), X)) { AmbientParams.Y = X; }
		if (Partial->TryGetNumberField(TEXT("z"), X)) { AmbientParams.Z = X; }
	}
	if (Vector(P, TEXT("AORemap"), V))
	{
		AORemap = V;
	}
	if (const FJsonObject* Related = Object(*P, TEXT("related_inputs")))
	{
		ADirectionalLight* Sun = MainLight ? MainLight.Get() : FirstInWorld<ADirectionalLight>(GetWorld());
		if (Sun && Sun->GetLightComponent() && Color(Related, TEXT("MainLightTint"), C))
		{
#if WITH_EDITOR
			Sun->GetLightComponent()->Modify();
#endif
			Sun->GetLightComponent()->SetLightColor(C);   // sRGB = true, as unreal.LightComponent.set_light_color
		}
		ASkyLight* Sky = SkyLight ? SkyLight.Get() : FirstInWorld<ASkyLight>(GetWorld());
		double Intensity;
		if (Sky && Sky->GetLightComponent() && Related->TryGetNumberField(TEXT("SkyLightIntensity"), Intensity))
		{
#if WITH_EDITOR
			Sky->GetLightComponent()->Modify();
#endif
			Sky->GetLightComponent()->SetIntensity(float(Intensity));
		}
	}
	LightingPreset = Preset;
	FString Source;
	P->TryGetStringField(TEXT("source"), Source);
	UE_LOG(LogWuwaToonEnvironment, Log, TEXT("%s: applied lighting preset %s (%s) <- %s"), *GetName(), *Preset.ToString(), *Key, *Source);
	return true;
}

// ------------------------------------------------------------------------------------------------------------ per frame

void AWuwaToonEnvironment::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	// Validation toggle (not recovered): rotating light-direction test, same yaw step as wuwa_validation_presets.rotate_light.
	if (ValidationLightRotationDegreesPerSecond != 0.f && MainLight && MainLight->GetRootComponent()
		&& MainLight->GetRootComponent()->Mobility == EComponentMobility::Movable)
	{
		FRotator R = MainLight->GetActorRotation();
		R.Yaw = FRotator::NormalizeAxis(R.Yaw + ValidationLightRotationDegreesPerSecond * DeltaSeconds);
		MainLight->SetActorRotation(R);
	}
	RefreshManagedCharacters();
	AssignCharacterMaskIds();
	// This frame's view (camera cache is updated before TG_PostUpdateWork; editor: active viewport client).
	CurrentView = FWuwaToonViewTracker::ResolveCurrent(GetWorld());
	static const TCHAR* SourceNames[] = { TEXT("None"), TEXT("PlayerCamera"), TEXT("EditorViewport"), TEXT("RenderedView"), TEXT("LateSetupView") };
	CaptureViewSource = FName(SourceNames[FMath::Clamp(int32(CurrentView.Source), 0, 4)]);
	SyncToonShadowCapture();
	SyncExtraPassCaptures();
	PushParameters();
	SyncToonDepthCapture();
}

void AWuwaToonEnvironment::AssignCharacterMaskIds()
{
	TSet<int32> Used;
	for (const AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (C && C->ToonCharacter && C->ToonCharacter->MaskID > 0)
		{
			Used.Add(C->ToonCharacter->MaskID);
		}
	}
	int32 Next = 1;
	for (AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (!C || !C->ToonCharacter)
		{
			continue;
		}
		if (!C->GetSkeletalMeshComponent()->IsVisible())
		{
			C->ToonCharacter->SetAssignedMaskID(0);   // hidden part (e.g. a skill prop of a character Blueprint): no ID used
			continue;
		}
		if (C->ToonCharacter->MaskID > 0)
		{
			C->ToonCharacter->SetAssignedMaskID(0);
			continue;
		}
		while (Used.Contains(Next))
		{
			++Next;
		}
		C->ToonCharacter->SetAssignedMaskID(Next <= 255 ? Next : 0);
		Used.Add(Next);
	}
}

void AWuwaToonEnvironment::SyncToonShadowCapture()
{
	ToonShadowCapture->bCaptureEveryFrame = ToonShadowTarget != nullptr && MainLight != nullptr;
	if (!ToonShadowCapture->bCaptureEveryFrame)
	{
		return;
	}
	FBox Bounds = bShadowFocusOnView && CurrentView.bValid ? FocusedShadowBounds() : FBox(ForceInit);
	if (!Bounds.IsValid)
	{
		for (const AWuwaToonCharacterActor* C : ManagedCharacters)
		{
			if (C)
			{
				Bounds += C->GetComponentsBoundingBox();
			}
		}
	}
	const FVector Centre = Bounds.IsValid ? Bounds.GetCenter() : GetActorLocation();
	const FVector LightTravel = MainLight->GetActorForwardVector();
	ToonShadowCapture->TextureTarget = ToonShadowTarget;
	// Capture-only extra-pass meshes are visible to every capture; keep them out of the light-space depth, except the
	// active face-shadow shell, which casts in Kuro (bFaceShadowShellCastsToonShadow).
	ToonShadowCapture->HiddenComponents.Reset();
	for (const AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (C)
		{
			TArray<UPrimitiveComponent*> Extra;
			C->GetExtraPassComponents(Extra);
			const UPrimitiveComponent* Caster = bFaceShadowShellCastsToonShadow ? C->GetActiveFaceShadowCaster() : nullptr;
			for (UPrimitiveComponent* P : Extra)
			{
				if (P != Caster)
				{
					ToonShadowCapture->HiddenComponents.Add(P);
				}
			}
		}
	}
	ToonShadowCapture->OrthoWidth = ShadowOrthoWidth;
	ToonShadowCapture->SetWorldLocationAndRotation(Centre - LightTravel * ShadowDistance * 0.5f, LightTravel.Rotation());
}

void AWuwaToonEnvironment::PushParameters() const
{
	if (!ToonParameters)
	{
		return;
	}
	UWorld* World = GetWorld();
	auto S = [&](const TCHAR* Name, float V) { UKismetMaterialLibrary::SetScalarParameterValue(World, ToonParameters, FName(Name), V); };
	auto V = [&](FName Name, const FLinearColor& C) { UKismetMaterialLibrary::SetVectorParameterValue(World, ToonParameters, Name, C); };
	auto V3 = [&](const TCHAR* Name, const FVector& C, float W = 0.f) { V(FName(Name), FLinearColor(C.X, C.Y, C.Z, W)); };

	// Main light: Kuro's View[302] points toward the light (rim: dot(L, N) with L = MainLightDir).
	FVector ToLight(0, 0, 1);
	if (MainLight && MainLight->GetComponent())
	{
		ToLight = -MainLight->GetActorForwardVector();
	}
	// View[301]/[302] are the character RIM colour and direction (ToonLightingData.md), fed from the rim properties.
	FVector RimDir = RimDirection;
	if (bRimDirectionFromMainLight)
	{
		const FVector Horizontal = FVector(ToLight.X, ToLight.Y, 0.f).GetSafeNormal();
		const float Elev = FMath::DegreesToRadians(30.f);   // EulerToForward(pitch 30, yaw H)
		RimDir = Horizontal * FMath::Cos(Elev) + FVector::UpVector * FMath::Sin(Elev);
	}
	V3(TEXT("ToonMainLightDir"), RimDir);
	V(FName(TEXT("ToonMainLightColor")), RimColor);
	// The character base passes read MPC_GlobalShaderParameters' GlobalCharacterDebugLightDirection slot as their base
	// light direction (cb3[42]; research/shaders/ToonCommon.md). The asset default is (0,0,0) -> NaN, so the game must
	// set it at runtime; we feed the main light's toward-light direction (role inferred from the half-Lambert use).
	V3(TEXT("GlobalCharacterDebugLightDirection"), ToLight);

	// Validation toggles (not recovered data) only alter the published values.
	FLinearColor AmbA_Near = AmbientA_Near, AmbA_Far = AmbientA_Far;
	float ShadowScale = AOStrength;
	FLinearColor GIEnable(bHSVIndirect ? 1.f : 0.f, bGITint ? 1.f : 0.f, 0, 0);
	if (bValidationHighContrast)
	{
		AmbA_Near *= ValidationHighContrastShadowScale;
		AmbA_Far *= ValidationHighContrastShadowScale;
		ShadowScale = 1.f;
	}
	if (bValidationDirectLightOnly)
	{
		AmbA_Near = AmbA_Far = FLinearColor(0.f, 0.f, 0.f, 0.f);
		GIEnable = FLinearColor(0.f, 0.f, 0.f, 0.f);
	}

	S(TEXT("ToonAOStrength"), ShadowScale);
	// Extra-pass emulation globals (HETPasses.md §4.3). Enables drop to 0 when no character drew into a mask this frame.
	S(TEXT("HETEnable"), bHETActive ? 1.f : 0.f);
	S(TEXT("FSEnable"), bFaceShadowActive ? 1.f : 0.f);
	S(TEXT("HETMaxBehind"), HETMaxBehind);
	S(TEXT("HETAOpacityScale"), HETAOpacityScale);
	S(TEXT("FSDepthEps"), FSDepthEps);
	V(FName(TEXT("ToonGIEnable")), GIEnable);
	V3(TEXT("ToonAmbientParams"), AmbientParams);
	V(FName(TEXT("ToonAmbientA_Near")), AmbA_Near);
	V(FName(TEXT("ToonAmbientA_Far")), AmbA_Far);
	V(FName(TEXT("ToonAmbientB_Near")), AmbientB_Near);
	V(FName(TEXT("ToonAmbientB_Far")), AmbientB_Far);
	V3(TEXT("ToonAORemap"), AORemap);
	V(FName(TEXT("ToonDepthGradient")), FLinearColor(DepthGradient.X, DepthGradient.Y, 0, 0));
	V(FName(TEXT("ToonRimPass")), FLinearColor(RimWidthScale, 0, 0, 0));
	V(FName(TEXT("ToonRimTint")), RimTint);

	// Light-space toon shadow basis for WuwaToonShadowMaskKuroSingle: Origin.w = ortho width (0 disables),
	// Forward.w = subject depth range (Kuro InvMaxSubjectDepth = 1/range), Right.w = caster bias (cm).
	const FTransform ST = ToonShadowCapture->GetComponentTransform();
	V3(TEXT("ToonShadowOrigin"), ST.GetLocation(), ToonShadowCapture->bCaptureEveryFrame ? ShadowOrthoWidth : 0.f);
	V3(TEXT("ToonShadowForward"), ST.GetUnitAxis(EAxis::X), ShadowDistance);
	V3(TEXT("ToonShadowRight"), ST.GetUnitAxis(EAxis::Y), ShadowDepthBias);
	V3(TEXT("ToonShadowUp"), ST.GetUnitAxis(EAxis::Z));

	// Toon local lights, laid out exactly like ToonLocalLightData (9 float4 per light).
	int32 Count = 0;
	for (const FWuwaToonLocalLight& L : LocalLights)
	{
		if (Count >= WuwaToonMPC::MaxLights || !L.Light)
		{
			continue;
		}
		const ULocalLightComponent* LC = L.Light->FindComponentByClass<ULocalLightComponent>();
		if (!LC)
		{
			continue;
		}
		const USpotLightComponent* Spot = Cast<USpotLightComponent>(LC);
		const FVector P = LC->GetComponentLocation();
		const float InvRadius = 1.f / FMath::Max(LC->AttenuationRadius, 1.f);
		const FVector Dir = -LC->GetForwardVector();
		// L1.w: light type in bits 16..17 (2 = spot). Stored numerically; WuwaToonLocalLight reads (uint)L1.w.
		const float TypeBits = Spot ? float(2u << 16) : 0.f;
		const float CosOuter = Spot ? FMath::Cos(FMath::DegreesToRadians(Spot->OuterConeAngle)) : 0.f;
		const float CosInner = Spot ? FMath::Cos(FMath::DegreesToRadians(Spot->InnerConeAngle)) : 1.f;
		const FLinearColor Col = LC->GetLightColor() * LC->Intensity;
		const FLinearColor Rows[9] = {
			FLinearColor(P.X, P.Y, P.Z, InvRadius),
			FLinearColor(Dir.X, Dir.Y, Dir.Z, TypeBits),
			FLinearColor(CosOuter, 1.f / FMath::Max(CosInner - CosOuter, 1e-4f), 0, 0),
			FLinearColor(L.HardBaseColor.R, L.HardBaseColor.G, L.HardBaseColor.B, L.HardShadowFactor),
			FLinearColor(L.Falloff.X, L.Falloff.Y, L.Falloff.Z, L.Falloff.W),
			FLinearColor(L.BaseColor.R * Col.R, L.BaseColor.G * Col.G, L.BaseColor.B * Col.B, L.StepCentre),
			FLinearColor(L.ShadowColor.R, L.ShadowColor.G, L.ShadowColor.B, L.DistanceBlend),
			FLinearColor(L.Intensity, L.Occlusion, 0, float(L.LightingChannelMask & 7)),
			FLinearColor(L.StepSoftness, L.bHard ? 1.f : 0.f, 0, 0),
		};
		for (int32 Row = 0; Row < 9; ++Row)
		{
			V(WuwaToonMPC::LightRecord(Count, Row), Rows[Row]);
		}
		++Count;
	}
	S(*WuwaToonMPC::LightCount.ToString(), float(Count));
}

void AWuwaToonEnvironment::AlignCapture(USceneCaptureComponent2D* Capture, UTextureRenderTarget2D* Target, const FWuwaToonTrackedView& View) const
{
	// Same view as the main camera so materials read their own pixel: location, rotation, horizontal FOV (from the view's
	// projection: axis constraint / letterboxing included) and a render target sized to the unscaled view rect (aspect).
	if (!View.bValid || !Capture || !Target)
	{
		return;
	}
	Capture->SetWorldLocationAndRotation(View.Location, View.Rotation);
	Capture->FOVAngle = View.HorizontalFOVDegrees;
	if (Target->SizeX != View.Size.X || Target->SizeY != View.Size.Y)
	{
		Target->ResizeTarget(View.Size.X, View.Size.Y);
	}
}

void AWuwaToonEnvironment::HandlePrimaryViewSetup(const FSceneViewFamily& Family, const FSceneView& View, const FWuwaToonTrackedView& Tracked)
{
	// Only the viewport this tick aligned to, only for this world; runs before that family's deferred captures render.
	if (!bLateViewAlignment || !Tracked.bValid || !CurrentView.bValid || !CurrentView.RenderTarget
		|| Family.RenderTarget != CurrentView.RenderTarget || !Family.Scene || Family.Scene->GetWorld() != GetWorld())
	{
		return;
	}
	if (ToonDepthTarget && ToonDepthCapture->bCaptureEveryFrame)
	{
		AlignCapture(ToonDepthCapture, ToonDepthTarget, Tracked);
	}
	if (bHETActive)
	{
		AlignCapture(HETCapture, HETMaskTarget, Tracked);
	}
	if (bFaceShadowActive)
	{
		AlignCapture(FaceShadowCapture, FaceShadowMaskTarget, Tracked);
	}
}

void AWuwaToonEnvironment::SyncToonDepthCapture()
{
	if (!ToonDepthTarget)
	{
		ToonDepthCapture->bCaptureEveryFrame = false;
		return;
	}
	ToonDepthCapture->bCaptureEveryFrame = true;
	ToonDepthCapture->TextureTarget = ToonDepthTarget;
	ToonDepthCapture->ShowOnlyActors.Reset();
	ToonDepthCapture->HiddenComponents.Reset();
	for (AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (C)
		{
			ToonDepthCapture->ShowOnlyActors.Add(C);
		}
		// ShowOnlyActors would include the capture-only HET / FS meshes and the HETA copy (HETPasses.md §4.2).
		if (C)
		{
			TArray<UPrimitiveComponent*> Extra;
			C->GetExtraPassComponents(Extra);
			ToonDepthCapture->HiddenComponents.Append(Extra);
		}
	}
	AlignCapture(ToonDepthCapture, ToonDepthTarget, CurrentView);
}

bool AWuwaToonEnvironment::SyncMaskCapture(USceneCaptureComponent2D* Capture, UTextureRenderTarget2D* Target,
	const TArray<UPrimitiveComponent*>& Show, bool& bWasActive)
{
	if (!Target || Show.IsEmpty())
	{
		Capture->bCaptureEveryFrame = false;
		if (bWasActive && Target)
		{
			// A capture that stops leaves its last frame in the target; clear it so no stale mask is sampled.
			UKismetRenderingLibrary::ClearRenderTarget2D(this, Target, WuwaToonExtraCapture::ClearValue);
		}
		bWasActive = false;
		return false;
	}
	Capture->TextureTarget = Target;
	Capture->ShowOnlyComponents.Reset();
	for (UPrimitiveComponent* P : Show)
	{
		Capture->ShowOnlyComponents.Add(P);
	}
	AlignCapture(Capture, Target, CurrentView);
	Capture->bCaptureEveryFrame = true;
	bWasActive = true;
	return true;
}

void AWuwaToonEnvironment::SyncExtraPassCaptures()
{
	TArray<UPrimitiveComponent*> HETShow, FSShow;
	for (const AWuwaToonCharacterActor* C : ManagedCharacters)
	{
		if (C)
		{
			C->GetActiveHETCaptureComponents(HETShow);
			C->GetActiveFaceShadowCaptureComponents(FSShow);
		}
	}
	SyncMaskCapture(HETCapture, HETMaskTarget, HETShow, bHETActive);
	SyncMaskCapture(FaceShadowCapture, FaceShadowMaskTarget, FSShow, bFaceShadowActive);
}
