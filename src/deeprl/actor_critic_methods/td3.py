from copy import deepcopy
from functools import partial
from itertools import cycle

# from collections.abc import Callable, Iterator
from typing import Union  # TODO: Unnecessary since version 3.10. See PEP 604.
from typing import (  # TODO: Deprecated since version 3.9. See Generic Alias Type and PEP 585.
    Callable,
    Iterator,
)

import torch
import torch.nn.functional as F
from cytoolz import comp
from cytoolz.curried import map, reduce
from torch import Tensor, add, min
from torch.nn.parameter import Parameter
from torch.optim import Optimizer

from .experience_replay import ExperienceReplay
from .neural_network import ActionCritic, DeterministicActor
from .noise_injection.action_space import ActionNoise, Gaussian


class TD3:
    """Twin-Delayed DDPG"""

    def __init__(
        self,
        device: torch.device,
        state_dim: int,
        action_dim: int,
        policy: Callable[[int, int], DeterministicActor],
        critic: Callable[[int, int], ActionCritic],
        policy_optimiser: Callable[[Iterator[Parameter]], Optimizer],
        critic_optimiser: Callable[[Iterator[Parameter]], Optimizer],
        experience_replay: ExperienceReplay,
        batch_size: int,
        discount_factor: float,
        target_smoothing_factor: float,
        policy_noise: Union[ActionNoise, None],
        smoothing_noise_stddev: float,
        smoothing_noise_clip: float,  # Norm length to clip target policy smoothing noise
        num_critics: int = 2,
        policy_delay: int = 2,
    ) -> None:

        self._policy = policy(state_dim, action_dim).to(device)
        self._critics = [
            deepcopy(critic(state_dim, action_dim).to(device))
            for _ in range(num_critics)
        ]
        self._target_policy = deepcopy(self._policy)
        self._target_critics = deepcopy(self._critics)
        # Freeze target networks with respect to optimisers (only update via Polyak averaging)
        self._target_policy.requires_grad_(False)
        [net.requires_grad_(False) for net in self._target_critics]

        self._policy_optimiser = policy_optimiser(self._policy.parameters())
        self._critic_optimisers = [
            critic_optimiser(critic.parameters()) for critic in self._critics
        ]

        self._experience_replay = experience_replay
        self._batch_size = batch_size

        self._discount_factor = discount_factor
        self._target_smoothing_factor = target_smoothing_factor
        self._policy_noise = policy_noise
        self._smoothing_noise_clip = smoothing_noise_clip
        self._smoothing_noise_stddev = smoothing_noise_stddev
        self._policy_delay = cycle(range(policy_delay))

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

        # Abbreviating to mathematical italic unicode char for readability
        ???? = batch.states
        ???? = batch.actions
        ???? = batch.rewards
        ?????? = batch.next_states
        ???? = batch.terminateds
        ???? = self._discount_factor
        ???? = self._smoothing_noise_stddev
        ???? = self._smoothing_noise_clip
        ???? = self._policy  # Deterministic policy is usually denoted by ????
        ?????? = self._target_policy
        ????_ = self._critics
        ??????_ = self._target_critics
        ???? = self._target_smoothing_factor

        # Compute target action
        ??????: Tensor = ??????(??????)

        # Target policy smoothing: add clipped noise to the target action
        ?? = ?????? + ??????.clone().normal_(0, ????).clamp_(-????, ????)
        ??.clamp_(-1, 1)  # clipped to lie in valid action range FIXME: hard-code range

        # Clipped double-Q learning
        ???? = ???? + ~???? * ???? * min(*[??????(??????, ??) for ?????? in ??????_])  # computes learning target
        action_values = [????(????, ????) for ???? in ????_]
        critic_loss_fn = comp(reduce(add), map(partial(F.mse_loss, target=????)))
        critic_loss: Tensor = critic_loss_fn(action_values)
        [critic_optimiser.zero_grad() for critic_optimiser in self._critic_optimisers]  # type: ignore
        critic_loss.backward()
        [critic_optimiser.step() for critic_optimiser in self._critic_optimisers]

        # "Delayed" policy updates
        if next(self._policy_delay) == 0:

            # Improve the deterministic policy just by maximizing the first Q function approximator by gradient ascent
            policy_loss: Tensor = -????_[0](????, ????(????)).mean()
            self._policy_optimiser.zero_grad()
            policy_loss.backward()
            self._policy_optimiser.step()

            # Update frozen target networks by Polyak averaging (exponential smoothing)
            with torch.no_grad():  # stops target param from requesting grad after calc because original param require grad are involved in the calc
                for ????, ?????? in zip(????_, ??????_):
                    for ????, ?????? in zip(????.parameters(), ??????.parameters()):
                        ??????.mul_(1.0 - ????)
                        ??????.add_(???? * ????)
                for ????, ?????? in zip(????.parameters(), ??????.parameters()):
                    ??????.mul_(1.0 - ????)
                    ??????.add_(???? * ????)

    @torch.no_grad()
    def compute_action(self, state: Tensor) -> Tensor:
        action: Tensor = self._policy(state)
        # TODO: Avaliable since version 3.10. See PEP 634
        # match self._policy_noise:
        #     case Gaussian():
        #     case _:
        if isinstance(self._policy_noise, Gaussian):
            action += self._policy_noise(action.size(), action.device)
            action.clamp_(-1, 1)  # FIXME: hard-code action range
        return action
