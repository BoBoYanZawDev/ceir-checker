from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> None:
    from app.config import app_data_dir

    # Packaged applications must not create or emit log files.
    if getattr(sys, "frozen", False):
        logging.disable(logging.CRITICAL)
        return

    log_dir = app_data_dir()
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_dir / "ceir-checker.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )

    # Detailed traffic can contain ALTCHA tokens and applicant information.
    # Keep it opt-in and unavailable in packaged applications.
    if "--debug" in sys.argv:
        debug_log_path = Path(__file__).resolve().parent / "ceir-api-debug.log"
        api_handler = RotatingFileHandler(
            debug_log_path,
            maxBytes=5_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        api_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        api_logger = logging.getLogger("ceir.api")
        api_logger.setLevel(logging.DEBUG)
        api_logger.addHandler(api_handler)
        api_logger.propagate = False
        logging.getLogger(__name__).warning(
            "Detailed CEIR API debug logging enabled: %s",
            debug_log_path,
        )


def main() -> None:
    if "--altcha-browser-worker" in sys.argv:
        from app.services.altcha_browser import main as run_altcha_browser_worker

        run_altcha_browser_worker()
        return

    configure_logging()

    from app.config import database_path
    from app.database import Database
    from app.repositories.calculation_repository import CalculationRepository
    from app.views.main_window import MainWindow

    repository = CalculationRepository(Database(database_path()))
    app = MainWindow(repository)
    app.mainloop()


if __name__ == "__main__":
    main()
