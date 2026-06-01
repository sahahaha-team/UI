import os
from dotenv import load_dotenv

load_dotenv()

# ===== 크롤링 대상 =====
BASE_URL = "https://www.saha.go.kr"

TARGET_MENUS = {
    "분야별정보": "/portal/contents.do?mId=0401000000",
    "사하복지": "/portal/contents.do?mId=0501000000",
    "전자민원": "/portal/contents.do?mId=0100000000",
    "정보공개": "/portal/contents.do?mId=0300000000",
    "구민참여": "/portal/contents.do?mId=0200000000",
    "사하소개": "/portal/contents.do?mId=0600000000",
}

# ===== 크롤러 설정 =====
CRAWL_DELAY = 1.0
MAX_PAGES_PER_MENU = 50
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3

# ===== Supabase 설정 (PostgreSQL + pgvector) =====
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # anon/public key

# ===== LLM 설정 (Groq - 무료 티어 한도 초과 우회용 임시 변경) =====
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# 💡 기존 "llama-3.3-70b-versatile" 모델의 일일 한도 초과로 인해, 한도가 넉넉한 3.1 8B 모델로 임시 교체합니다.
GROQ_LLM_MODEL = "llama-3.1-8b-instant"

# ===== 청크 설정 =====
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# ===== 챗봇 설정 =====
MAX_CONVERSATION_HISTORY = 10
MAX_RETRIEVAL_RESULTS = 5
CHATBOT_TEMPERATURE = 0.3

# ===== Flask 설정 =====
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY를 .env에 설정해주세요 (세션 위조 방지)")

# ===== 관리자 API 인증 =====
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# ===== Supabase service role 키 (관리자 작업용, RLS 우회) =====
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ===== CORS 허용 출처 (위젯 임베딩) =====
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "https://www.saha.go.kr").split(",")
    if o.strip()
]

# ===== Rate Limiting =====
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "10 per minute")

# ===== 대화 이력 TTL (일 단위) =====
CONVERSATION_TTL_DAYS = int(os.getenv("CONVERSATION_TTL_DAYS", "30"))

# ===== 하이브리드 검색 가중치 (벡터:BM25) =====
HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.7"))
HYBRID_BM25_WEIGHT = float(os.getenv("HYBRID_BM25_WEIGHT", "0.3"))
HYBRID_BM25_TOP_N = int(os.getenv("HYBRID_BM25_TOP_N", "30"))
