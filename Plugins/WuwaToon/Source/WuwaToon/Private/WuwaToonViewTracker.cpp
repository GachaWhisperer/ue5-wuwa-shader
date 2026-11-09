#include "WuwaToonViewTracker.h"

#include "Camera/CameraTypes.h"
#include "Camera/PlayerCameraManager.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "SceneInterface.h"
#include "SceneView.h"
#include "UnrealClient.h"

#if WITH_EDITOR
#include "Camera/CameraComponent.h"
#include "Editor.h"
#include "LevelEditorViewport.h"
#include "Settings/LevelEditorViewportSettings.h"
#endif

namespace
{
	FCriticalSection GTrackedViewLock;
	FWuwaToonTrackedView GTrackedView;

	float HorizontalFOVFromProjection(const FMatrix& Proj)
	{
		return FMath::RadiansToDegrees(2.f * FMath::Atan(1.f / float(Proj.M[0][0])));
	}

	FWuwaToonTrackedView MakeView(const FVector& Location, const FRotator& Rotation, const FMatrix& Proj, const FIntPoint& Size,
		EWuwaToonViewSource Source, const FRenderTarget* RenderTarget)
	{
		FWuwaToonTrackedView V;
		V.bValid = Size.X > 0 && Size.Y > 0 && Proj.M[3][3] < 1.f;   // perspective only (the masks are perspective-only too)
		V.Location = Location;
		V.Rotation = Rotation;
		V.HorizontalFOVDegrees = HorizontalFOVFromProjection(Proj);
		V.Size = Size;
		V.Source = Source;
		V.RenderTarget = RenderTarget;
		return V;
	}

	/** Game / PIE: what ULocalPlayer::GetViewPoint + GetProjectionData will use for this frame's main view. */
	bool ResolvePlayerCamera(const UWorld* World, FWuwaToonTrackedView& Out)
	{
		for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
		{
			const APlayerController* PC = It->Get();
			if (!PC || !PC->IsLocalController() || !PC->PlayerCameraManager)
			{
				continue;
			}
			const ULocalPlayer* LP = PC->GetLocalPlayer();
			FViewport* Viewport = (LP && LP->ViewportClient) ? LP->ViewportClient->Viewport : nullptr;
			if (!Viewport || Viewport->GetSizeXY().X <= 0 || Viewport->GetSizeXY().Y <= 0 || LP->Size.X <= 0.f || LP->Size.Y <= 0.f)
			{
				continue;
			}
			// Camera cache of this frame (UpdateCameraManager runs before TG_PostUpdateWork), FOV as ULocalPlayer::GetViewPoint.
			FMinimalViewInfo ViewInfo = PC->PlayerCameraManager->GetCameraCacheView();
			ViewInfo.FOV = PC->PlayerCameraManager->GetFOVAngle();
			if (ViewInfo.ProjectionMode != ECameraProjectionMode::Perspective)
			{
				continue;
			}
			const FIntPoint VS = Viewport->GetSizeXY();
			const FIntPoint Min = FIntPoint(FMath::TruncToInt(LP->Origin.X * VS.X), FMath::TruncToInt(LP->Origin.Y * VS.Y)) + Viewport->GetInitialPositionXY();
			const FIntPoint Size(FMath::TruncToInt(LP->Size.X * VS.X), FMath::TruncToInt(LP->Size.Y * VS.Y));
			FSceneViewProjectionData Projection;
			Projection.SetViewRectangle(FIntRect(Min, Min + Size));
			// Same call as ULocalPlayer::GetProjectionData (axis constraint, letterboxing for bConstrainAspectRatio).
			FMinimalViewInfo::CalculateProjectionMatrixGivenView(ViewInfo, LP->AspectRatioAxisConstraint, Viewport, Projection);
			Out = MakeView(ViewInfo.Location, ViewInfo.Rotation, Projection.ProjectionMatrix, Projection.GetConstrainedViewRect().Size(),
				EWuwaToonViewSource::PlayerCamera, Viewport);
			return Out.bValid;
		}
		return false;
	}

#if WITH_EDITOR
	/** Editor / simulate: the active perspective level viewport showing World, mirroring FEditorViewportClient::CalcSceneView. */
	bool ResolveEditorViewport(const UWorld* World, FWuwaToonTrackedView& Out)
	{
		if (!GEditor)
		{
			return false;
		}
		auto Usable = [World](const FLevelEditorViewportClient* C)
		{
			return C && C->Viewport && C->IsPerspective() && C->GetWorld() == World
				&& C->Viewport->GetSizeXY().X > 0 && C->Viewport->GetSizeXY().Y > 0;
		};
		FLevelEditorViewportClient* Client = nullptr;
		if (Usable(GCurrentLevelEditingViewportClient))
		{
			Client = GCurrentLevelEditingViewportClient;
		}
		else if (Usable(GLastKeyLevelEditingViewportClient))
		{
			Client = GLastKeyLevelEditingViewportClient;
		}
		else
		{
			for (FLevelEditorViewportClient* C : GEditor->GetLevelViewportClients())
			{
				if (Usable(C) && C->IsVisible())
				{
					Client = C;
					break;
				}
			}
		}
		if (!Client)
		{
			return false;
		}
		const FIntPoint VS = Client->Viewport->GetSizeXY();
		const EAspectRatioAxisConstraint AxisSetting = GetDefault<ULevelEditorViewportSettings>()->AspectRatioAxisConstraint;
		if (UCameraComponent* Camera = Client->GetCameraComponentForView())
		{
			// Piloted / cinematic camera: CalcSceneView uses the camera's FMinimalViewInfo (FOV, constrained aspect).
			FMinimalViewInfo ViewInfo;
			Camera->GetCameraView(0.f, ViewInfo);
			ViewInfo.Location = Client->GetViewLocation();
			ViewInfo.Rotation = Client->GetViewRotation();
			FSceneViewProjectionData Projection;
			Projection.SetViewRectangle(FIntRect(FIntPoint::ZeroValue, VS));
			FMinimalViewInfo::CalculateProjectionMatrixGivenView(ViewInfo, ViewInfo.AspectRatioAxisConstraint.Get(AxisSetting),
				Client->Viewport, Projection);
			Out = MakeView(ViewInfo.Location, ViewInfo.Rotation, Projection.ProjectionMatrix, Projection.GetConstrainedViewRect().Size(),
				EWuwaToonViewSource::EditorViewport, Client->Viewport);
			return Out.bValid;
		}
		// Free perspective camera: FReversedZPerspectiveMatrix(MatrixFOV, MatrixFOV, XMul, YMul) as in CalcSceneView.
		const float ViewFOV = FMath::Max(0.001f, Client->ViewFOV);
		const bool bMaintainXFOV = (VS.X > VS.Y && AxisSetting == AspectRatio_MajorAxisFOV) || AxisSetting == AspectRatio_MaintainXFOV;
		float HFOV = ViewFOV;
		if (!bMaintainXFOV)
		{
			const float HalfX = FMath::DegreesToRadians(ViewFOV * 0.5f);
			const float MatrixFOV = Client->AspectRatio != 0.f ? FMath::Atan(FMath::Tan(HalfX) / Client->AspectRatio) : HalfX;
			const float XAxisMultiplier = float(VS.Y) / float(VS.X);
			HFOV = FMath::RadiansToDegrees(2.f * FMath::Atan(FMath::Tan(MatrixFOV) / XAxisMultiplier));
		}
		Out.bValid = true;
		Out.Location = Client->GetViewLocation();
		Out.Rotation = Client->GetViewRotation();
		Out.HorizontalFOVDegrees = HFOV;
		Out.Size = VS;
		Out.Source = EWuwaToonViewSource::EditorViewport;
		Out.RenderTarget = Client->Viewport;
		return true;
	}
#endif
}

