#pragma once

#include "GameFramework/Actor.h"
#include "WuwaToonViewTracker.h"
#include "WuwaToonEnvironment.generated.h"

class UMaterialParameterCollection;
class USceneCaptureComponent2D;
class UTextureRenderTarget2D;
class UPrimitiveComponent;
class ADirectionalLight;
class APointLight;
class ASpotLight;
class ASkyLight;
class AWuwaToonCharacterActor;

/** One Kuro toon local light (FToonLocalLightShaderParameters; 9 float4 per light in ToonLocalLightData). */
USTRUCT(BlueprintType)
struct FWuwaToonLocalLight
{
	GENERATED_BODY()

	/** Point or spot light actor providing position, radius, direction and cone. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) TObjectPtr<AActor> Light = nullptr;
	/** L5.xyz base colour (lit side), L5.w toon step centre. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) FLinearColor BaseColor = FLinearColor::White;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float StepCentre = 0.5f;
	/** L6.xyz shadow colour multiplier, L6.w distance-edge blend. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) FLinearColor ShadowColor = FLinearColor(0.5f, 0.5f, 0.5f);
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float DistanceBlend = 0.f;
	/** L3.xyz hard base colour, L3.w hard shadow factor. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) FLinearColor HardBaseColor = FLinearColor::Black;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float HardShadowFactor = 0.f;
	/** L7.x intensity, L7.y occlusion strength, L7.w lighting channel mask (3 bits). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float Intensity = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float Occlusion = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 LightingChannelMask = 1;
	/** L4.xyzw falloff (inverse-square scale, bias, attenuation scale) and light-axis facing weight. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) FVector4 Falloff = FVector4(1.f, 1.f, 1.f, 0.f);
	/** L8.x step softness, L8.y > 0 selects the "hard" accumulation path. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite) float StepSoftness = 0.1f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite) bool bHard = false;
};

/**
 * Publishes the Kuro toon View-uniform additions and toon local lights (consumed by FKuroToonShadingPS,
 * View[286..306] and ToonLocalLightData) into MPC_WuwaToon, and renders the character-only depth used by
 * the screen-space rim (Kuro: KuroToonRimDepthTexture / GBufferToonDepth). Field meanings: research/hlsl/
 * KuroToonShading_Deferred.hlsl. Values must be set per scene; the game's runtime values are not in the files.
 */
UCLASS(ClassGroup = (WuwaToon))
class WUWATOON_API AWuwaToonEnvironment : public AActor
{
	GENERATED_BODY()

public:
	AWuwaToonEnvironment();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon")
	TObjectPtr<UMaterialParameterCollection> ToonParameters;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Main Light")
	TObjectPtr<ADirectionalLight> MainLight;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Main Light")
	float MainLightIntensityScale = 1.f;

	/**
	 * Recovered toon lighting preset (KuroWeatherDataAsset CharacterSetting; research/shaders/ToonLightingData.md). Options:
	 * "Custom" (no-op: keep the values below), the scenario aliases (OutdoorDaylight, Indoor, Night, StudioDay, StudioNight,
	 * NearFar) and every preset in Content/Python/data/kuro_toon_lighting_presets.json, the single source shared with
	 * wuwa_validation_presets.py. Selecting one applies exactly the fields the preset defines (ambient A/B far, near = far
	 * unless given, rim colour/direction, AmbientParams axes, AORemap, sun tint, sky light intensity); everything else is
	 * kept. Records the last applied preset; later manual edits are not tracked.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "WuwaToon|Lighting Preset", meta = (GetOptions = "GetLightingPresetOptions"))
	FName LightingPreset = TEXT("Custom");

	/** Sky light whose intensity a preset sets (related_inputs.SkyLightIntensity). Empty = first ASkyLight in the world. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Lighting Preset")
	TObjectPtr<ASkyLight> SkyLight;

	/** Applies a preset or scenario alias from the JSON (runtime-safe; the file is read from the plugin directory). "Custom" = no-op. */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon|Lighting Preset")
	bool ApplyLightingPreset(FName Preset);

	/** "Custom", the scenario aliases, then every preset name in the JSON. */
	UFUNCTION(BlueprintPure, Category = "WuwaToon|Lighting Preset")
	static TArray<FString> GetLightingPresetNames();

	UFUNCTION()
	TArray<FString> GetLightingPresetOptions() const { return GetLightingPresetNames(); }

	// Validation toggles (master prompt §8 test environment). NOT recovered data: they only change what is published to
	// MPC_WuwaToon (stored properties are untouched) or animate the sun, to exercise the shading under controlled lighting.

