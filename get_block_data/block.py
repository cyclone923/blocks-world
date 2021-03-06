import os
import json
from collections import defaultdict
from get_block_data.relation import SceneRelation
import sys

if len(sys.argv) == 1:
    print("Please specify #objs and #stacks")
    exit(0)
else:
    objs = int(sys.argv[1])
    stacks = int(sys.argv[2])

seed = 0
prefix_dir = "block_img/"
prefix = "blocks-{}-{}-{}".format(objs, stacks, seed)
print(prefix)

with open((os.path.join(prefix_dir, prefix, "{}-init.json".format(prefix)))) as f:
    init_json = json.load(f)

STACK_XS = init_json['stack_x']
BLCOK_INDIES = [i for i in range(1, objs+1)]
PAD_INDIES = [i for i in range(objs+1, objs+stacks+1)]


class Block:

    def __init__(self, object_config):
        self.shape = object_config['shape']
        self.size = object_config['size']
        self.color = object_config['color']
        if 'location' in object_config:
            self.n_stack = STACK_XS.index(object_config['location'][0])
            self.z = object_config['location'][2]

    def __eq__(self, other):
        assert isinstance(other, Block)
        if self.shape != other.shape:
            return False
        if self.size != other.size:
            return False
        for c1, c2 in zip(self.color, other.color):
            if c1 != c2:
                return False
        return True

    def __repr__(self):
        return "\nshape: {} size:{: .2f} color:({:.2f}, {:.2f}, {:.2f})".format(
            self.shape, self.size, self.color[0], self.color[1], self.color[2]
        )

    def set_block_id(self, n):
        self.id = BLCOK_INDIES[n]

    def set_pad_id(self, n):
        self.id = PAD_INDIES[n]

    def set_floor(self, floor):
        self.floor = floor

    def position_eq(self, other):
        return self.n_stack == other.n_stack and self.floor == other.floor

    def print_block_scene_position(self):
        print("Block on {}th stack and {}th floor".format(self.n_stack, self.floor))

SCENE_OBJS = [Block(config) for config in init_json['objects']]

def extract_predicate(json_file):
    # print(json_file)
    with open(json_file) as f:
        state_json = json.load(f)
    scene_stacks_ys = defaultdict(lambda: [])
    scene_objs = []
    relation = SceneRelation()
    bottom_pads_objs = []
    for obj in state_json['objects']:
        b = Block(obj)
        if b in SCENE_OBJS:
            scene_objs.append(b)
            b.set_block_id(SCENE_OBJS.index(b))
            scene_stacks_ys[b.n_stack].append(b.z)
        else:
            assert b.shape == "SmoothBottomPad"
            b.set_pad_id(len(bottom_pads_objs))
            bottom_pads_objs.append(b)
            relation.on_ground.add(b.id)
    for k, v in scene_stacks_ys.items():
        scene_stacks_ys[k] = sorted(v)
    for b in scene_objs:
        b.set_floor(scene_stacks_ys[b.n_stack].index(b.z))
        # b.print_block_scene_position()
    for p in bottom_pads_objs:
        relation.clear.add(p.id)
    for b in scene_objs:
        clear = True
        if b.floor == 0:
            for p in bottom_pads_objs:
                if p.n_stack == b.n_stack:
                    relation.on_block[b.id] = p.id
                    relation.clear.remove(p.id)
                    break
        for other_b in scene_objs:
            if other_b.floor == b.floor - 1:
                relation.on_block[b.id] = other_b.id
            elif other_b.floor > b.floor:
                clear = False
        if clear:
            relation.clear.add(b.id)


    return scene_objs, sorted(bottom_pads_objs, key=lambda x: x.n_stack), state_json['scene_state'], relation


