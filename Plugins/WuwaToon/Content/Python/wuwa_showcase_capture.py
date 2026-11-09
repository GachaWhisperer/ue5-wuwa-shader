"""Showcase captures (WUWA_SHOWCASE_CAPTURE=<cfg json>): one SceneCapture2D shot per Blueprint instance in L_CharacterShowcase.

cfg: {'out': dir, 'result': json, 'res': [w, h], 'warmup': frames, 'initial_warmup': frames, 'fov': deg, 'exposure_bias': ev,
      'only': [bp names], 'phases': [{'name': 'masked', 'hidden': 'masked'}, {'name': 'additive', 'hidden': 'additive'}]}
Each phase optionally rebuilds M_Wuwa_Hidden first, saved in place ('additive': wuwa_generate_materials.invisible_material;
'masked': the former zero-opacity masked version, for A/B only; run the additive phase last), waits `warmup` frames
(`initial_warmup` before the first phase: textures still settle for ~1 min after the map loads and draw black until then),
then frames every Blueprint instance (bounds of its Body child actor, camera on -Y looking +Y) and
writes <out>/<phase>/<bp>.png (final colour LDR, manual exposure, no temporal AA). The map is not saved. Driver:
tools/roster/showcase_capture.py.
"""
import math
import os
import traceback

import unreal

os.environ['WUWA_GENERATE_AS_LIBRARY'] = '1'
import wuwa_generate_materials as G   # noqa: E402
import wuwa_roster_common as C        # noqa: E402

MAP = '/Game/WuWa/Showcase/L_CharacterShowcase'
HIDDEN = '/Game/WuWa/Materials/Masters/M_Wuwa_Hidden'


def legacy_masked_hidden():
    """The former M_Wuwa_Hidden (unlit masked, opacity mask 0), rebuilt in place for A/B captures only."""
    mat = G.W.new_material(HIDDEN, blend=unreal.BlendMode.BLEND_MASKED)
    zero = G.W.node(mat, unreal.MaterialExpressionConstant, -300, 0, r=0.0)
    G.W.MEL.connect_material_property(zero, '', unreal.MaterialProperty.MP_OPACITY_MASK)
    G.W.compile_and_report(mat)
    return mat


