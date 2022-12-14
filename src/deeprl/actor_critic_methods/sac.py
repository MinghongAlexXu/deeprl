import math
from copy import deepcopy
from functools import partial

# from collections.abc import Callable, Iterator
from typing import (  # TODO: Deprecated since version 3.9. See Generic Alias Type and PEP 585.
    Callable,
    Iterable,
    Iterator,
)

import torch
import torch.nn.functional as F
from cytoolz import comp
from cytoolz.curried import map, reduce
from torch import Tensor, add, min
from torch.distributions import Distribution
from torch.nn.parameter import Parameter
from torch.optim import Optimizer

from .experience_replay import ExperienceReplay
from .neural_network import ActionCritic, StochasticActor


class SAC:
    """Soft Actor-Critic"""

    def __init__(
        self,
        device: torch.device,
        state_dim: int,
        action_dim: int,
        policy: Callable[[int, int], StochasticActor],
        critic: Callable[[int, int], ActionCritic],
        policy_optimiser: Callable[[Iterator[Parameter]], Optimizer],
        critic_optimiser: Callable[[Iterator[Parameter]], Optimizer],
        temperature_optimiser: Callable[[Iterable[Tensor]], Optimizer],
        experience_replay: ExperienceReplay,
        batch_size: int,
        discount_factor: float,
        target_smoothing_factor: float,  # Exponential smoothing
        num_critics: int = 2,
    ) -> None:

        self._policy = policy(state_dim, action_dim).to(device)
        self._critics = [
            deepcopy(critic(state_dim, action_dim).to(device))
            for _ in range(num_critics)
        ]
        self._target_critics = deepcopy(self._critics)
        # Freeze target critics with respect to optimisers (only update via Polyak averaging)
        [net.requires_grad_(False) for net in self._target_critics]

        self._policy_optimiser = policy_optimiser(self._policy.parameters())
        self._critic_optimisers = [
            critic_optimiser(critic.parameters()) for critic in self._critics
        ]

        self._experience_replay = experience_replay
        self._batch_size = batch_size

        self._discount_factor = discount_factor
        self._target_smoothing_factor = target_smoothing_factor

        # Using log value of temperature in temperature loss are generally nicer TODO: Why?
        # https://github.com/toshikwa/soft-actor-critic.pytorch/issues/2
        self._log_temperature = torch.zeros(1, requires_grad=True, device=device)
        self._temperature_optimiser = temperature_optimiser([self._log_temperature])

        # Differential entropy can be negative TODO: How to understand?
        # https://en.wikipedia.org/wiki/Entropy_(information_theory)#Differential_entropy
        self._target_entropy = -action_dim

    def step(
        self,
        state: Tensor,
        action: Tensor,
        reward: Tensor,
        next_state: Tensor,
        terminated: Tensor,
    ) -> None:
        self._experience_replay.push(state, action, reward, next_state, terminated)
        self._update_parameters()

    def _update_parameters(self) -> None:

        try:
            batch = self._experience_replay.sample(self._batch_size)
        except ValueError:
            return
        # fmt: off

        # Abbreviating to mathematical italic unicode char for readability
        ???? = batch.states
        ???? = batch.actions
        ???? = batch.rewards
        ?????? = batch.next_states
        ???? = batch.terminateds
        ???? = self._discount_factor
        ????_ = self._critics
        ??????_ = self._target_critics
        ???? = self._target_smoothing_factor
        log???? = self._log_temperature
        ???? = log??.exp().detach()  # FIXME
        ???? = self._target_entropy
        """
        ???? denotes the action distribution with infinite support (unbounded Gaussian)
        ???? denotes the tanh squashed ????
        """

        # Compute target action and its log-likelihood
        ??????: Distribution = self._policy(??????)
        u?? = ??????.rsample()  # Reparameterised sample
        # ???????????????????????????????????? ???????????????????????? ????????????????????????
        ?????? = torch.tanh(u??)  # Apply an invertible squashing function (tanh) to the Gaussian sample to get bounded action
        log?????? = ??????.log_prob(u??)
        log??????: Tensor = log?????? - 2 * (math.log(2) - u?? - F.softplus(-2 * u??))  # Employ change of variables formula (SAC 2018, app C, eq 21) to compute the likelihood of the bounded action
        """
        The second term is mathematically equivalent to log(1 - tanh(x)^2) but more
        numerically-stable.
        Derivation:
        log(1 - tanh(x)^2)
         = log(sech(x)^2)
         = 2 * log(sech(x))
         = 2 * log(2e^-x / (e^-2x + 1))
         = 2 * (log(2) - x - log(e^-2x + 1))
         = 2 * (log(2) - x - softplus(-2x))
        """
        log?????? = log??????.sum(dim=1, keepdim=True)  # TODO: Why?

        ???? = ???? + ~???? * ???? * (min(*[??????(??????, ??????) for ?????? in ??????_]) - ???? * log????)  # computes learning target
        action_values = [????(????, ????) for ???? in ????_]
        critic_loss_fn = comp(reduce(add), map(partial(F.mse_loss, target=????)))
        critic_loss: Tensor = critic_loss_fn(action_values)
        [critic_optimiser.zero_grad() for critic_optimiser in self._critic_optimisers]  # type: ignore
        critic_loss.backward()
        [critic_optimiser.step() for critic_optimiser in self._critic_optimisers]

        # Compute action and its log-likelihood
        ????: Distribution = self._policy(????)
        u = ????.rsample()
        # ???????????????????????????????????? ???????????????????????? ????????????????????????
        ?? = torch.tanh(u)  # denotes the action sampled fresh from the policy (whereas ???? denotes the action comes from the experience replay)
        log???? = ????.log_prob(u)
        log????: Tensor = log???? - 2 * (math.log(2) - u - F.softplus(-2 * u))
        log???? = log????.sum(dim=1, keepdim=True)
        # fmt: on

        policy_loss = (???? * log?? - min(*[????(????, ??) for ???? in ????_])).mean()
        self._policy_optimiser.zero_grad()
        policy_loss.backward()
        self._policy_optimiser.step()

        temperature_loss = (-log???? * (log????.detach() + ????)).mean()
        self._temperature_optimiser.zero_grad()
        temperature_loss.backward()
        self._temperature_optimiser.step()

        # Update frozen target critics by Polyak averaging (exponential smoothing)
        with torch.no_grad():
            for ????, ?????? in zip(????_, ??????_):
                for ????, ?????? in zip(????.parameters(), ??????.parameters()):
                    ??????.mul_(1.0 - ????)
                    ??????.add_(???? * ????)

    @torch.no_grad()
    def compute_action(self, state: Tensor) -> Tensor:
        return torch.tanh(self._policy(state).rsample())
