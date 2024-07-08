import os
import bpy
import glob
import pickle
import numpy as np
from anim import bvh
from tqdm import tqdm
from anim import amass
from multiprocessing import Pool

VMD_BONE_NAMES =[
                "足.L",
                "足.R",
                "上半身",
                "ひざ.L",
                "ひざ.R",
                "上半身2",
                "足首.L",
                "足首.R",
                "つま先.L",
                "つま先.R",
                "首",
                "肩.L",
                "肩.R",
                "頭",
                "腕.L",
                "腕.R",
                "ひじ.L",
                "ひじ.R",
                "手首.L",
                "手首.R",
                "人指１.L",
                "人指２.L",
                "中指１.L",
                "中指２.L",
                "小指１.L",
                "小指２.L",
                "薬指１.L",
                "薬指２.L",
                "親指０.L",
                "親指１.L",
                "人指１.R",
                "人指２.R",
                "中指１.R",
                "中指２.R",
                "小指１.R",
                "小指２.R",
                "薬指１.R",
                "薬指２.R",
                "親指０.R",
                "親指１.R",
                'センター' # not included in joint transformations, debugging only
                ]

def mesh_triangulate(me):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()

def export_AMASS_vmd(mocap):
    files = [k for k in glob.glob(f"data/{mocap}/**/**") if not k.endswith('shape.npz')]
    os.makedirs(f'data/{mocap}_bvh', exist_ok=True)
    os.makedirs(f'data/{mocap}_vmd', exist_ok=True)

    for f in files:
        bpy.ops.wm.read_factory_settings(use_empty=True) # clean all
        bpy.ops.preferences.addon_enable(module='mmd_tools') # must enable within the loop
        assert len(dir(bpy.ops.mmd_tools)) > 0, "mmd tools not correctly installed" 

        anim = amass.load(
                amass_motion_path=f,
                smplh_path="data/smplh/neutral/model.npz",
        )

        filename = f.replace(f"data/{mocap}/", "")
        folder, _ = filename.split('/')

        os.makedirs(f'data/{mocap}_bvh/{folder}', exist_ok=True)
        os.makedirs(f'data/{mocap}_vmd/{folder}', exist_ok=True)

        bvh.save(
            filepath=os.path.join(f'data/{mocap}_bvh', filename.replace('npz', 'bvh')),
            anim=anim,
            save_pos=False
        )

        bpy.ops.import_anim.bvh(filepath=os.path.join(f'data/{mocap}_bvh', filename.replace('npz', 'bvh')), global_scale=0.0112, use_fps_scale=True, rotate_mode='QUATERNION')

        print("save to", os.path.join(f'data/{mocap}_vmd', filename.replace('npz', 'vmd')))

        bpy.ops.mmd_tools.export_vmd(filepath=os.path.join(f'data/{mocap}_vmd', filename.replace('npz', 'vmd')), check_existing=True,
                                        filter_glob="*.vmd", scale=12.5, use_pose_mode=True, use_frame_range=False) # use_pose_mode = True to start from A-Pose

def export_blend(to_path, vmd_path, char, no_physics=False):
    bpy.ops.wm.read_factory_settings(use_empty=True) # clean all
    bpy.ops.preferences.addon_enable(module='mmd_tools') # must enable within the loop

    bpy.ops.mmd_tools.import_model(filepath=f"data/characters/{char}/{char}.pmx",
                                    files=[{"name": f"{char}.pmx"}], 
                                    directory=f"data/characters/{char}", log_level="ERROR") 

    bpy.ops.mmd_tools.import_vmd(filepath=vmd_path, 
                                files=[{"name":vmd_path.split('/')[-1]}], 
                                directory='/'.join(vmd_path.split('/')[:-1]))
    
    bpy.context.view_layer.objects.active = bpy.context.scene.objects.get(char)
    bpy.data.objects[char].select_set(True)

    # build physics
    bpy.ops.rigidbody.constraint_add(type='GENERIC')

    if not no_physics:
        bpy.ops.mmd_tools.build_rig()

    # close all IK
    bpy.data.objects[f'{char}_arm'].pose.bones["つま先ＩＫ.R"].mmd_ik_toggle = False
    bpy.data.objects[f'{char}_arm'].pose.bones["つま先ＩＫ.L"].mmd_ik_toggle = False
    bpy.data.objects[f'{char}_arm'].pose.bones["足ＩＫ.R"].mmd_ik_toggle = False
    bpy.data.objects[f'{char}_arm'].pose.bones["足ＩＫ.L"].mmd_ik_toggle = False

    # select mesh for recording
    bpy.data.objects[f'{char}_mesh'].select_set(True)

    # delete all shape keys for triangulation
    obj = bpy.data.objects[f'{char}_mesh']
    for shapekey in obj.data.shape_keys.key_blocks:
        obj.shape_key_remove(shapekey)

    print(f"loaded {bpy.context.scene.frame_end} frames")

    # bake physics simulation
    if not no_physics:
        bpy.ops.ptcache.bake_all(bake=True)
    
    # get a specific frame
    bpy.context.scene.frame_set(0)

    # update the scene at the target frame
    dg = bpy.context.evaluated_depsgraph_get()
    obj = obj.evaluated_get(dg)
    me = obj.to_mesh(preserve_all_data_layers=True, depsgraph=dg)

    # process mesh: triangulate, keep vertices order    
    mesh_triangulate(me)
    sort_func = lambda a: a[0].use_smooth
    face_index_pair = [(face, index) for index, face in enumerate(me.polygons)]
    face_index_pair.sort(key=sort_func)

    # cache the file
    tp_wf = to_path[:-6] + f'_{bpy.context.scene.frame_end}.blend'
    cwd = os.getcwd()
    print("SAVING AT", f'{cwd}/{tp_wf}')
    bpy.ops.wm.save_as_mainfile(filepath=f'{cwd}/{tp_wf}', compress=True)

