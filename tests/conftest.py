import sys
from unittest.mock import MagicMock

# Mock google.generativeai and google.auth before tests run
sys.modules['google.generativeai'] = MagicMock()
sys.modules['google.generativeai.types'] = MagicMock()
sys.modules['google.generativeai.types.content_types'] = MagicMock()
sys.modules['google.auth'] = MagicMock()
sys.modules['google_auth_oauthlib'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['pyaudio'] = MagicMock()
sys.modules['speech_recognition'] = MagicMock()