FWuwaToonTrackedView FWuwaToonViewTracker::Get()
{
	FScopeLock Lock(&GTrackedViewLock);
	return GTrackedView;
}

FWuwaToonTrackedView FWuwaToonViewTracker::ResolveCurrent(const UWorld* World)
{
	FWuwaToonTrackedView View;
	if (World && IsInGameThread())
	{
		if (World->IsGameWorld() && ResolvePlayerCamera(World, View))
		{
			return View;
		}
#if WITH_EDITOR
		if (ResolveEditorViewport(World, View))
		{
			return View;
		}
#endif
	}
	View = Get();
	View.Source = View.bValid ? EWuwaToonViewSource::RenderedView : EWuwaToonViewSource::None;
	View.RenderTarget = nullptr;
	return View;
}

FWuwaToonOnPrimaryViewSetup& FWuwaToonViewTracker::OnPrimaryViewSetup()
{
	static FWuwaToonOnPrimaryViewSetup Delegate;
	return Delegate;
}

void FWuwaToonViewTracker::SetupView(FSceneViewFamily& InViewFamily, FSceneView& InView)
{
	// Scene captures (including our own toon depth capture) must not overwrite the tracked main view.
	if (InView.bIsSceneCapture || InView.bIsReflectionCapture || InView.bIsPlanarReflection)
	{
		return;
	}
	// Asset editors / thumbnails render preview worlds (any size, e.g. tall material previews): never track those.
	const UWorld* World = InViewFamily.Scene ? InViewFamily.Scene->GetWorld() : nullptr;
	if (!World || (World->WorldType != EWorldType::Game && World->WorldType != EWorldType::PIE && World->WorldType != EWorldType::Editor))
	{
		return;
	}
	const FWuwaToonTrackedView Tracked = MakeView(InView.ViewMatrices.GetViewOrigin(), InView.ViewRotation,
		InView.ViewMatrices.GetViewToClipNoAA(), InView.UnscaledViewRect.Size(), EWuwaToonViewSource::LateSetupView,
		InViewFamily.RenderTarget);
	{
		FScopeLock Lock(&GTrackedViewLock);
		GTrackedView = Tracked;
	}
	// SetupView runs on the game thread from CalcSceneView, before BeginRenderingViewFamilies renders the deferred captures.
	if (IsInGameThread())
	{
		OnPrimaryViewSetup().Broadcast(InViewFamily, InView, Tracked);
	}
}