	/** Direct-light-only test: publishes zero shadow-side ambient (AmbientA near/far = 0) and disables the GI flags (View[289]). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Validation Toggles (not recovered)", meta = (DisplayName = "Direct Light Only (zero ambient)"))
	bool bValidationDirectLightOnly = false;

	/** High-contrast shadow test: shadow-side ambient scaled by ValidationHighContrastShadowScale and the shadow term scale (View[286].z) forced to 1. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Validation Toggles (not recovered)", meta = (DisplayName = "High Contrast Shadows"))
	bool bValidationHighContrast = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Validation Toggles (not recovered)", meta = (ClampMin = "0", ClampMax = "1", EditCondition = "bValidationHighContrast"))
	float ValidationHighContrastShadowScale = 0.25f;

	/** Rotating light-direction test: MainLight yaw speed in degrees per second (0 = off). Runs in realtime editor viewports and in game. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Validation Toggles (not recovered)", meta = (DisplayName = "Rotate Main Light (deg/s)"))
	float ValidationLightRotationDegreesPerSecond = 0.f;

	/**
	 * View[301] = KuroWeatherDataAsset CharacterSetting.CharacterRimColor (HDR; BP_GlobalGI.UpdateCharacterGI with
	 * CustomCharacterLightingIntensity = 1). Rim colour of FKuroToonShadingPS â€” not the main light colour.
	 * research/shaders/ToonLightingData.md. Default = indoor preset DA_IM_yanjiusuo.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Rim")
	FLinearColor RimColor = FLinearColor(2.f, 2.f, 2.f);

	/** View[302] = KuroCharRimDir = EulerToForward(pitch 30, yaw LightHorizontalAngle). Used when bRimDirectionFromMainLight is false. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Rim")
	FVector RimDirection = FVector(0.616936, 0.607775, 0.5);

	/** Derive the rim direction like Kuro (30 deg elevation) along the main light's horizontal direction (yaw source inferred). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Rim")
	bool bRimDirectionFromMainLight = true;

	/** View[286].z: scales the decoded main-light shadow term (t5), also on non-toon pixels (ToonShadow.md). Named AO originally. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") float AOStrength = 1.f;                         // View[286].z
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") bool bHSVIndirect = false;                     // View[289].x
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") bool bGITint = false;                          // View[289].y
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FVector AmbientParams = FVector(1, 1, 0);      // View[298]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FLinearColor AmbientA_Near = FLinearColor(0.3f, 0.3f, 0.32f); // View[306]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FLinearColor AmbientA_Far = FLinearColor(0.3f, 0.3f, 0.32f);  // View[299]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FLinearColor AmbientB_Near = FLinearColor(0.5f, 0.5f, 0.52f); // View[305]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FLinearColor AmbientB_Far = FLinearColor(0.5f, 0.5f, 0.52f);  // View[300]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FVector AORemap = FVector(0, 1, 1);            // View[303]
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Ambient") FVector2D DepthGradient = FVector2D(10000, 1); // View[304]

	/** Rim pass constants (cbPass[0..1] of FKuroToonShadingPS). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Rim") float RimWidthScale = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Rim") FLinearColor RimTint = FLinearColor::White;

	/** Up to 16 lights, matching the compiled loop bound (ToonLocalLightData holds 144 float4 + count). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Local Lights")
	TArray<FWuwaToonLocalLight> LocalLights;

	/**
	 * Character actors rendered into the toon depth target. An entry may also be any actor whose child actors
	 * (ChildActorComponent, e.g. the generated BP_WuwaChar_* character Blueprints) are AWuwaToonCharacterActors: those are managed too.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Depth")
	TArray<TObjectPtr<AActor>> Characters;

	/** Also manage every AWuwaToonCharacterActor in the world (incl. child actors), after the Characters entries. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Depth")
	bool bAutoCollectCharacters = false;

	/** Toon characters actually managed this frame (Characters expanded by child actors, plus auto-collected ones). */
	UPROPERTY(VisibleAnywhere, Transient, Category = "WuwaToon|Toon Depth")
	TArray<TObjectPtr<AWuwaToonCharacterActor>> ManagedCharacters;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Depth")
	TObjectPtr<UTextureRenderTarget2D> ToonDepthTarget;

	UPROPERTY(VisibleAnywhere, Category = "WuwaToon|Toon Depth")
	TObjectPtr<USceneCaptureComponent2D> ToonDepthCapture;

