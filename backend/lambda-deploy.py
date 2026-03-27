import os
import shutil
import subprocess
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = ROOT_DIR / "lambda-package"
ZIP_PATH = ROOT_DIR / "lambda-deployment.zip"

EXCLUDE_DIRS = {".venv", "__pycache__", "memory", "lambda-package", ".git"}
EXCLUDE_FILES = {".env", "mcp.sqlite3"}


def _reset_output() -> None:
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)


def _install_dependencies() -> None:
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT_DIR}:/var/task",
            "--platform",
            "linux/amd64",
            "--entrypoint",
            "",
            "public.ecr.aws/lambda/python:3.12",
            "/bin/sh",
            "-c",
            "pip install --target /var/task/lambda-package -r /var/task/requirements.txt --platform manylinux2014_x86_64 --only-binary=:all: --upgrade",
        ],
        check=True,
    )


def _should_skip_dir(path: Path) -> bool:
    return path.name in EXCLUDE_DIRS


def _should_skip_file(path: Path) -> bool:
    return path.name in EXCLUDE_FILES


def _copy_sources() -> None:
    for root, dirs, files in os.walk(ROOT_DIR):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not _should_skip_dir(Path(d))]
        if _should_skip_dir(root_path):
            continue
        for filename in files:
            file_path = root_path / filename
            if _should_skip_file(file_path):
                continue
            if file_path.suffix != ".py":
                continue
            dest = PACKAGE_DIR / file_path.relative_to(ROOT_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)


def _zip_package() -> None:
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(PACKAGE_DIR):
            root_path = Path(root)
            for filename in files:
                file_path = root_path / filename
                zipf.write(file_path, file_path.relative_to(PACKAGE_DIR))


def main() -> None:
    print("Creating Lambda deployment package...")
    _reset_output()
    print("Installing dependencies in Lambda runtime container...")
    _install_dependencies()
    print("Copying application sources...")
    _copy_sources()
    print("Creating zip file...")
    _zip_package()
    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"Created lambda-deployment.zip ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
