"""un-subscribird: collect feeder visits, pre-label with a local VLM, confirm by hand, train."""

import os

__version__ = "0.28.0"

# What the pages and /api/stats show. A pre-release image (the :edge channel) is built with UNSUB_BUILD=edge
# and shows as "0.28.0-edge"; a release or a local build shows the plain version.
version_label = __version__ + (f"-{os.environ['UNSUB_BUILD']}" if os.environ.get("UNSUB_BUILD") else "")
