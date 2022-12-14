# from collections.abc import Callable, Iterable
# TODO: Deprecated since version 3.9. See Generic Alias Type and PEP 585.
from typing import Callable, Iterable

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from torch.distributions import Distribution, Normal

from ._base import ActionCritic, DeterministicActor, StochasticActor


class GaussianPolicy(StochasticActor):
    """
    TODO
    Action scaling/unscaling

    TODO
    Return Tanh squashed Gaussian distribution with diagonal covariance matrix
    - https://github.com/rail-berkeley/rlkit/blob/master/rlkit/torch/distributions.py#L312:7
    - https://stable-baselines3.readthedocs.io/en/v1.0/_modules/stable_baselines3/common/distributions.html
    - https://garage.readthedocs.io/en/v2020.06.2/_apidoc/garage.torch.distributions.tanh_normal.html
    - https://pytorch.org/docs/stable/distributions.html#pathwise-derivative
    - https://math.stackexchange.com/questions/3108216/change-of-variables-apply-tanh-to-the-gaussian-samples

    FIXME
    torch.distributions.normal.Normal is not JIT supported
    Compiled functions can't take variable number of arguments or use keyword-only arguments with defaults:
        File "torch/distributions/utils.py", line 11
        def broadcast_all(*values):
                          ~~~~~~~ <--- HERE
    - https://github.com/pytorch/pytorch/issues/29843
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Iterable[int],
        activation_fn: Callable[[Tensor], Tensor] = F.relu,
    ) -> None:
        super(GaussianPolicy, self).__init__()

        dims = [state_dim] + list(hidden_dims)
        self._lyrs = nn.ModuleList(
            [ nn.Linear(in_dim, out_dim) for in_dim, out_dim in zip(dims, dims[1:]) ])  # fmt: skip
        self._mean_lyr = nn.Linear(dims[-1], action_dim)
        self._log_stddev_lyr = nn.Linear(dims[-1], action_dim)
        self.apply(_init_weights)

        self._actv_fn = activation_fn

        self._log_stddev_min = -20
        self._log_stddev_max = 2

    def forward(self, state: Tensor) -> Distribution:
        actv = state

        for lyr in self._lyrs:
            actv = self._actv_fn(lyr(actv))
        mean: Tensor = self._mean_lyr(actv)
        log_stddev: Tensor = self._log_stddev_lyr(actv)

        # TODO: Why?
        log_stddev = torch.clamp(log_stddev, self._log_stddev_min, self._log_stddev_max)

        return Normal(mean, log_stddev.exp())


class Policy(DeterministicActor):
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Iterable[int],
        activation_fn: Callable[[Tensor], Tensor] = F.relu,
        output_fn: Callable[[Tensor], Tensor] = torch.tanh,
    ) -> None:
        super(Policy, self).__init__()

        dims = [state_dim] + list(hidden_dims) + [action_dim]
        self._lyrs = nn.ModuleList(
            [ nn.Linear(in_dim, out_dim) for in_dim, out_dim in zip(dims, dims[1:]) ])  # fmt: skip
        self.apply(_init_weights)

        self._actv_fn = activation_fn
        self._out_fn = output_fn  # controls the amplitude of the output

    def forward(self, state: Tensor) -> Tensor:
        # https://github.com/pytorch/pytorch/issues/47336
        # activation = state
        # for hidden_layer in self._layers[:-1]:
        #     activation = self._activation_fn( hidden_layer(activation) )
        # action = self._output_fn( self._layers[-1](activation) )
        # One-liner:
        # action = self._output_fn(self.layers[-1](
        #     reduce(lambda activation, hidden_layer: self._activation_fn(hidden_layer(activation)), self.layers[:-1], state)))
        # However, torch.jit.script raises torch.jit.frontend.UnsupportedNodeError: Lambda aren't supported
        actv = state
        last = len(self._lyrs)
        for current, lyr in enumerate(self._lyrs, start=1):
            if current != last:
                actv = self._actv_fn(lyr(actv))
            else:
                actv = self._out_fn(lyr(actv))
        action = actv

        return action


class ActionValue(ActionCritic):
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: Iterable[int],
        activation_fn: Callable[[Tensor], Tensor] = F.relu,
    ) -> None:
        super(ActionCritic, self).__init__()

        dims = [state_dim + action_dim] + list(hidden_dims) + [1]
        self._lyrs = nn.ModuleList(
            [ nn.Linear(in_dim, out_dim) for in_dim, out_dim in zip(dims, dims[1:]) ])  # fmt: skip
        self.apply(_init_weights)

        self._actv_fn = activation_fn

    def forward(self, state: Tensor, action: Tensor) -> Tensor:

        actv = torch.cat([state, action], dim=1)
        for lyr in self._lyrs[:-1]:
            actv = self._actv_fn(lyr(actv))
        action_value = self._lyrs[-1](actv)

        return action_value


@torch.no_grad()
def _init_weights(m: nn.Module) -> None:
    if isinstance(m, nn.Linear):
        nn.init.xavier_uniform_(m.weight)
