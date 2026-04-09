import sys
from pathlib import Path

# mlops 루트를 sys.path에 추가하여 mlops.pipeline 임포트 가능하게 함
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
