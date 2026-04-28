from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from formai.config import FormAIConfig

_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".venv311",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "tmp",
    "dist",
    "build",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_EXCLUDED_NAMES = {".DS_Store"}


@dataclass(frozen=True)
class ColabBenchmarkBundle:
    bundle_dir: Path
    workspace_archive: Path
    benchmark_spec: Path
    bootstrap_script: Path
    runner_script: Path
    readme_path: Path
    remote_output_dir: str
    benchmark_command: str


def prepare_colab_benchmark_bundle(
    *,
    config: FormAIConfig,
    dataset: str,
    split: str,
    max_samples: int,
    pack: str,
    output_dir: Path,
    provider: str,
    intake_backend: str,
    layout_backend: str,
    perception_backend: str,
    resolver_backend: str,
    region_adjudicator_backend: str,
    verification_backend: str,
    runner_backend: str,
) -> ColabBenchmarkBundle:
    output_dir.mkdir(parents=True, exist_ok=True)
    remote_output_dir = "/content/formai_outputs"
    archive_path = output_dir / "formai_workspace.tar.gz"
    spec_path = output_dir / "benchmark_spec.json"
    bootstrap_path = output_dir / "bootstrap_colab.py"
    runner_path = output_dir / "run_benchmark_in_colab.py"
    readme_path = output_dir / "README.md"

    _write_workspace_archive(config.working_dir, archive_path)

    spec = {
        "dataset": dataset,
        "split": split,
        "max_samples": max_samples,
        "pack": pack,
        "remote_output_dir": remote_output_dir,
        "provider": provider,
        "intake_backend": intake_backend,
        "layout_backend": layout_backend,
        "perception_backend": perception_backend,
        "resolver_backend": resolver_backend,
        "region_adjudicator_backend": region_adjudicator_backend,
        "verification_backend": verification_backend,
        "runner_backend": runner_backend,
    }
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    bootstrap_path.write_text(_bootstrap_script_text(), encoding="utf-8")
    runner_path.write_text(_runner_script_text(), encoding="utf-8")
    benchmark_command = (
        "python /content/formai_bundle/bootstrap_colab.py && "
        "python /content/formai_bundle/run_benchmark_in_colab.py"
    )
    readme_path.write_text(
        _readme_text(
            dataset=dataset,
            pack=pack,
            provider=provider,
            intake_backend=intake_backend,
            layout_backend=layout_backend,
            perception_backend=perception_backend,
            verification_backend=verification_backend,
            benchmark_command=benchmark_command,
            remote_output_dir=remote_output_dir,
        ),
        encoding="utf-8",
    )
    return ColabBenchmarkBundle(
        bundle_dir=output_dir,
        workspace_archive=archive_path,
        benchmark_spec=spec_path,
        bootstrap_script=bootstrap_path,
        runner_script=runner_path,
        readme_path=readme_path,
        remote_output_dir=remote_output_dir,
        benchmark_command=benchmark_command,
    )


def _write_workspace_archive(project_root: Path, archive_path: Path) -> None:
    include_paths = ["pyproject.toml", "README.md", "src", "tests"]
    with tarfile.open(archive_path, "w:gz") as tar:
        for relative in include_paths:
            path = project_root / relative
            if not path.exists():
                continue
            if path.is_file():
                tar.add(path, arcname=f"formai_workspace/{relative}")
                continue
            for child in path.rglob("*"):
                if not child.exists():
                    continue
                rel = child.relative_to(project_root)
                if _should_exclude(rel):
                    continue
                tar.add(child, arcname=f"formai_workspace/{rel.as_posix()}")


def _should_exclude(relative_path: Path) -> bool:
    parts = set(relative_path.parts)
    if parts & _EXCLUDED_DIRS:
        return True
    if relative_path.name in _EXCLUDED_NAMES:
        return True
    return relative_path.suffix in _EXCLUDED_SUFFIXES


