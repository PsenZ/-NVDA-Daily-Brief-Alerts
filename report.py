import logging
import sys

from veyraquant.config import AppConfig
from veyraquant.runner import run


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(AppConfig.from_env())


if __name__ == "__main__":
    sys.exit(main())
