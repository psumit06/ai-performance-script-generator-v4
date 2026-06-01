from operator import gt

from pydantic import BaseModel, Field

class Config(BaseModel):
    users: int = Field(default=1, gt=0, description="Number of virtual users")  
    ramp_up: int = Field(default=1, gt=0, description="Ramp-up time in seconds")
    duration: int = Field(default=60, gt=0, description="Duration of the test in seconds")
    think_time: int = Field(default=1000, gt=0, description="Think time in milli-seconds")

class GenerateRequest(BaseModel):
    provider: str
    api_spec: str
    config: Config