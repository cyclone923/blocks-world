from torch import nn
from fosae.gumble import gumbel_softmax
from fosae.activations import TrinaryStep
from fosae.domain_info.blocks_world import *


CONV_CHANNELS = 32
SEMANTICS_LATENT = 4
ENCODER_FC_LAYER_SIZE = 200

IMG_H = 64
IMG_W = 96
IMG_C = 3
assert IMG_W % 4 == 0
assert IMG_H % 4 == 0
FMAP_H = IMG_H // 4
FMAP_W = IMG_W // 4


class PredicateNetwork(nn.Module):

    def __init__(self, in_objects, out_features):
        super(PredicateNetwork, self).__init__()
        self.in_objects = in_objects
        self.conv1 = nn.Conv2d(in_channels=in_objects*IMG_C, out_channels=CONV_CHANNELS, kernel_size=(8,8), stride=(4,4), padding=2)
        # self.bn1 = nn.BatchNorm2d(CONV_CHANNELS)
        self.fc2 = nn.Linear(in_features=CONV_CHANNELS*FMAP_H*FMAP_W, out_features=ENCODER_FC_LAYER_SIZE)
        # self.bn2 = nn.BatchNorm1d(1)
        self.fc3 = nn.Linear(in_features=ENCODER_FC_LAYER_SIZE, out_features=out_features)

    def forward(self, input, temp):
        h1 = torch.relu(self.conv1(input.view(-1, self.in_objects * IMG_C, IMG_H, IMG_W)))
        h1 = h1.view(-1, 1, CONV_CHANNELS * FMAP_H * FMAP_W)
        h2 = torch.relu(self.fc2(h1))
        return gumbel_softmax(self.fc3(h2), temp).squeeze()


class StateChangePredictor(nn.Module):

    def __init__(self, in_features, out_features):
        super(StateChangePredictor, self).__init__()
        self.fc1 = nn.Linear(in_features=in_features, out_features=out_features)
        self.fc2 = nn.Linear(in_features=out_features, out_features=out_features)
        self.step_func = TrinaryStep()

    def forward(self, input):
        ret = self.step_func.apply(self.fc2(torch.relu(self.fc1(input))))
        return ret

class StateEncoder(nn.Module):

    def __init__(self):
        super(StateEncoder, self).__init__()
        list_of_predicate_module = []
        for i, p in enumerate(Ps):
            arity = i + 1
            list_of_predicate_module.append(nn.ModuleList([PredicateNetwork(in_objects=arity+1, out_features=1) for _ in range(p)]))
        self.state_predicate_encoder = nn.ModuleList(list_of_predicate_module)


    def enumerate_state(self, state, state_next, n_obj, backgrounds):

        all_objs = [[] for _ in range(len(Ps))]
        all_next_objs = [[] for _ in range(len(Ps))]

        for s, s_n, n, bg in zip(state, state_next, n_obj, backgrounds):
            for i, p in enumerate(Ps):
                arity = i + 1
                enum_index = torch.cartesian_prod(*[torch.arange(n.item()) for _ in range(arity)]).to(device)
                for t in enum_index:
                    all_objs[i].append(
                        torch.cat([
                            torch.index_select(s, dim=0, index=t), bg[0].unsqueeze(0)
                        ], dim=0).view((arity+1) * IMG_C, IMG_H, IMG_W)
                    )
                    all_next_objs[i].append(
                        torch.cat([
                            torch.index_select(s_n, dim=0, index=t), bg[1].unsqueeze(0)
                        ], dim=0).view((arity+1) * IMG_C, IMG_H, IMG_W)
                    )

        all_objs = [torch.stack(x, dim=0).to(device) for x in all_objs]
        all_next_objs = [torch.stack(x, dim=0).to(device) for x in all_next_objs]

        return (all_objs, all_next_objs)

    def forward(self, state_input, temp):
        state, state_next, n_obj, backgrounds = state_input

        n_state = state.size()[0]

        objs = self.enumerate_state(state, state_next, n_obj, backgrounds)

        p_slots = [[] for _ in range(2)]

        for i, (p, p_module_list) in enumerate(zip(Ps, self.state_predicate_encoder)):
            arity = i + 1
            for (o, p_slot) in zip(objs, p_slots):
                preds = torch.cat([net(o[i], temp) for net in p_module_list], dim=0)
                preds_reshape = torch.zeros(size=(n_state, p * MAX_N ** arity)).to(device)
                start_idx = 0
                for j, n in enumerate(n_obj):
                    fill_length = p * n ** arity
                    preds_reshape[j, :fill_length] = preds[start_idx: start_idx + fill_length]
                    start_idx += fill_length
                p_slot.append(preds_reshape)

        return (torch.cat(x, dim=1) for x in p_slots)


class ActionEncoder(nn.Module):

    def __init__(self):
        super(ActionEncoder, self).__init__()
        n_pred = 0
        for i, a in enumerate(Ps):
            arity = i+1
            n_pred += MAX_N ** arity

        self.action_semantic_encoder = nn.ModuleList([StateChangePredictor(in_features=a*MAX_N, out_features=n_pred) for a in As])

    def index_to_one_hot(self, idx):
        idx = idx.view(-1, 1)
        source = torch.zeros(size=(idx.size()[0], MAX_N)).to(device)
        return torch.scatter(source, dim=1, index=idx, value=1).view(-1, MAX_N*max(As))

    def forward(self, action_input):
        action_indecies, action_n_obj, action_types = action_input
        all_action_latent = []
        for a, n, t in zip(self.index_to_one_hot(action_indecies), action_n_obj, action_types):
            all_action_latent.append(self.action_semantic_encoder[t.item()](a[:n*MAX_N]))
        return torch.stack(all_action_latent)

class FoSae(nn.Module):

    def __init__(self):
        super(FoSae, self).__init__()
        self.state_encoders = StateEncoder()
        self.action_encoders = ActionEncoder()

    def forward(self, state_input, action_input, temp):
        return self.state_encoders(state_input, temp), self.action_encoders(action_input)

    def get_supervise_signal(self, action_input):
        pre_ind = []
        pre_label = []
        eff_ind = []
        eff_label = []
        for idx, n_obj, type in zip(*action_input):
            assert idx.dim() == 1
            assert type.dim() == 0
            assert n_obj.dim() == 0
            idx = [i for i in idx]
            pre_signal = ACTION_FUNC[type.item()].get_precondition(*idx[:n_obj.item()])
            eff_signal = ACTION_FUNC[type.item()].get_effect(*idx[:n_obj.item()])
            pre_ind.append(pre_signal[0])
            pre_label.append(pre_signal[1])
            eff_ind.append(eff_signal[0])
            eff_label.append(eff_signal[1])
        return torch.stack(pre_ind).to(device), torch.stack(pre_label).to(device), \
               torch.stack(eff_ind).to(device), torch.stack(eff_label).to(device)