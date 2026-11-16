"""Calls every /v1 endpoint with DYNASTY_API_KEY and validates the responses
against the generated models. Read-only. Usage: uv run --project python python scripts/live/check.py"""
import inspect
import os
import sys

from cfb27_dynasty import DynastyClient, DynastyAPIError

c = DynastyClient(os.environ["DYNASTY_API_KEY"], base_url=os.environ.get("DYNASTY_BASE_URL"))
failed = 0
sched = c.list_schedule()
game_key = next((g.key for g in sched.data), None) if hasattr(sched.data[0] if sched.data else None, "key") else None
for name, fn in inspect.getmembers(c, inspect.ismethod):
    if name.startswith("_") or name in ("close", "with_dynasty"):
        continue
    params = [p for p in inspect.signature(fn).parameters.values() if p.kind == p.POSITIONAL_OR_KEYWORD]
    try:
        if params:
            if game_key is None:
                print(f"skip  {name} (no game key)")
                continue
            res = fn(game_key)
        else:
            res = fn()
        n = len(res.data) if isinstance(getattr(res, "data", None), list) else 1
        extra = res.model_extra or {}
        print(f"ok    {name} ({n})" + (f" extra fields: {sorted(extra)}" if extra else ""))
    except DynastyAPIError as e:
        print(f"api   {name}: {e}")
    except Exception as e:  # validation errors
        failed += 1
        print(f"FAIL  {name}: {str(e)[:600]}")
sys.exit(1 if failed else 0)
