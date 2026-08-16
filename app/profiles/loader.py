from pathlib import Path

import yaml

from app.profiles.models import ProfileConfig


def load_profiles(directory: Path) -> list[ProfileConfig]:
    profiles = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as file:
            profiles.append(ProfileConfig.model_validate(yaml.safe_load(file)))
    if not profiles:
        raise ValueError(f"No profiles found in {directory}")
    slugs = [profile.slug for profile in profiles]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Profile slugs must be unique")
    return profiles
