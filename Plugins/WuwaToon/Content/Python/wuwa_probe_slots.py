"""Per-section probe of one showcase Blueprint (WUWA_PROBE=<cfg json>): find which section / pass draws a wrong colour.

cfg: {'bp': actor label in L_CharacterShowcase, 'part': child actor component (default Body), 'out': dir, 'result': json,
      'res': [w, h], 'bone': framing bone (default Bip001Head), 'dist': cm}
Shots (<out>/<name>.png): base; body_slot<i>_<slot> (that body slot set to M_Wuwa_Hidden); no_<Follower> (that follower
component hidden: OutlineMesh, HETAMesh, ...). Materials / visibility are restored after each shot; the map is not saved.
"""
import os
import traceback

import unreal

import wuwa_roster_common as C

MAP = '/Game/WuWa/Showcase/L_CharacterShowcase'
HIDDEN = '/Game/WuWa/Materials/Masters/M_Wuwa_Hidden'
FOLLOWERS = ('OutlineMesh', 'HETAMesh', 'HETMaskMesh', 'HETOccluderMesh', 'FaceShadowMesh')


class Probe:
    def __init__(self, cfg):
        self.cfg, self.busy, self.f, self.i = cfg, False, 0, -1
        w, h = cfg.get('res', [512, 512])
        unreal.EditorLoadingAndSavingUtils.load_map(MAP)
        self.world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.SystemLibrary.execute_console_command(self.world, 'r.TextureStreaming 0')
        actor = next(a for a in unreal.GameplayStatics.get_all_actors_of_class(self.world, unreal.Actor)
                     if a.get_actor_label() == cfg['bp'])
        part = cfg.get('part', 'Body')
        self.toon = next(c.get_editor_property('child_actor') for c in actor.get_components_by_class(unreal.ChildActorComponent)
                         if str(c.get_name()) == part)
        self.body = self.toon.skeletal_mesh_component
        self.hidden = unreal.load_asset(HIDDEN)
        self.followers = {str(c.get_name()): c for c in self.toon.get_components_by_class(unreal.SkeletalMeshComponent)
                          if str(c.get_name()) in FOLLOWERS}
        bone = cfg.get('bone', 'Bip001Head')
        head = self.body.get_socket_location(bone) if self.body.does_socket_exist(bone) else self.body.bounds.origin
        dist = float(cfg.get('dist', 70.0))
        self.cap = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
            unreal.SceneCapture2D, unreal.Vector(head.x, head.y - dist, head.z), unreal.Rotator(roll=0, pitch=0, yaw=90))
        c = self.cap.capture_component2d
        c.set_editor_property('texture_target', unreal.RenderingLibrary.create_render_target2d(
            self.world, w, h, unreal.TextureRenderTargetFormat.RTF_RGBA8))
        c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        c.set_editor_property('capture_every_frame', False)
        c.set_editor_property('capture_on_movement', False)
        c.set_editor_property('always_persist_rendering_state', True)
        c.set_editor_property('fov_angle', 30.0)
        c.set_editor_property('show_flag_settings', [unreal.EngineShowFlagsSetting(show_flag_name=n, enabled=False)
                                                     for n in ('TemporalAA', 'MotionBlur', 'EyeAdaptation')])
        pp = c.get_editor_property('post_process_settings')
        pp.set_editor_property('override_auto_exposure_method', True)
        pp.set_editor_property('auto_exposure_method', unreal.AutoExposureMethod.AEM_MANUAL)
        pp.set_editor_property('override_auto_exposure_apply_physical_camera_exposure', True)
        pp.set_editor_property('auto_exposure_apply_physical_camera_exposure', False)
        pp.set_editor_property('override_auto_exposure_bias', True)
        pp.set_editor_property('auto_exposure_bias', 1.5)
        c.set_editor_property('post_process_settings', pp)
        names = [str(n) for n in self.body.get_material_slot_names()]
        self.shots = [('base', None, None)]
        self.shots += [(f'body_slot{i}_{n}', 'slot', i) for i, n in enumerate(names)]
        self.shots += [(f'no_{n}', 'follower', n) for n in self.followers]
        # material variants: {'name', 'slot', 'material' (path; default the slot's own), 'scalars', 'textures' {param: path}}
        self.shots += [(v['name'], 'variant', v) for v in cfg.get('variants') or []]
        if cfg.get('variants_only'):
            self.shots = [s for s in self.shots if s[1] in (None, 'variant')]
        self.res = {'bp': cfg['bp'], 'part': part, 'slots': names,
                    'materials': [m.get_path_name() if m else None for m in self.body.get_materials()],
                    'followers': {n: [m.get_name() if m else None for m in f.get_materials()] for n, f in self.followers.items()},
                    'follower_visible': {n: bool(f.is_visible()) for n, f in self.followers.items()}, 'shots': [], 'errors': []}
        # fresh texture imports for the variants (wuwa_roster_common.import_textures items)
        if cfg.get('import_textures'):
            n, errs = C.import_textures(cfg['import_textures'], skip_existing=False)
            C.log(f'probe: imported {n} textures, errors {errs}')
        # textures to rebuild before the shots (re-set a build setting: PostEditChange rebuilds the platform data)
        for p in cfg.get('rebuild_textures') or []:
            t = unreal.load_asset(p)
            t.set_editor_property('compression_settings', t.get_editor_property('compression_settings'))
            C.log(f'probe: rebuilt texture {p}')
        os.makedirs(cfg['out'], exist_ok=True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def apply(self, kind, arg, on):
        if kind == 'slot':
            self.body.set_material(arg, self.hidden if on else self.saved)
        elif kind == 'variant':
            if not on:
                self.body.set_material(arg['slot'], self.saved)
                return
            src = unreal.load_asset(arg['material']) if arg.get('material') else self.saved
            mid = self.body.create_dynamic_material_instance(arg['slot'], src)
            for p, x in (arg.get('scalars') or {}).items():
                mid.set_scalar_parameter_value(p, float(x))
            for p, t in (arg.get('textures') or {}).items():
                mid.set_texture_parameter_value(p, unreal.load_asset(t))
            self.body.set_material(arg['slot'], mid)
        elif kind == 'follower':
            self.followers[arg].set_visibility(not on)

    def tick(self, _dt):
        if self.busy:
            return
        self.busy = True
        try:
            self.step()
        except Exception:
            self.res['errors'].append(traceback.format_exc()[-1500:])
            self.finish()
        finally:
            self.busy = False

    def step(self):
        self.f += 1
        if self.i < 0:
            if self.f >= int(self.cfg.get('warmup', 200)):   # warm-up: toon environment / captures settled
                self.i, self.f = 0, 0
            return
        if self.i >= len(self.shots):
            self.finish()
            return
        name, kind, arg = self.shots[self.i]
        c = self.cap.capture_component2d
        if self.f == 1:
            if kind in ('slot', 'variant'):
                self.saved = self.body.get_material(arg if kind == 'slot' else arg['slot'])
            self.apply(kind, arg, True)
        elif self.f == 4:
            c.capture_scene()
        elif self.f == 6:
            c.capture_scene()
            unreal.RenderingLibrary.export_render_target(self.world, c.get_editor_property('texture_target'),
                                                         self.cfg['out'], name + '.png')
            self.apply(kind, arg, False)
            self.res['shots'].append(name)
            self.i, self.f = self.i + 1, 0

    def finish(self):
        unreal.unregister_slate_post_tick_callback(self.handle)
        C.jsave(self.cfg['result'], self.res)
        C.log(f"probe {self.cfg['bp']}: {len(self.res['shots'])} shots, errors {len(self.res['errors'])}")
        unreal.SystemLibrary.quit_editor()


unreal.EditorPythonScripting.set_keep_python_script_alive(True)
try:
    PROBE = Probe(C.jload(os.environ['WUWA_PROBE']))
except Exception:
    unreal.log_error('[WuwaRoster] ' + traceback.format_exc())
    unreal.SystemLibrary.quit_editor()
