# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Hugging Face repository settings shared by every upload (datasets now, models later).

Project rule: every repository we publish has Community contributions (Discussions and Pull
Requests) turned off. ``huggingface_hub`` has no argument for this, so the settings endpoint is
called directly and the result is checked by listing discussions (403 when disabled).
"""

from huggingface_hub import HfApi
from huggingface_hub.utils import get_session, hf_raise_for_status


def _url(api: HfApi, repo_id: str, repo_type: str, suffix: str) -> str:
    return f"{api.endpoint}/api/{repo_type}s/{repo_id}/{suffix}"


def community_disabled(api: HfApi, repo_id: str, repo_type: str) -> bool:
    r = get_session().get(
        _url(api, repo_id, repo_type, "discussions"), headers=api._build_hf_headers()
    )
    return r.status_code == 403 and "disabled" in r.text.lower()


def disable_community(api: HfApi, repo_id: str, repo_type: str) -> None:
    """Turn off Discussions / Pull Requests and verify it; raises if it did not take effect."""
    r = get_session().put(
        _url(api, repo_id, repo_type, "settings"),
        headers=api._build_hf_headers(),
        json={"discussionsDisabled": True},
    )
    hf_raise_for_status(r)
    if not community_disabled(api, repo_id, repo_type):
        raise RuntimeError(f"community contributions are still enabled on {repo_id}")
