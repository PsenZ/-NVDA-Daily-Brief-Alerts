import logging
import sys

from veyraquant.config import AppConfig
from veyraquant.triggers import run_premarket_briefing


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_premarket_briefing(AppConfig.from_env())


if __name__ == "__main__":
    sys.exit(main())
