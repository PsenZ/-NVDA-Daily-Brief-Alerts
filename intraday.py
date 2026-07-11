import logging
import sys

from veyraquant.config import AppConfig
from veyraquant.triggers import run_intraday_check


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_intraday_check(AppConfig.from_env())


if __name__ == "__main__":
    sys.exit(main())
