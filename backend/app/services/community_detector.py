import sys

from backend.app.services.community import detector as _detector

sys.modules[__name__] = _detector
