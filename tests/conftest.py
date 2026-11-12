import sys
import os

# Add the agente directory to the path so `sistema.*` imports work
agente_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agente")
if agente_path not in sys.path:
    sys.path.insert(0, agente_path)