def process_char(arg):
    char, f, to_path, no_physics = arg
    to_folder = [fs for fs in to_path if '.blend' not in fs]
    to_folder.append(char)
    ts = '/'.join(to_folder)
    os.makedirs(ts, exist_ok=True)
    to_folder.append(to_path[-1])
    tf = '/'.join(to_folder)
    export_blend(to_path=tf, vmd_path=f, char=char, no_physics=no_physics)


def cache_blend(to_folder, blend_path, char):
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    # global axis, z front, y top
    global_array = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])
    global_arrayx4 = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]])
    
    bpy.context.view_layer.objects.active = bpy.context.scene.objects.get(char)
    bpy.data.objects[char].select_set(True)

    print(f"loaded {bpy.context.scene.frame_end} frames")

    for i in tqdm(range(30, bpy.context.scene.frame_end)): # discard initial frames
        bpy.context.scene.frame_set(i)
        obj = bpy.data.objects[f'{char}_mesh']

        dg = bpy.context.evaluated_depsgraph_get()
        obj = obj.evaluated_get(dg)
        me = obj.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
   
        mesh_triangulate(me)
        v1 = (global_array @ np.array([v.co for v in me.vertices]).T).T
        sort_func = lambda a: a[0].use_smooth
        face_index_pair = [(face, index) for index, face in enumerate(me.polygons)]
        face_index_pair.sort(key=sort_func)
        faces = np.array([face[0].vertices for face in face_index_pair])

        j1 = []
        m1 = []
        for vmd_bone in VMD_BONE_NAMES:
            j1.append(list(bpy.data.objects[f'{char}_arm'].pose.bones[vmd_bone].head)) # the bone direction goes from head -> tail
            m1.append(np.array(bpy.data.objects[f'{char}_arm'].pose.bones[vmd_bone].matrix))

        j1 = np.array(j1)
        j1 = (global_array @ j1.T).T

        m1 = np.array(m1)
        m1 = (global_arrayx4 @ m1)

        path_seq = blend_path.split('/')
        seq_id = f'{path_seq[-3]}_{path_seq[-2]}_{path_seq[-1][:-4]}'

        # return: v: mesh vertices
        #         j: joint position
        #         f: mesh faces
        #         m: joint transformation wrt. world frame

        result = {'v': v1.astype(np.float32), 'j': j1.astype(np.float32), 'f': faces,
                  'm': m1.astype(np.float32), 'name': char, 'seq': seq_id, 't': i}

        cnt = len(os.listdir(to_folder))
        pickle.dump(result, open(f'{to_folder}/data_{cnt}.pkl', 'wb'))

def export_dataset_parallel(no_physics):
    files = glob.glob('data/DanceDB_vmd/**/**')
    chars = [char for char in os.listdir('data/characters')]
    suf = '_nophysics' if no_physics else ''
    for f in tqdm(files):
        to_path = f.replace('DanceDB_vmd', f'mmd_blend_dataset{suf}').replace('.vmd', '.blend').split('/')
        pool = Pool()
        args = [(char, f, to_path, no_physics) for char in chars]
        pool.map(process_char, args)
        pool.close()
        pool.join()

def cache_all():
    files = glob.glob('data/mmd_blend_dataset/**/**/**')
    for f in files:
        motion_name = f.split('/')[-3] + '_' + f.split('/')[-1].replace('.blend', '')
        char = f.split('/')[-2]
        t_folder = f'data/cached/' + motion_name
        os.makedirs(t_folder, exist_ok=True)
        cache_blend(t_folder, f, char)
    
if __name__ == "__main__":
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--extract-vmd", dest='extract_vmd', action="store_true")
    parser.add_argument("--extract-blend", dest='extract_blend', action="store_true")
    parser.add_argument("--no-physics", dest='no_physics', action="store_true")
    parser.add_argument("--cache", dest='cache', action="store_true")

    args = parser.parse_args()

    if args.extract_vmd:
        export_AMASS_vmd('DanceDB')
    
    if args.extract_blend:
        export_dataset_parallel(args.no_physics)

    if args.cache:
        cache_all()