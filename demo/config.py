from pydantic import BaseModel, validator
from omegaconf import OmegaConf


class EnvConfig(BaseModel):
    gym_name: str
    num_episodes: int
    device: str


class TD3Config(BaseModel):
    hidden_dims: list[int]
    actor_lr : float
    critic_lr: float
    weight_decay: float
    memory_capacity: int
    batch_size: int
    discount_factor: float
    polyak: float
    clip_bound: float
    stddev: float
    action_noise_stddev: float
    action_noise_decay_const: float

    def __init__(self, **data):
        data['hidden_dims'] = OmegaConf.to_object(data['hidden_dims'])
        super().__init__(**data)

    @validator('polyak')
    def polyak_is_between_0_and_1(cls, v):
        assert 0 <= v <= 1
        return v