from __future__ import annotations

import logging

from app.config import database_path
from app.database import Database
from app.repositories.calculation_repository import CalculationRepository
from app.views.main_window import MainWindow


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    repository = CalculationRepository(Database(database_path()))
    app = MainWindow(repository)
    app.mainloop()


if __name__ == "__main__":
    main()
