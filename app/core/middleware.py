import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("openpartsflow.middleware")


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "[%s] %s %s -> %s (%.2fms)",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "[%s] Unhandled error on %s %s (%.2fms): %s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                exc,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "request_id": request_id,
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response
