from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(min_length=12, max_length=128)


class RegisterRequest(Credentials):
    display_name: str = Field(default="", max_length=40)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(max_length=40)


class Profile(BaseModel):
    user_id: str
    username: str
    display_name: str
    created_at: AwareDatetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: AwareDatetime
    user: Profile
