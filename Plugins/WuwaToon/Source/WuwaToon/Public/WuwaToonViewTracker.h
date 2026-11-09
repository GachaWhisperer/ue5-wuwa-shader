#pragma once

#include "SceneViewExtension.h"

class FRenderTarget;
class UWorld;

/** Where a view used to align the screen-space captures came from. */
enum class EWuwaToonViewSource : uint8
{
	None,
	PlayerCamera,     // local APlayerCameraManager camera cache of this frame (game / PIE; read in TG_PostUpdateWork)
	EditorViewport,   // active perspective level-editor viewport client (editor / simulate)
	RenderedView,     // last primary view the renderer set up (FWuwaToonViewTracker fallback; one frame old at tick time)
	LateSetupView,    // the same viewport's FSceneView, re-applied in ISceneViewExtension::SetupView before the captures render
};

/** A primary (non scene-capture) view: everything a view-matched capture needs. */
struct FWuwaToonTrackedView
{
	bool bValid = false;
	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	/** Horizontal FOV derived from the view's projection matrix (covers MaintainX/Y-FOV and constrained aspect). */
	float HorizontalFOVDegrees = 90.f;
	/** Unscaled (pre screen-percentage) view rect size = capture render target size. */
	FIntPoint Size = FIntPoint(1920, 1080);
	EWuwaToonViewSource Source = EWuwaToonViewSource::None;
	/** Viewport the view is drawn into (key for the late re-alignment); null for the fallback. */
	const FRenderTarget* RenderTarget = nullptr;
};

DECLARE_MULTICAST_DELEGATE_ThreeParams(FWuwaToonOnPrimaryViewSetup, const FSceneViewFamily& /*Family*/, const FSceneView& /*View*/,
	const FWuwaToonTrackedView& /*Tracked*/);

/**
 * Tracks the primary view and resolves the CURRENT frame's view for the toon depth / HET / FS captures.
 *
 * Frame order (UE 5.8, LevelTick.cpp / EditorEngine.cpp / SceneRendering.cpp):
 *   game:   ... TG_PostPhysics -> PlayerController::UpdateCameraManager -> TG_PostUpdateWork (our ticks) -> Draw:
 *           CalcSceneView (SetupView) -> BeginRenderingViewFamilies -> deferred scene captures -> main view.
 *   editor: world tick (our ticks) -> FEditorViewportClient::Tick (fly-camera movement) -> Draw (as above).
 * ResolveCurrent() is exact in game at tick time; in the editor it reads the viewport client's current transform, and
 * OnPrimaryViewSetup lets the environment re-apply the exact FSceneView of the same viewport right before the captures
 * render (removes the residual lag of keyboard fly movement applied after the world tick).
 */
class FWuwaToonViewTracker : public FSceneViewExtensionBase
{
public:
	FWuwaToonViewTracker(const FAutoRegister& AutoRegister) : FSceneViewExtensionBase(AutoRegister) {}

	/** Last primary view the renderer set up (any world). Fallback only: one frame old when read during a tick. */
	static FWuwaToonTrackedView Get();

	/**
	 * Current-frame primary view of World: the local player's camera (game / PIE; call in TG_PostUpdateWork or later),
	 * else the active perspective level-editor viewport showing World (editor builds), else Get().
	 */
	static FWuwaToonTrackedView ResolveCurrent(const UWorld* World);

	/** Broadcast on the game thread for every primary view in SetupView (before that family's scene captures render). */
	static FWuwaToonOnPrimaryViewSetup& OnPrimaryViewSetup();

	virtual void SetupViewFamily(FSceneViewFamily& InViewFamily) override {}
	virtual void SetupView(FSceneViewFamily& InViewFamily, FSceneView& InView) override;
	virtual void BeginRenderViewFamily(FSceneViewFamily& InViewFamily) override {}
};