def _bootstrap_script_text() -> str:
    return dedent(
        """
        from __future__ import annotations
        import os
        import shutil
        import subprocess
        import sys
        import tarfile
        from pathlib import Path

        BUNDLE_DIR = Path(os.environ.get("FORMAI_COLAB_BUNDLE_DIR", "/content/formai_bundle"))
        ARCHIVE_PATH = BUNDLE_DIR / "formai_workspace.tar.gz"
        WORKSPACE_ROOT = Path(
            os.environ.get("FORMAI_COLAB_WORKSPACE_ROOT", "/content/formai_workspace")
        )


        def _run(*args: str, cwd: Path | None = None) -> None:
            subprocess.check_call(list(args), cwd=str(cwd) if cwd else None)


        def main() -> None:
            if WORKSPACE_ROOT.exists():
                shutil.rmtree(WORKSPACE_ROOT)
            WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
            with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
                tar.extractall("/content")
            os.environ["HF_HUB_DISABLE_XET"] = "1"
            os.environ["PYTHONNOUSERSITE"] = "1"
            _run(sys.executable, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel")
            _run(
                sys.executable,
                "-m",
                "pip",
                "uninstall",
                "-y",
                "huggingface-hub",
                "hf-xet",
                "transformers",
                "tokenizers",
                "chandra-ocr",
            )
            _run(
                sys.executable,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-cache-dir",
                "-U",
                "jedi>=0.19.2",
                "huggingface-hub==1.8.0",
                "hf-xet==1.4.3",
                "transformers==5.4.0",
                "accelerate>=1.11.0",
                "chandra-ocr[hf]==0.2.0",
            )
            _run(
                sys.executable,
                "-m",
                "pip",
                "install",
                "-e",
                ".[benchmarks,local_vlm]",
                cwd=WORKSPACE_ROOT,
            )
            _run(
                sys.executable,
                "-c",
                (
                    "import huggingface_hub.utils as hub_utils; "
                    "from transformers import AutoModelForImageTextToText, AutoProcessor; "
                    "from chandra.model.hf import load_model; "
                    "print('formai-colab-bootstrap-ok', "
                    "hasattr(hub_utils, 'XetConnectionInfo'))"
                ),
            )


        if __name__ == "__main__":
            main()
        """
    ).strip() + "\n"


def _runner_script_text() -> str:
    return dedent(
        """
        from __future__ import annotations

        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        BUNDLE_DIR = Path(os.environ.get("FORMAI_COLAB_BUNDLE_DIR", "/content/formai_bundle"))
        WORKSPACE_ROOT = Path(
            os.environ.get("FORMAI_COLAB_WORKSPACE_ROOT", "/content/formai_workspace")
        )
        SPEC_PATH = BUNDLE_DIR / "benchmark_spec.json"


        def main() -> None:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            out_dir = Path(
                os.environ.get("FORMAI_COLAB_REMOTE_OUTPUT_DIR", spec["remote_output_dir"])
            ).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable,
                "-m",
                "formai.cli",
                "benchmark",
                "--dataset",
                spec["dataset"],
                "--split",
                spec["split"],
                "--max-samples",
                str(spec["max_samples"]),
                "--pack",
                spec["pack"],
                "--provider",
                spec["provider"],
                "--intake-backend",
                spec["intake_backend"],
                "--layout-backend",
                spec["layout_backend"],
                "--perception-backend",
                spec["perception_backend"],
                "--resolver-backend",
                spec["resolver_backend"],
                "--region-adjudicator-backend",
                spec["region_adjudicator_backend"],
                "--verification-backend",
                spec["verification_backend"],
                "--runner-backend",
                spec["runner_backend"],
                "--out-dir",
                str(out_dir),
            ]
            env = dict(os.environ)
            env["HF_HUB_DISABLE_XET"] = "1"
            pythonpath = str(WORKSPACE_ROOT / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = pythonpath if not existing else f"{pythonpath}:{existing}"
            subprocess.check_call(command, cwd=str(WORKSPACE_ROOT), env=env)


        if __name__ == "__main__":
            main()
        """
    ).strip() + "\n"


def _readme_text(
    *,
    dataset: str,
    pack: str,
    provider: str,
    intake_backend: str,
    layout_backend: str,
    perception_backend: str,
    verification_backend: str,
    benchmark_command: str,
    remote_output_dir: str,
) -> str:
    return dedent(
        f"""
        # FormAI Colab Benchmark Bundle

        Bu paket, FormAI benchmark'ını Google Colab GPU üzerinde çalıştırmak için üretildi.

        Önerilen stack:
        - provider: `{provider}`
        - intake: `{intake_backend}`
        - layout: `{layout_backend}`
        - perception: `{perception_backend}`
        - verification: `{verification_backend}`
        - dataset: `{dataset}`
        - pack: `{pack}`

        Colab'da bundle'ı `/content/formai_bundle` altına koyduktan sonra tek komut:

        ```bash
        {benchmark_command}
        ```

        Çıktılar:
        - remote output dir: `{remote_output_dir}`
        - benchmark summary: `{remote_output_dir}/summary.json`

        Not:
        - `colab-mcp` bağlandığında bu bundle notebook içine kopyalanıp doğrudan koşturulabilir.
        - Bu bundle yerel Ollama gerektirmez; HF tabanlı `glm_ocr`, `chandra` ve `surya` lane'i için hazırlanmıştır.
        """
    ).strip() + "\n"
