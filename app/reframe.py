"""Per-clip render recipes, so "Reframe" can re-render ONE clip.

Every clip already goes through ``clipper.generate_clip(source_mp4, start,
end, opts)`` inside the batch pipeline (see ``jobs.py``). To let a user
manually reposition the crop later without re-running the whole
download -> transcribe -> select -> render pipeline for every other clip,
jobs.py saves the exact arguments that produced each clip here, keyed by
``clip_id`` + ``index``.

In v2.0, recipes are cached in memory for zero-latency retrieval AND persisted
to the SQLite datastore so reframing survives server restarts and crashes.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional
from app.database.session import db_session
from app.database.repository import Repository

logger = logging.getLogger(__name__)

_RECIPES: dict[str, dict] = {}
_LOCK = threading.Lock()


def _key(clip_id: str, index: int) -> str:
    return f"{clip_id}:{index}"


def save_recipe(clip_id: str, index: int, *, source_mp4: Path, start: float, end: float, opts_kwargs: dict) -> None:
    """Record what produced ``clips/<clip_id>/<index>.mp4`` for later reframing."""
    recipe = {
        "source_mp4": str(source_mp4),
        "start": start,
        "end": end,
        "opts_kwargs": opts_kwargs,
    }
    with _LOCK:
        _RECIPES[_key(clip_id, index)] = recipe

    # Persist into SQLite database
    try:
        with db_session() as session:
            repo = Repository(session)
            db_clip_id = f"{clip_id}_{index}"
            clip = repo.get_clip(db_clip_id)
            if clip:
                repo.update_clip_recipe(db_clip_id, recipe)
            else:
                # If clip not yet created, create minimal record
                repo.create_clip(
                    clip_id=db_clip_id,
                    job_id=clip_id,
                    clip_index=index,
                    start_seconds=start,
                    end_seconds=end,
                    output_path=str(Path(source_mp4).parent / f"{index}.mp4"),
                    render_recipe_json=json.dumps(recipe),
                )
    except Exception as e:
        logger.debug("Could not persist recipe for %s:%d to database: %s", clip_id, index, e)


def get_recipe(clip_id: str, index: int) -> Optional[dict]:
    """Retrieve render recipe from memory cache or SQLite persistence."""
    k = _key(clip_id, index)
    with _LOCK:
        recipe = _RECIPES.get(k)
        if recipe:
            return dict(recipe)

    # Fallback to SQLite
    try:
        with db_session() as session:
            repo = Repository(session)
            db_clip_id = f"{clip_id}_{index}"
            clip = repo.get_clip(db_clip_id)
            if clip and clip.render_recipe_json:
                data = json.loads(clip.render_recipe_json)
                with _LOCK:
                    _RECIPES[k] = data
                return dict(data)
    except Exception as e:
        logger.debug("Failed querying recipe from database for %s:%d: %s", clip_id, index, e)

    return None
