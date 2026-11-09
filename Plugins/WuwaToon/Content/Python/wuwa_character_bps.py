"""Character showcase Blueprints + showcase level (WUWA_CHAR_BPS=<cfg json>, mode in cfg['mode']).

Plan: extracted/roster/_work/character_bps.json (tools/roster/character_bp_plan.py: one entry per character model / skin,
read from the game's own character Blueprint). Each generated Blueprint /Game/WuWa/Showcase/Blueprints/<Kind>/BP_WuwaChar_*
is an Actor with
  DefaultSceneRoot
    Body          ChildActorComponent -> AWuwaToonCharacterActor (main mesh; the game's CharacterMesh0 rotation)
    <component>   ChildActorComponent -> AWuwaToonCharacterActor per mesh component of the game BP (hair, tails, props),
                  same component name and ComponentTags; socket-attached components are baked to their reference-pose
                  socket transform on the body; components the game hides by default (bVisible=false / bHiddenInGame)
                  have their mesh hidden (toggle Visible on the child actor's mesh to show them).
Every part is a full toon actor (CPD, outline / HET / HETA / FS followers). AWuwaToonEnvironment manages the parts of a
Blueprint listed in Characters (child actors) or, with bAutoCollectCharacters, every toon actor in the level.

modes: bps (create / rebuild the Blueprints), showcase (build L_CharacterShowcase from them), verify (reload the map in a
fresh session; check every Blueprint instance's child actors and meshes against the plan).
"""
import os

import unreal

import wuwa_roster_common as C

BP_DIR = '/Game/WuWa/Showcase/Blueprints'
MAP = '/Game/WuWa/Showcase/L_CharacterShowcase'
RT_DIR = '/Game/WuWa/Validation/Yangyang'
MPC = '/Game/WuWa/Materials/MPC_WuwaToon.MPC_WuwaToon'
PRESET = 'OutdoorDaylight'
COLS, DX, DY = 12, 300.0, 600.0
SDS = None


def folder(plan):
    return f"{BP_DIR}/{'Characters' if plan['kind'] == 'character' else 'Skins'}"


def xf(d):
    return unreal.Transform(unreal.Vector(*d['location']),
                            unreal.Rotator(roll=d['rotation'][2], pitch=d['rotation'][0], yaw=d['rotation'][1]),
                            unreal.Vector(*d['scale']))


def socket_transforms(body_mesh, sockets):
    """Reference-pose transform of each socket / bone in the body mesh's component space."""
    out = {}
    if not sockets:
        return out
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0))
    try:
        comp = a.skeletal_mesh_component
        comp.set_skeletal_mesh_asset(body_mesh)
        for s in sockets:
            if comp.does_socket_exist(s):
                out[s] = comp.get_socket_transform(s, unreal.RelativeTransformSpace.RTS_COMPONENT)
    finally:
        eas.destroy_actor(a)
    return out


def handle_object(h):
    return unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h))


def add_part(bp, root_h, name, mesh, transform, visible, tags):
    h, reason = SDS.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_h, new_class=unreal.ChildActorComponent,
                                                                   blueprint_context=bp))
    if not unreal.SubobjectDataBlueprintFunctionLibrary.is_handle_valid(h):
        raise RuntimeError(f'{name}: add_new_subobject failed: {reason}')
    SDS.rename_subobject(h, unreal.Text(name))
    comp = handle_object(h)
    comp.set_child_actor_class(unreal.WuwaToonCharacterActor)
    tmpl = comp.get_editor_property('child_actor_template')
    if tmpl is None:
        raise RuntimeError(f'{name}: no child actor template')
    smc = tmpl.get_editor_property('skeletal_mesh_component')
    smc.set_skeletal_mesh_asset(mesh)
    smc.set_editor_property('visible', bool(visible))
    comp.set_editor_property('relative_location', transform.translation)
    comp.set_editor_property('relative_rotation', transform.rotation.rotator())
    comp.set_editor_property('relative_scale3d', transform.scale3d)
    comp.set_editor_property('component_tags', [unreal.Name(t) for t in tags])
    return comp


