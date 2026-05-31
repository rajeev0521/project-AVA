"""
Rate limiter for Gemini API free tier.
Ensures AVA stays within: 15 RPM, 1,500 RPD.
Provides both sync and async interfaces.
"""

import time
import asyncio
from collections import deque
from datetime import datetime, date
from threading import Lock

from .logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Sliding-window rate limiter for Gemini free tier.
    
    Limits:
        - 15 requests per minute (RPM)
        - 1,500 requests per day (RPD)
    
    Usage (sync):
        limiter = RateLimiter()
        limiter.wait_if_needed()  # blocks if at limit
        # ... make API call ...
        limiter.record_request()
    
    Usage (async):
        wait_time = limiter.check_rate_limit()  # non-blocking check
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        limiter.record_request()
    """
    
    MAX_RPM = 15
    MAX_RPD = 1500
    
    def __init__(self, max_rpm: int = None, max_rpd: int = None):
        self.max_rpm = max_rpm or self.MAX_RPM
        self.max_rpd = max_rpd or self.MAX_RPD
        
        self._minute_window: deque = deque()  # timestamps of requests in last 60s
        self._daily_count = 0
        self._daily_date = date.today()
        self._lock = Lock()
    
    def check_rate_limit(self) -> float:
        """
        Non-blocking check — returns seconds to wait (0.0 if ok).
        Raises RateLimitExceeded if daily limit hit.
        Thread-safe via threading.Lock (safe to call from asyncio.to_thread too).
        """
        with self._lock:
            # Reset daily counter if new day
            today = date.today()
            if today != self._daily_date:
                self._daily_count = 0
                self._daily_date = today
                logger.info("Daily rate limit counter reset")
            
            # Check daily limit
            if self._daily_count >= self.max_rpd:
                logger.error(
                    f"Daily rate limit reached ({self.max_rpd} RPD). "
                    "No more API calls today. Using local fallback."
                )
                raise RateLimitExceeded("Daily rate limit exceeded")
            
            # Clean expired entries from minute window
            now = time.monotonic()
            while self._minute_window and (now - self._minute_window[0]) > 60.0:
                self._minute_window.popleft()
            
            # Check per-minute limit
            if len(self._minute_window) >= self.max_rpm:
                wait_time = 60.0 - (now - self._minute_window[0]) + 0.1
                if wait_time > 0:
                    logger.warning(f"Rate limit: need to wait {wait_time:.1f}s (RPM={self.max_rpm})")
                    return wait_time
            
            return 0.0
    
    def wait_if_needed(self) -> float:
        """
        Blocking wait — for sync callers (desktop mode).
        
        Returns:
            Number of seconds waited (0.0 if no wait needed)
        """
        wait_time = self.check_rate_limit()
        if wait_time > 0:
            time.sleep(wait_time)
        return wait_time
    
    async def wait_if_needed_async(self) -> float:
        """
        Async wait — for FastAPI handlers.
        Uses asyncio.sleep instead of time.sleep to avoid blocking the event loop.
        
        Returns:
            Number of seconds waited (0.0 if no wait needed)
        """
        wait_time = self.check_rate_limit()
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        return wait_time
    
    def record_request(self):
        """Record that an API request was made."""
        with self._lock:
            self._minute_window.append(time.monotonic())
            self._daily_count += 1
            
            remaining_rpm = self.max_rpm - len(self._minute_window)
            remaining_rpd = self.max_rpd - self._daily_count
            
            if remaining_rpd <= 100:
                logger.warning(f"Daily API budget low: {remaining_rpd} requests remaining")
            elif remaining_rpm <= 3:
                logger.info(f"RPM budget low: {remaining_rpm} remaining in this minute")
    
    @property
    def daily_remaining(self) -> int:
        """Number of API requests remaining today."""
        with self._lock:
            today = date.today()
            if today != self._daily_date:
                return self.max_rpd
            return max(0, self.max_rpd - self._daily_count)
    
    @property
    def can_make_request(self) -> bool:
        """Check if a request can be made without waiting."""
        try:
            wait = self.check_rate_limit()
            return wait == 0.0
        except RateLimitExceeded:
            return False


class RateLimitExceeded(Exception):
    """Raised when daily rate limit is exhausted."""
    pass