class Capture:
    def __init__(self, cfg):
        self.cfg = cfg
        self.w, self.h = cfg.get('res', [384, 640])
        self.warm = int(cfg.get('warmup', 240))
        self.fov = float(cfg.get('fov', 40.0))
        self.res = {'phases': {}, 'errors': []}
        unreal.EditorLoadingAndSavingUtils.load_map(MAP)
        self.world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.SystemLibrary.execute_console_command(self.world, 'r.TextureStreaming 0')
        only = set(cfg.get('only') or [])
        self.targets = sorted([a for a in unreal.GameplayStatics.get_all_actors_of_class(self.world, unreal.Actor)
                               if a.get_actor_label().startswith('BP_WuwaChar_') and (not only or a.get_actor_label() in only)],
                              key=lambda a: a.get_actor_label())
        self.cap = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
            unreal.SceneCapture2D, unreal.Vector(0, -500, 100), unreal.Rotator(0, 0, 90))
        c = self.cap.capture_component2d
        c.set_editor_property('texture_target', unreal.RenderingLibrary.create_render_target2d(
            self.world, self.w, self.h, unreal.TextureRenderTargetFormat.RTF_RGBA8))
        c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        c.set_editor_property('capture_every_frame', False)
        c.set_editor_property('capture_on_movement', False)
        c.set_editor_property('always_persist_rendering_state', True)
        c.set_editor_property('fov_angle', self.fov)
        c.set_editor_property('show_flag_settings', [unreal.EngineShowFlagsSetting(show_flag_name=n, enabled=False)
                                                     for n in ('TemporalAA', 'MotionBlur', 'EyeAdaptation')])
        pp = c.get_editor_property('post_process_settings')
        pp.set_editor_property('override_auto_exposure_method', True)
        pp.set_editor_property('auto_exposure_method', unreal.AutoExposureMethod.AEM_MANUAL)
        pp.set_editor_property('override_auto_exposure_apply_physical_camera_exposure', True)
        pp.set_editor_property('auto_exposure_apply_physical_camera_exposure', False)
        pp.set_editor_property('override_auto_exposure_bias', True)
        pp.set_editor_property('auto_exposure_bias', float(cfg.get('exposure_bias', 0.0)))
        c.set_editor_property('post_process_settings', pp)
        c.set_editor_property('post_process_blend_weight', 1.0)
        self.phases = list(cfg['phases'])
        self.pi, self.ti, self.f, self.state, self.busy = 0, 0, 0, 'start', False
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def aim(self, a):
        # frame the body (hidden skill props would inflate the whole actor's bounds)
        body = next((c.get_editor_property('child_actor') for c in a.get_components_by_class(unreal.ChildActorComponent)
                     if str(c.get_name()) == 'Body'), None) or a
        origin, ext = body.get_actor_bounds(False)
        # fov_angle is horizontal: vertical half-angle = atan(tan(h/2) * h/w)
        vhalf = math.atan(math.tan(math.radians(self.fov / 2)) * self.h / self.w)
        hhalf = math.radians(self.fov / 2)
        dist = max(ext.z * 1.08 / math.tan(vhalf), ext.x * 1.08 / math.tan(hhalf), 60.0) + ext.y
        self.cap.set_actor_location_and_rotation(unreal.Vector(origin.x, origin.y - dist, origin.z),
                                                 unreal.Rotator(roll=0, pitch=0, yaw=90), False, False)

    def tick(self, _dt):
        if self.busy:
            return   # material compile / save pump Slate, which re-enters this callback
        self.busy = True
        try:
            self.step()
        except Exception:
            self.res['errors'].append(traceback.format_exc()[-1500:])
            C.warn(traceback.format_exc())
            self.finish()
        finally:
            self.busy = False

    def step(self):
        self.f += 1
        if self.pi >= len(self.phases):
            self.finish()
            return
        ph = self.phases[self.pi]
        out = os.path.join(self.cfg['out'], ph['name'])
        if self.state == 'start':
            if ph.get('hidden') == 'masked':
                legacy_masked_hidden()
            elif ph.get('hidden') == 'additive' or ph.get('rebuild_hidden'):
                G.invisible_material()
            hidden = unreal.load_asset(HIDDEN)
            self.res['phases'][ph['name']] = {'hidden_blend_mode': str(hidden.get_editor_property('blend_mode')),
                                              'hidden_shading_model': str(hidden.get_editor_property('shading_model')),
                                              'shots': []}
            os.makedirs(out, exist_ok=True)
            self.state, self.f = 'warm', 0
        elif self.state == 'warm' and self.f >= (int(self.cfg.get('initial_warmup', self.warm)) if self.pi == 0 else self.warm):
            self.state, self.f = 'aim', 0
        elif self.state == 'aim':
            if self.ti >= len(self.targets):
                self.pi, self.ti, self.state = self.pi + 1, 0, 'start'
                return
            self.aim(self.targets[self.ti])
            self.cap.capture_component2d.capture_scene()
            self.state, self.f = 'shoot', 0
        elif self.state == 'shoot' and self.f >= 2:
            c = self.cap.capture_component2d
            c.capture_scene()   # second capture: view state (shadow / toon captures) settled on the new framing
            name = self.targets[self.ti].get_actor_label()
            unreal.RenderingLibrary.export_render_target(self.world, c.get_editor_property('texture_target'), out, name + '.png')
            self.res['phases'][ph['name']]['shots'].append(name)
            self.ti += 1
            self.state = 'aim'

    def finish(self):
        unreal.unregister_slate_post_tick_callback(self.handle)
        self.res['targets'] = len(self.targets)
        C.jsave(self.cfg['result'], self.res)
        C.log(f"showcase capture: {len(self.targets)} targets, phases "
              + ', '.join(f"{k} {len(v['shots'])} shots ({v['hidden_blend_mode']})" for k, v in self.res['phases'].items())
              + f", errors {len(self.res['errors'])}")
        unreal.SystemLibrary.quit_editor()


unreal.EditorPythonScripting.set_keep_python_script_alive(True)
try:
    CAPTURE = Capture(C.jload(os.environ['WUWA_SHOWCASE_CAPTURE']))
except Exception:
    unreal.log_error('[WuwaRoster] ' + traceback.format_exc())
    unreal.SystemLibrary.quit_editor()