def open_bp(plan):
    """The Blueprint asset, created or (when it exists, e.g. referenced by the showcase map) emptied to its root."""
    path = f"{folder(plan)}/{plan['bp_name']}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        bp = unreal.load_asset(path)
        handles = SDS.k2_gather_subobject_data_for_blueprint(bp)
        if len(handles) > 1:
            SDS.delete_subobjects(handles[0], handles[1:], bp)
    else:
        f = unreal.BlueprintFactory()
        f.set_editor_property('parent_class', unreal.Actor)
        bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(plan['bp_name'], folder(plan), unreal.Blueprint, f)
    handles = SDS.k2_gather_subobject_data_for_blueprint(bp) if bp else []
    if not handles:
        raise RuntimeError(f'{path}: no Blueprint / root component')
    return bp, handles[0], path


def build_bp(plan):
    bp, root_h, path = open_bp(plan)
    body_mesh = unreal.load_asset(plan['body']['asset'])
    if not isinstance(body_mesh, unreal.SkeletalMesh):
        raise RuntimeError(f"body mesh {plan['body']['asset']} missing")
    body_x = xf(plan['body'])
    add_part(bp, root_h, 'Body', body_mesh, body_x, True, [])
    # frame (Blueprint space) and mesh of every placed component; a component's SCS parent is the body or another part
    frames, meshes = {'CharacterMesh0': body_x}, {'CharacterMesh0': body_mesh}
    sockets = {}   # mesh path -> {socket: component-space transform}
    pending = [c for c in plan['components']]
    parts, notes = [], []
    while pending:
        progressed = False
        for c in list(pending):
            parent = c.get('parent') or 'CharacterMesh0'
            if parent not in frames and parent in {x['name'] for x in pending}:
                continue   # parent placed first
            pending.remove(c)
            progressed = True
            mesh = unreal.load_asset(c['asset'])
            if not isinstance(mesh, unreal.SkeletalMesh):
                notes.append(f"{c['name']}: mesh {c['asset']} missing")
                continue
            if parent not in frames:
                notes.append(f"{c['name']}: parent {parent} not placed; attached to the body")
                parent = 'CharacterMesh0'
            local = xf(c)
            if c.get('socket'):
                pm = meshes[parent]
                key = pm.get_path_name()
                if key not in sockets:
                    sockets[key] = socket_transforms(pm, {x['socket'] for x in plan['components'] if x.get('socket')})
                s = sockets[key].get(c['socket'])
                if s is None:
                    notes.append(f"{c['name']}: socket {c['socket']} not on {pm.get_name()}; placed at its origin")
                else:
                    local = local.multiply(s)
            frame = local.multiply(frames[parent])
            add_part(bp, root_h, c['name'], mesh, frame, c['visible'], c.get('tags') or [])
            frames[c['name']], meshes[c['name']] = frame, mesh
            parts.append(c['name'])
        if not progressed:   # parent cycle: attach the rest to the body
            for c in pending:
                c['parent'] = 'CharacterMesh0'
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    unreal.EditorAssetLibrary.save_loaded_asset(bp, only_if_is_dirty=False)
    return {'path': path, 'parts': parts, 'notes': notes}


def mode_bps(cfg):
    plans = C.jload(cfg['plan'])
    only = set(filter(None, (cfg.get('only') or '').split(',')))
    res = {'ok': [], 'failed': {}, 'notes': {}}
    for p in plans:
        if only and p['bp_name'] not in only:
            continue
        try:
            r = build_bp(p)
            res['ok'].append(r['path'])
            if r['notes']:
                res['notes'][p['bp_name']] = r['notes']
            C.log(f"bp {p['bp_name']}: body + {len(r['parts'])} parts")
        except Exception as e:
            res['failed'][p['bp_name']] = str(e)
            C.warn(f"FAILED bp {p['bp_name']}: {e}")
        C.jsave(cfg['result'], res)
    C.log(f"bps: {len(res['ok'])} ok, {len(res['failed'])} failed")


