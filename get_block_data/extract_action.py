import os
from get_block_data.block import Block, prefix, prefix_dir, extract_predicate, stacks, objs
import matplotlib.pyplot as plt
import numpy as np
from c_swm.utils import save_list_dict_h5py


NUM_EPISODE = 100
EPISODE_LENGTH = 10
N_TRAIN_DICT = {1:10, 2:80, 3:600, 4:5000}
N_EVAL_DICT = {1:2, 2:16, 3:120, 4:760}
# N_TRAIN = N_TRAIN_DICT[objs]
# N_EVAL = N_EVAL_DICT[objs]

np.random.seed(0)
np.set_printoptions(threshold=np.inf, linewidth=np.inf)
# TRAIN_IDX = np.random.choice(N_TRAIN+N_EVAL, N_TRAIN, replace=False)

# def resize(block_img, scale=2): # resize by 2
#     assert len(block_img.shape) == 3 or len(block_img.shape) == 2
#     if len(block_img.shape) == 3:
#         img_down_sampled = block_img[:,::scale,::scale]
#     else:
#         img_down_sampled = block_img[::scale, ::scale]
#     return img_down_sampled

def resize(img, scale=1):
    return img

def get_index_from_image(img, color):
    color = color[:-1]
    target = np.tile(color, (img.shape[0], img.shape[1], 1))
    cond = np.all(img == target, axis=-1)
    return np.where(cond)

