"""
Rate limiting (tiêu chí 7).

Yêu cầu:
  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429, nên kèm header Retry-After
  • State lưu trong Redis để mọi worker / instance dùng chung và vẫn còn sau khi
    restart agent (script chấm sẽ restart agent để kiểm tra)
"""
import time
import uuid
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r


def check_rate_limit(key: str) -> None:
    """Sliding window rate limit bằng Redis sorted set."""
    now = time.time()
    window = 60
    redis_key = f"ratelimit:{key}"

    r.zremrangebyscore(redis_key, 0, now - window)
    count = r.zcard(redis_key)

    if count >= settings.rate_limit_per_minute:
        oldest = r.zrange(redis_key, 0, 0, withscores=True)
        retry_after = max(1, int(window - (now - oldest[0][1]))) if oldest else window
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    member = f"{now}:{uuid.uuid4().hex}"
    r.zadd(redis_key, {member: now})
    r.expire(redis_key, window)
