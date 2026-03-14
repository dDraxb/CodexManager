from app.core.settings import load_settings

_settings = load_settings()

APP_HOME = _settings.app_home
SESSIONS_DIR = _settings.sessions_dir
WORKTREES_DIR = _settings.worktrees_dir
DB_PATH = _settings.db_path