def gen_episode(num_episode, episode_length):

    tr_files = os.listdir(os.path.join(prefix_dir, prefix, "scene_tr"))
    tr_files.sort()
    n_tr = len(tr_files) // 2
    # assert N_TRAIN + N_EVAL == n_tr

    img_tr_files = os.listdir(os.path.join(prefix_dir, prefix, "image_tr"))
    img_tr_files.sort()

    mask_tr_files = os.listdir(os.path.join(prefix_dir, prefix, "mask_image_tr"))
    mask_tr_files.sort()

    ACTIONS = [(i, j) for i in range(stacks) for j in range(stacks) if j != i]  # (SOURCE, TARGET)

    replay_buffer_train = []
    replay_buffer_eval = []
    replay_buffer = []

    for i in range(n_tr):
        if i % 100 == 0:
            print(i)
        if i == 3 or i == 53:
            pass
        else:
            continue
        # if i in TRAIN_IDX:
        #     replay_buffer = replay_buffer_train
        # else:
        #     replay_buffer = replay_buffer_eval
        pre_json = os.path.join(prefix_dir, prefix, "scene_tr", tr_files[i*2])
        suc_json = os.path.join(prefix_dir, prefix, "scene_tr", tr_files[i*2+1])
        pre_objs, pre_bottom_pads, pre_state, relation = extract_predicate(pre_json)
        suc_objs, suc_bottom_pads, suc_state, relation = extract_predicate(suc_json)
        action = None
        target_obj = None
        moving_obj = None
        from_obj = None

        obs = plt.imread(os.path.join(prefix_dir, prefix, "image_tr", img_tr_files[i*2]))[:,:,:-1]
        next_obs = plt.imread(os.path.join(prefix_dir, prefix, "image_tr", img_tr_files[i*2+1]))[:,:,:-1]

        mask = plt.imread(os.path.join(prefix_dir, prefix, "mask_image_tr", mask_tr_files[i*2]))[:,:,:-1]
        next_mask = plt.imread(os.path.join(prefix_dir, prefix, "mask_image_tr", mask_tr_files[i*2+1]))[:,:,:-1]

        pre_objs_index_matrix = np.zeros(shape=mask.shape[:2], dtype=np.float32)
        next_objs_index_matrix = np.zeros(shape=next_mask.shape[:2], dtype=np.float32)

        assert len(pre_objs) == len(suc_objs)

        for pre_obj, suc_obj in zip(pre_objs, suc_objs):
            assert pre_obj.id == suc_obj.id
            assert isinstance(pre_obj, Block)
            pre_obj_index = get_index_from_image(mask, pre_obj.color)
            next_obj_index = get_index_from_image(next_mask, suc_obj.color)
            pre_objs_index_matrix[pre_obj_index[0], pre_obj_index[1]] = pre_obj.id #0 as back ground
            next_objs_index_matrix[next_obj_index[0], next_obj_index[1]] = suc_obj.id #0 as back ground
            if pre_obj.position_eq(suc_obj):
                # print("Block {} does not move".format(pre_obj.id))
                pass
            else:
                # print("Pick up block {} from stack {},  Drop it on stack {}".format(pre_obj.id, pre_obj.n_stack, suc_obj.n_stack))

                moving_obj = pre_obj

                if suc_obj.floor == 0:
                    target_obj = pre_bottom_pads[suc_obj.n_stack]
                else:
                    for obj in suc_objs:
                        if obj.floor == suc_obj.floor - 1 and obj.n_stack == suc_obj.n_stack:
                            target_obj = obj
                            break

                if pre_obj.floor == 0:
                    from_obj = pre_bottom_pads[pre_obj.n_stack]
                else:
                    for obj in pre_objs:
                        if obj.floor == pre_obj.floor - 1 and obj.n_stack == pre_obj.n_stack:
                            from_obj = obj
                            break
                # print("Moving {} from {} to {}".format(moving_obj, from_obj, target_obj))
                action = ACTIONS.index((pre_obj.n_stack, suc_obj.n_stack))

        for (pre_pad, suc_pad) in zip(pre_bottom_pads, suc_bottom_pads):
            pre_obj_index = get_index_from_image(mask, pre_pad.color)
            pre_objs_index_matrix[pre_obj_index[0], pre_obj_index[1]] = pre_pad.id
            suc_obj_index = get_index_from_image(next_mask, suc_pad.color)
            next_objs_index_matrix[suc_obj_index[0], suc_obj_index[1]] = suc_pad.id

        for m in [pre_objs_index_matrix, next_objs_index_matrix]:
            assert np.unique(m).shape[0] == objs + 1 + 4

        assert action is not None
        assert target_obj is not None
        assert from_obj is not None
        assert moving_obj is not None

        replay = {
            'obs': [],
            'mask': [],
            'obs_obj_index': [],
            'next_obs': [],
            'next_mask': [],
            'next_obj_index': [],
            'action_mov_obj_index': [],
            'action_tar_obj_index': [],
            'action_from_obj_index': [],
            'scene_state_pre': [],
            'scene_state_suc': []
        }

        obs_colors = np.unique(np.resize(mask, (-1, mask.shape[-1])), axis=0)
        next_obs_colors = np.unique(np.resize(next_mask, (-1, next_mask.shape[-1])), axis=0)
        assert obs_colors.shape[0] == objs + 1 + 4
        assert next_obs_colors.shape[0] == objs + 1 + 4

        # action_mov_obs = set_image_action(obs, moving_obj.color)
        # action_tar_obs = set_image_action(obs, target_obj.color)
        # action_image = np.stack([action_mov_obs, action_tar_obs]).astype(np.float32)
        # replay['action_image'].append(
        #     resize(action_image, (2, 100, 150))
        # )
        # plt.imshow(obs)
        # plt.show()
        # plt.imshow(next_obs)
        # plt.show()

        replay['obs'].append(
            resize(np.transpose(obs, (2,0,1)))
        )

        replay['next_obs'].append(
            resize(np.transpose(next_obs, (2,0,1)))
        )

        replay['mask'].append(
            resize(np.transpose(mask, (2,0,1)))
        )

        replay['next_mask'].append(
            resize(np.transpose(next_mask, (2,0,1)))
        )

        replay['obs_obj_index'].append(
            resize(pre_objs_index_matrix)
        )

        replay['next_obj_index'].append(
            resize(next_objs_index_matrix)
        )

        replay['action_mov_obj_index'].append(
            moving_obj.id
        )

        replay['action_tar_obj_index'].append(
            target_obj.id
        )

        replay['action_from_obj_index'].append(
            from_obj.id
        )

        replay['scene_state_pre'].extend(
            pre_state
        )

        replay['scene_state_suc'].extend(
            suc_state
        )

        replay_buffer.append(replay)

    # save_list_dict_h5py(replay_buffer_train, "{}/{}/{}".format("c_swm", "data", "{}_train.h5".format(prefix)))
    # save_list_dict_h5py(replay_buffer_eval, "{}/{}/{}".format("c_swm", "data", "{}_eval.h5".format(prefix)))
    print(len(replay_buffer))
    # save_list_dict_h5py(replay_buffer_eval + replay_buffer_train, "{}/{}/{}".format("c_swm", "data", "{}_special2.h5".format(prefix)))
    save_list_dict_h5py(replay_buffer, "{}/{}/{}".format("c_swm", "data", "{}_special2.h5".format(prefix)))


if __name__ == "__main__":
    gen_episode(NUM_EPISODE, EPISODE_LENGTH)