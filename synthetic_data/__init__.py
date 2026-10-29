"""synthetic-data 영역: 합성 데이터 생성 잡과 데이터셋 저장소(I2)."""
__version__ = "0.2.0"
from boundary_contracts import PIPELINE_SCHEMA_VERSION   # 이 영역이 쓰는 경계 계약 MAJOR.MINOR 
# 왜 계약에서 읽나: 숫자를 적어 두면 계약 MAJOR가 오를 때 저장소가 새 레코드를 거부한다(3.0.0 전환에서 겪음). 지원하는 MAJOR는 설치된 계약의 것이다
SUPPORTED_PIPELINE_MAJOR = int(PIPELINE_SCHEMA_VERSION.split(".")[0])
