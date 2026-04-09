from worker.main import run


def test_worker_entrypoint_exists() -> None:
    assert callable(run)