	/**
	 * Light-space toon shadow (stands in for FKuroToonShadingPS t5 LightAttenuation). Kuro's default copies the
	 * CSM/ray-traced screen shadow mask, which a launcher-build plugin cannot read; this reproduces Kuro's
	 * per-object toon shadow method instead: an orthographic depth view along the main light around the characters.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Shadow")
	TObjectPtr<UTextureRenderTarget2D> ToonShadowTarget;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Shadow")
	float ShadowOrthoWidth = 400.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Shadow")
	float ShadowDistance = 2000.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Shadow")
	float ShadowDepthBias = 2.f;

	/**
	 * Centre the light-space toon shadow on the character group (one top-level actor and its child actors) nearest the
	 * current view's line of sight instead of on all characters' bounds. For showcase lineups wider than ShadowOrthoWidth.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Toon Shadow")
	bool bShadowFocusOnView = false;

	UPROPERTY(VisibleAnywhere, Category = "WuwaToon|Toon Shadow")
	TObjectPtr<USceneCaptureComponent2D> ToonShadowCapture;

	/**
	 * Kuro HET / HETA / face-shadow-mesh emulation (research/shaders/HETPasses.md §4). Two view-matched captures of the
	 * characters' capture-only follower meshes (AWuwaToonCharacterActor): RGB = mask emissive, A = scene depth (cm).
	 * The bangs (HETCut master), the translucent HETA copy and the 180-queue masters sample them at their own screen UV.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes")
	TObjectPtr<UTextureRenderTarget2D> HETMaskTarget;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes")
	TObjectPtr<UTextureRenderTarget2D> FaceShadowMaskTarget;

	UPROPERTY(VisibleAnywhere, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USceneCaptureComponent2D> HETCapture;

	UPROPERTY(VisibleAnywhere, Category = "WuwaToon|Extra Passes")
	TObjectPtr<USceneCaptureComponent2D> FaceShadowCapture;

	/** Bangs are cut only where the HET surface lies 0..HETMaxBehind cm behind them (plugin guard; Kuro's stencil is global). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") float HETMaxBehind = 30.f;
	/** Scales the HETA per-texel opacity saturate(MainTex.a * OpacityIntensity); Kuro's blend is Unknown (calibration knob). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") float HETAOpacityScale = 1.f;
	/** FS applies where the shifted bangs shell is no more than FSDepthEps cm behind the receiver pixel. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes") float FSDepthEps = 0.5f;

	/**
	 * Kuro's FS shell casts shadows (M_FaceShadowMesh carries ShadowDepth VS/PS and no bDisableCastDynamicShadows, unlike
	 * M_WriteStencil; MI_..Face_FS sets bCastRayTracedShadows; HETPasses.md §1.4). When true the active shell is drawn into
	 * the light-space toon shadow capture (the plugin's stand-in for the CSM that toon pixels receive).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Extra Passes")
	bool bFaceShadowShellCastsToonShadow = true;

	/** Assigns each character in Characters a unique mask ID (CPD 35, UWuwaToonCharacterComponent::MaskID); explicit IDs are kept. */
	UFUNCTION(BlueprintCallable, Category = "WuwaToon|Extra Passes")
	void AssignCharacterMaskIds();

	/**
	 * Re-apply the exact FSceneView of the viewport the captures were aligned to, in SetupView, right before the deferred
	 * captures render (editor: removes the lag of fly-camera movement applied after the world tick).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "WuwaToon|Captures")
	bool bLateViewAlignment = true;

	/** View source the captures used last: PlayerCamera / EditorViewport / RenderedView (fallback) / LateSetupView / None. */
	UPROPERTY(VisibleAnywhere, Transient, Category = "WuwaToon|Captures")
	FName CaptureViewSource;

	virtual void Tick(float DeltaSeconds) override;
	virtual bool ShouldTickIfViewportsOnly() const override { return true; }
	virtual void BeginPlay() override;
	virtual void OnConstruction(const FTransform& Transform) override;
	virtual void PostRegisterAllComponents() override;
	virtual void PostUnregisterAllComponents() override;
#if WITH_EDITOR
	virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif

private:
	void PushParameters() const;
	void SyncToonDepthCapture();
	void SyncToonShadowCapture();
	void SyncExtraPassCaptures();
	bool SyncMaskCapture(USceneCaptureComponent2D* Capture, UTextureRenderTarget2D* Target, const TArray<UPrimitiveComponent*>& Show, bool& bWasActive);
	void AlignCapture(USceneCaptureComponent2D* Capture, UTextureRenderTarget2D* Target, const FWuwaToonTrackedView& View) const;
	void HandlePrimaryViewSetup(const FSceneViewFamily& Family, const FSceneView& View, const FWuwaToonTrackedView& Tracked);
	void UpdateTickPrerequisites();
	void RefreshManagedCharacters();
	FBox FocusedShadowBounds() const;

	bool bHETActive = false;
	bool bFaceShadowActive = false;
	/** View resolved this tick (current frame) and used for every view-matched capture. */
	FWuwaToonTrackedView CurrentView;
	FDelegateHandle PrimaryViewSetupHandle;
};
