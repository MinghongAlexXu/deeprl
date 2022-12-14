import math
from functools import partial
from pathlib import Path

import gymnasium as gym
import hydra
import torch
import torch.optim as optim
import wandb
from omegaconf import DictConfig, OmegaConf

from conf import EnvConfig, TD3Config
from deeprl.actor_critic_methods import TD3
from deeprl.actor_critic_methods.neural_network import mlp
from deeprl.actor_critic_methods.experience_replay import UER
from deeprl.actor_critic_methods.noise_injection.action_space import Gaussian


@hydra.main(version_base=None, config_path='conf', config_name='train_td3')
def train(cfg: DictConfig) -> None:
    env_cfg = EnvConfig(**cfg['env'])
    td3_cfg = TD3Config(**cfg['td3'])

    env = gym.make(env_cfg.name)
    device = torch.device(env_cfg.device)

    agent = TD3(
        device,
        math.prod(env.observation_space.shape),
        math.prod(env.action_space.shape),
        partial(mlp.Policy, hidden_dims=td3_cfg.hidden_dims),
        partial(mlp.ActionValue, hidden_dims=td3_cfg.hidden_dims),
        partial(optim.Adam, lr=td3_cfg.actor_lr),
        partial(optim.Adam, lr=td3_cfg.critic_lr),
        UER(td3_cfg.memory_capacity),
        td3_cfg.batch_size,
        td3_cfg.discount_factor,
        td3_cfg.target_smoothing_factor,
        Gaussian(td3_cfg.action_noise_stddev),
        td3_cfg.smoothing_noise_stddev,
        td3_cfg.smoothing_noise_clip,
    )

    run = wandb.init(project="TD3_HPs_tuning", config=OmegaConf.to_container(cfg, resolve=True))

    for episode in range(env_cfg.num_episodes):
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

        run.log({
            "episodic_return": episodic_return,
        })


if __name__ == '__main__':
    train()
