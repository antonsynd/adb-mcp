# MIT License
#
# Copyright (c) 2025 Mike Chambers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
import logging

# Configure root logger to write to stderr with ISO timestamps and log level
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s : %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
)

logging.root.addHandler(_handler)
logging.root.setLevel(logging.DEBUG)

_logger = logging.getLogger("adb_mcp")


def log(message: str, filter_tag: str = "LOGGER") -> None:
    """Log *message* at INFO level using a child logger named after *filter_tag*."""
    logging.getLogger(f"adb_mcp.{filter_tag}").info(message)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the adb_mcp namespace."""
    return logging.getLogger(f"adb_mcp.{name}")