def spawn(cls, loc=(0, 0, 0), rot=(0, 0, 0), label=None):
    a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))
    if label:
        a.set_actor_label(label)
    return a


def mode_showcase(cfg):
    plans = C.jload(cfg['plan'])
    if not unreal.EditorLoadingAndSavingUtils.new_blank_map(False):
        raise RuntimeError('new_blank_map failed')
    sun = spawn(unreal.DirectionalLight, (0, 0, 800), (-40, -30, 0), 'MainToonLight')
    sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sun.light_component.set_editor_property('intensity', 6.0)
    sky = spawn(unreal.SkyLight, (0, 0, 600), label='SkyLight')
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky.light_component.set_editor_property('real_time_capture', True)
    spawn(unreal.SkyAtmosphere, label='SkyAtmosphere')
    spawn(unreal.ExponentialHeightFog, label='HeightFog')
    groups = [('Characters', [p for p in plans if p['kind'] == 'character']), ('Skins', [p for p in plans if p['kind'] == 'skin'])]
    row, placed, missing = 0, [], []
    for gname, items in groups:
        for i, p in enumerate(items):
            r, col = row + i // COLS, i % COLS
            x, y = col * DX, r * DY
            cls = unreal.EditorAssetLibrary.load_blueprint_class(f"{folder(p)}/{p['bp_name']}")
            if not cls:
                missing.append(p['bp_name'])
                continue
            # the game BP faces +X (CharacterMesh0 yaw -90); turn every character toward the cameras at -Y
            a = spawn(cls, (x, y, 0), (0, -90, 0), p['bp_name'])
            a.set_folder_path(f'Showcase/{gname}')
            placed.append(p['bp_name'])
            lbl = spawn(unreal.TextRenderActor, (x, y - 70, 2), (90, -90, 0), f"Label_{p['bp_name']}")
            lbl.text_render.set_text(p['label'].replace('_', ' '))
            lbl.text_render.set_editor_property('world_size', 12.0)
            lbl.text_render.set_editor_property('horizontal_alignment', unreal.HorizTextAligment.EHTA_CENTER)
            lbl.set_folder_path(f'Showcase/{gname}')
        row += (len(items) + COLS - 1) // COLS + 1
    floor = spawn(unreal.StaticMeshActor, (COLS * DX / 2, row * DY / 2, 0), label='Floor')
    floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Plane.Plane'))
    floor.set_actor_scale3d(unreal.Vector(COLS * DX / 100 + 10, row * DY / 100 + 10, 1))
    env = spawn(unreal.WuwaToonEnvironment, (0, 0, 0), label='WuwaToonEnvironment')
    env.set_editor_property('toon_parameters', unreal.load_asset(MPC))
    env.set_editor_property('main_light', sun)
    env.set_editor_property('sky_light', sky)
    env.set_editor_property('auto_collect_characters', True)
    env.set_editor_property('shadow_focus_on_view', True)
    env.set_editor_property('toon_depth_target', unreal.load_asset(f'{RT_DIR}/RT_ToonDepth'))
    env.set_editor_property('toon_shadow_target', unreal.load_asset(f'{RT_DIR}/RT_ToonShadow'))
    env.set_editor_property('het_mask_target', unreal.load_asset(f'{RT_DIR}/RT_WuwaHETMask'))
    env.set_editor_property('face_shadow_mask_target', unreal.load_asset(f'{RT_DIR}/RT_WuwaFaceShadowMask'))
    ok = env.apply_lighting_preset(PRESET)
    spawn(unreal.CameraActor, (COLS * DX / 2, -900, 200), (-5, 90, 0), 'Cam_Overview')
    spawn(unreal.CameraActor, (0, -260, 110), (-5, 90, 0), 'Cam_FirstCharacter')
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
        raise RuntimeError(f'save_map({MAP}) failed')
    res = {'map': MAP, 'placed': len(placed), 'missing': missing, 'preset_applied': bool(ok)}
    C.jsave(cfg['result'], res)
    C.log(f'showcase built: {len(placed)} blueprints, missing {len(missing)}, preset {PRESET} {ok}')


