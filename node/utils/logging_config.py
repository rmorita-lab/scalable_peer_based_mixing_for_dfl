import logging
import os

from utils.exception_decorator import log_exceptions

LOG_COLORS = {
    "DEBUG": "\033[96;1m",
    "INFO": "\033[97;1m",
    "WARNING": "\033[95;1m",
    "ERROR": "\033[91;1m",
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = LOG_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{RESET}"
        record.msg = f"{color}{record.msg}{RESET}"
        return super().format(record)


@log_exceptions
def setup_logging(node_id):
    handler = logging.StreamHandler()
    formatter = ColorFormatter(fmt=f"[Node {node_id}] %(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    root.setLevel(log_level)

    logging.getLogger("quic").setLevel(logging.WARNING)
    logging.getLogger("aioquic").setLevel(logging.WARNING)


def log_header(title):
    pad = 30 - len(title) // 2
    logging.info("")
    logging.info(f"{'=' * pad} {title} {'=' * pad}")
