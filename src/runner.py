import subprocess
import tempfile
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _find_repo_root(path: Path) -> Path:
    for candidate in [path, *path.parents]:
        if (candidate / "main.py").exists() and (candidate / "src").is_dir():
            return candidate
    return path.parent


def run_pytest_targets(test_targets: list[str]) -> dict[str, Any]:
    """Execute pytest for one or more test targets and return metadata."""
    if not test_targets:
        return {
            "command": "",
            "return_code": 0,
            "passed": True,
            "output": "No test targets were selected.",
            "start_time_utc": None,
            "end_time_utc": None,
            "duration_seconds": 0.0,
        }

    normalized_targets = [str(Path(target)) for target in test_targets]
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--disable-warnings", *normalized_targets]

    start_time_iso = datetime.now(timezone.utc).isoformat()
    start_ts = time.time()

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as stdout_file, tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="ignore") as stderr_file:
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=str(_find_repo_root(Path(normalized_targets[0]).resolve())),
                timeout=120,
                check=False,
            )
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            return_code = 124

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().strip()
        stderr = stderr_file.read().strip()

    end_ts = time.time()
    end_time_iso = datetime.now(timezone.utc).isoformat()
    duration = round(end_ts - start_ts, 3)

    output = "\n".join(chunk for chunk in [stdout, stderr] if chunk)
    if return_code == 124:
        output = "\n".join(chunk for chunk in [output, "Pytest timed out after 120 seconds."] if chunk)

    return {
        "command": " ".join(command),
        "return_code": return_code,
        "passed": return_code == 0,
        "output": output,
        "start_time_utc": start_time_iso,
        "end_time_utc": end_time_iso,
        "duration_seconds": duration,
    }


def run_pytest(test_file: str) -> dict[str, Any]:
    """Execute pytest for the provided test file and return result metadata."""
    return run_pytest_targets([test_file])
