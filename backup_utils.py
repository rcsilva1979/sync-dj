import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


def _resolve_backup_dir(backup_dir: Optional[str | os.PathLike[str]] = None) -> Path:
    if backup_dir is None:
        return Path.home() / "Documents" / "Sync_DJ" / "Backup_DB"
    return Path(backup_dir)


def create_database_file_backup(db_path, backup_dir=None, prefix: str = "backup") -> Optional[Path]:
    """Cria um backup simples de um arquivo SQLite em disco, com timestamp."""
    source_path = Path(db_path)
    if not source_path.exists():
        return None

    target_dir = _resolve_backup_dir(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = target_dir / f"{source_path.name}.{prefix}-{timestamp}"
    shutil.copy2(source_path, backup_path)
    return backup_path


def create_database_backup(db_path, backup_dir=None, archive_name_prefix: str = "Backup_Engine_Drive") -> Optional[str]:
    """Cria um backup compactado em ZIP do diretório do banco de dados."""
    source_path = Path(db_path)
    if not source_path.exists():
        return None

    source_dir = source_path.parent
    target_dir = _resolve_backup_dir(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    drive = source_path.drive.replace(":", "").replace(" ", "_") or "PC"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_base = target_dir / f"{archive_name_prefix}_{drive}_{timestamp}"
    shutil.make_archive(str(archive_base), "zip", str(source_dir))
    return f"{archive_base}.zip"