def mode_verify(cfg):
    plans = {p['bp_name']: p for p in C.jload(cfg['plan'])}
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    problems, ok, toon, facing = [], 0, 0, {}
    for a in actors:
        p = plans.get(a.get_actor_label())
        if not p:
            continue
        comps = {str(c.get_name()): c for c in a.get_components_by_class(unreal.ChildActorComponent)}
        want = {'Body': (p['body']['asset'], True)}
        want.update({c['name']: (c['asset'], c['visible']) for c in p['components']})
        bad = []
        for n, (asset, vis) in want.items():
            c = comps.get(n)
            child = c.get_editor_property('child_actor') if c else None
            if not isinstance(child, unreal.WuwaToonCharacterActor):
                bad.append(f'{n}: no toon child actor')
                continue
            toon += 1
            smc = child.skeletal_mesh_component
            m = smc.get_skeletal_mesh_asset()
            if m is None or C.asset_path(m.get_path_name()) != asset:
                bad.append(f'{n}: mesh {m.get_path_name() if m else None} != {asset}')
            if bool(smc.is_visible()) != bool(vis):
                bad.append(f'{n}: visible {smc.is_visible()} != {vis}')
            if any(x is None for x in smc.get_materials()):
                bad.append(f'{n}: empty material slot')
        # facing: horizontal foot -> toe direction of the body in world space (cameras look from -Y toward +Y)
        body = comps.get('Body').get_editor_property('child_actor') if comps.get('Body') else None
        if isinstance(body, unreal.WuwaToonCharacterActor):
            smc = body.skeletal_mesh_component
            pairs = [('Bip001LFoot', 'Bip001LToe0'), ('Bip001RFoot', 'Bip001RToe0'), ('Bip001_L_Foot', 'Bip001_L_Toe0')]
            for foot, toe in pairs:
                if smc.does_socket_exist(foot) and smc.does_socket_exist(toe):
                    d = smc.get_socket_location(toe) - smc.get_socket_location(foot)
                    facing[p['bp_name']] = [round(d.x, 2), round(d.y, 2)]
                    if d.y > 0 and abs(d.y) > abs(d.x):
                        bad.append(f'Body faces away from the cameras (toe dir {d.x:.1f}, {d.y:.1f})')
                    break
        if bad:
            problems.append(f"{p['bp_name']}: " + '; '.join(bad[:4]))
        else:
            ok += 1
    envs = [a for a in actors if isinstance(a, unreal.WuwaToonEnvironment)]
    if len(envs) != 1:
        problems.append(f'{len(envs)} WuwaToonEnvironment actors')
    placed = sum(1 for a in actors if a.get_actor_label() in plans)
    res = {'map': MAP, 'blueprint_instances': placed, 'verified': ok, 'toon_child_actors': toon,
           'planned': len(plans), 'problems': problems, 'facing': facing,
           'ok': not problems and placed == len(plans)}
    C.jsave(cfg['result'], res)
    C.log(f"showcase verify: {placed}/{len(plans)} placed, {ok} verified, {toon} toon child actors, problems {len(problems)}: "
          + '; '.join(problems[:5]))


def main():
    global SDS
    SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    cfg = C.jload(os.environ['WUWA_CHAR_BPS'])
    {'bps': mode_bps, 'showcase': mode_showcase, 'verify': mode_verify}[cfg['mode']](cfg)


C.run_guarded(main)
