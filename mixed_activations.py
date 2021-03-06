import torch
from torch import nn
from modules import MLP, MLP_ATT, Antirelu, Identity


MLP_neg = ['MLP1_neg', 'MLP_ATT_neg']
ATT_list = ['MLP_ATT', 'MLP_ATT_neg', 'MLP_ATT_b']


class MIX(nn.Module):
    def __init__(self, act_fn, combinator, neurons, normalize=None, init='random', alpha_dropout=None):
        super(MIX, self).__init__()
        self.combinator = combinator  # name of the combinator, e.g. "Linear"
        self.act_fn = act_fn  # basic activation function to be used, e.g. "Tanh, Sigmoid"
        self.normalize = normalize  # normalize alpha, e.g. with a Sigmoid
        self.neurons = neurons  # number of neurons of the layer
        self.alpha_dropout = alpha_dropout  # apply a dropout on alpha (only for MLP_ATT)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.act_module = {'relu': nn.ReLU(),  # dictionary containing useful functions
                           'sigmoid': nn.Sigmoid(),
                           'tanh': nn.Tanh(),
                           'antirelu': Antirelu(),
                           'identity': Identity(),
                           'softmax': nn.Softmax()}

        if combinator == 'Linear':  # 3 different alpha initialization for the Linear combinator
            assert init in ['normal', 'uniform', 'random'], "init must be 'normal','uniform','random'"
            if init == 'normal':  # sample taken from a gaussian N(0,1)
                self.alpha = nn.Parameter(torch.randn(neurons, len(act_fn)))
            elif init == 'uniform':  # same init for each alpha, equal to 1/(num of act_fn)
                self.alpha = nn.Parameter(torch.ones(neurons, len(act_fn)) / len(act_fn))
            elif init == 'random':  # sample alpha in a uniform interval
                self.alpha = nn.Parameter(torch.FloatTensor(neurons, len(act_fn)).uniform_(-0.5, 0.5))

        elif combinator in ['MLP1', 'MLP1_neg', 'MLP2', 'MLP3', 'MLP4', 'MLP5']:  # create a list of MLP
            self.MLP_list = nn.ModuleList([MLP(combinator) for _ in range(neurons)])

        elif combinator == 'MLPr':  # MLPr is a mix of MLP1, MLP2
            self.MLP_list = nn.ModuleList([])
            for i in range(neurons // 2):
                self.MLP_list.extend([MLP('MLP1')])
                self.MLP_list.extend([MLP('MLP2')])

        elif combinator in ['MLP_ATT', 'MLP_ATT_neg', 'MLP_ATT_b']:  # MLP_ATT has a different structure w.r.t MLP
            self.MLP_list = nn.ModuleList([MLP_ATT(combinator) for _ in range(neurons)])

    def forward(self, s):
        act_fn = self.act_fn
        combinator = self.combinator
        alpha_dropout = self.alpha_dropout
        normalize = self.normalize
        act_module = self.act_module

        if combinator != 'None':
            if combinator not in MLP_neg:  # compute basic activations results, e.g. [tanh(s), sigmoid(s)] w/ s = input
                activations = torch.cat([act_module[act](s).unsqueeze(-1) for act in act_fn], dim=-1)
            else:  # for MLP_neg also the negative basic activations are added in the list
                activations = torch.cat([[act_module[act](s).unsqueeze(-1), -1 * act_module[act](s).unsqueeze(-1)]
                                         for act in act_fn], dim=-1)

            if combinator == 'Linear':
                # the result is the linear combination of the basic activations, weighted by alpha (learned by the nn)
                alpha = self.alpha
                if normalize != 'None':  # apply normalization if requested
                    alpha = act_module[normalize.lower()](alpha)
                res = torch.sum(alpha * activations, axis=-1)

            elif combinator in ATT_list:
                # the result is the linear combination of the basic activations, weighted by alpha (learned by an MLP)
                # each neuron is associated with a MLP with (input, output) = (n, n) where n = num. of basic act_fn
                alpha = torch.cat([self.act_module['softmax'](mod(activations[:, i, :])).unsqueeze(1)
                                  for i, mod in enumerate(self.MLP_list)],
                                  dim=1)  # e.g. [256, 128, 4] (or [256, 128, 8] for neg)
                if alpha_dropout is not None:  # apply dropout if requested
                    alpha = nn.Dropout(alpha_dropout)(alpha)
                res = torch.sum(alpha * activations, axis=-1)
                # uncomment for hard routing
                '''
                if self.training is False
                    alpha_max, idx = torch.max(alpha, dim=2)
                    mask = torch.arange(alpha.size(-1)).reshape(1, 1, -1) == idx.unsqueeze(-1)
                    res = activations[mask].reshape(alpha_max.shape)
                '''
            else:  # combinator in ['MLP1', 'MLP2', 'MLP3', 'MLP4', 'MLP5', 'MLPr']
                # the results will be computed by an MLP with dim (input, output) = (n,1) where n = num. of act_fn
                res = torch.cat([mod(activations[:, i, :]) for i, mod in enumerate(self.MLP_list)], dim=-1)

        else:  # compute only a basic activation function (no MIX)
            res = act_module[act_fn[0]]

        return res
