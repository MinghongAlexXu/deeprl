import math
from datetime import datetime
from functools import partial
from pathlib import Path

import gymnasium as gym
import torch
import torch.optim as optim
from torch.utils.tensorboard import SummaryWriter

from deeprl.actor_critic_methods import SAC
from deeprl.actor_critic_methods.neural_network import mlp
from deeprl.actor_critic_methods.experience_replay import UER


def train() -> None:

    # env = gym.make("HalfCheetah-v4")
    env = gym.make("InvertedDoublePendulum-v4")
    device = torch.device("cuda:1")

    agent = SAC(
        device,
        math.prod(env.observation_space.shape),
        math.prod(env.action_space.shape),
        partial(mlp.GaussianPolicy, hidden_dims=[256, 256]),
        partial(mlp.ActionValue, hidden_dims=[256, 256]),
        partial(optim.Adam, lr=3e-4),
        partial(optim.Adam, lr=3e-4),
        partial(optim.Adam, lr=3e-4),
        UER(1_000_000),
        256,
        0.99,
        5e-3,
    )

    with SummaryWriter(log_dir=Path(__file__).resolve().parent/'.logs'/'SAC'/f'{env.spec.name}-v{env.spec.version}'/f'{datetime.now().strftime("%Y%m%d%H%M")}') as writer:
        for episode in range(100_000):
            state, _ = env.reset()
            state = torch.tensor(state, device=device, dtype=torch.float32)
            episodic_return = torch.zeros(1, device=device)

            while True:
                action = agent.compute_action(state)

                next_state, reward, terminated, truncated, _ = env.step(action.cpu().numpy())
                next_state = torch.tensor(next_state  , device=device, dtype=torch.float32)
                # Convert to size(1,) tensor
                reward     = torch.tensor([reward]    , device=device, dtype=torch.float32)
                terminated = torch.tensor([terminated], device=device, dtype=torch.bool)

                episodic_return += reward
                # Store a transition in the experience replay and perform one step of the optimisation
                agent.step(state, action, reward, next_state, terminated)

                if terminated or truncated:
                    break
                # Move to the next state
                state = next_state

            # Logging
            writer.add_scalar(f'{env.spec.name}-v{env.spec.version}/episodic_return', episodic_return.item(), episode)


if __name__ == '__main__':
    train()
