"""LibTV backend. No Atlas network calls and no automatic paid resubmission."""
class ProviderError(RuntimeError):
    pass


def get_provider(name=None, project_dir=None, config=None):
    if name not in (None, "libtv", "libtv_cli"):
        raise ProviderError(f"Unsupported provider {name!r}; run pipeline.py migrate")
    from libtv_provider import LibTVProvider
    return LibTVProvider(project_dir, config=config)


def run_jobs(prov, specs, **legacy_poll_options):
    """CLI --run waits for its terminal receipt; polling options are obsolete."""
    done = {}
    for key, submit in specs.items():
        prov.job_label = str(key)
        print(f"[{key}] starting / recovering", flush=True)
        job = submit()
        result = prov.get_status(job)
        if result["status"] != "completed" or not result.get("output"):
            raise ProviderError(f"[{key}] {result['status']}: {result.get('error')}; "
                                "existing task retained; no automatic resubmission")
        done[key] = result["output"]
        print(f"[{key}] completed", flush=True)
    return done
