# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os
import sys

if __name__ == "__main__":
    # `python -m tukuroi` puts the current directory first on sys.path (unless
    # with -P or PYTHONSAFEPATH). Take it off, as for the `tukuroi` script, so
    # that the modules imported from here on (the formatters, rich, pygls) are
    # not read from the directory being linted. See "Security" in the docs.
    if not sys.flags.safe_path and sys.path and sys.path[0] == os.getcwd():
        del sys.path[0]

    from tukuroi.cli import main

    main()
