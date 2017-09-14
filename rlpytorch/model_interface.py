# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import torch
import torch.cuda
import torch.optim
import torch.nn as nn
from torch.autograd import Variable
from collections import deque

# All model must provide .outputs and .preprocess
# E.g., .outputs = { "Q" : self.final_linear_layer }
#       .preprocess = lambda self, x: downsample(x)

class ModelInterface:
    ''' An interface for the model to receive intermediate results from the forward pass '''
    def __init__(self):
        ''' Initialization for models, old_models and optimizers.'''
        self.models = { }
        self.old_models = deque()
        self.optimizers = { }

    def clone(self, gpu=None):
        ''' Clone the state for the model interface

        Returns:
            cloned `ModelInterface`.
        '''
        mi = ModelInterface()
        for key, model in self.models.items():
            mi.models[key] = model.clone(gpu=gpu)
            if key in self.optimizers:
                # Same parameters.
                mi.optimizers[key] = torch.optim.Adam(mi.models[key].parameters())
                new_optim = mi.optimizers[key]
                old_optim = self.optimizers[key]

                new_optim_params = new_optim.param_groups[0]
                old_optim_params = old_optim.param_groups[0]
                # Copy the parameters.
                for k in new_optim_params.keys():
                    if k != "params":
                        new_optim_params[k] = old_optim_params[k]
                # Copy the state
                '''
                new_optim.state = { }
                for k, v in old_optim.state.items():
                    if isinstance(v, (int, float, str)):
                        new_optim.state[k] = v
                    else:
                        new_optim.state[k] = v.clone()
                        if gpu is not None:
                            new_optim.state[k] = new_optim.state[k].cuda(gpu)
                '''
        return mi


    def add_model(self, key, model, copy=False, cuda=False, gpu_id=None, optim_params={}):
        '''Add a model.

        Args:
            key(str): key in ``self.models``.
            model(str): the model to be added.
            copy(bool): indicate if the model needs to be deep copied.
            cuda(bool): indicate if model needs to be converted to cuda.
            gpu_id(int): gpu index.
            optim_params(dict): an dict of parameters for optimizers.

        Returns:
            ``False`` if key is already in ``self.models``, ``True`` if model is successfully added.
        '''
        if key in self.models: return False

        # New model.
        self.models[key] = model.clone() if copy else model
        if cuda:
            if gpu_id is not None:
                self.models[key].cuda(device_id=gpu_id)
            else:
                self.models[key].cuda()

        curr_model = self.models[key]
        if len(optim_params) > 0:
            # TODO: put betas, eps into optim_params?
            self.optimizers[key] = \
                    torch.optim.Adam(curr_model.parameters(), lr = optim_params["lr"], betas = (0.9, 0.999), eps=1e-3)

        return True

    def update_model(self, key, model, save_old_model=False):
        ''' Update an old model '''
        # print("Updating model " + key)
        if save_old_model:
            self.old_models.append(self.models[key].clone().cpu())
            if len(self.old_models) > 20:
                self.old_models.popleft()
        self.models[key].load_from(model)

    def average_model(self, key, model):
        ''' Average the model parameters.'''
        for param, other_param in zip(self.models[key].parameters(), model.parameters()):
            param.data += other_param.data.cuda(param.data.get_device())
            param.data /= 2

    def copy(self, dst_key, src_key):
        ''' Copy a model from src_key to dst_key in ``self.models``'''
        assert dst_key in self.models, "ModelInterface: dst_key = %s cannot be found" % dst_key
        assert src_key in self.models, "ModelInterface: src_key = %s cannot be found" % src_key
        self.update_model(dst_key, self.models[src_key].clone())

    ''' Usage:
        record = interface(input)
        Then record["Q"] will be the Q-function given the input.
    '''
    def zero_grad(self):
        ''' Zero the gradient for all optimizers '''
        for k, optimizer in self.optimizers.items():
            optimizer.zero_grad()

    def update_weights(self):
        ''' For each optimizer, call before_update for all the models, update the weights and increment the step for the model.'''
        for k, optimizer in self.optimizers.items():
            self.models[k].before_update()
            optimizer.step()
            self.models[k].inc_step()

    def __getitem__(self, key):
        ''' Get an item associated with ``key`` from ``self.models``'''
        return self.models[key]
