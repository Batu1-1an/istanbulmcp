import pytest

from app.core.rate_limit import AsyncTokenBucket, SourceRateLimitExceeded


@pytest.mark.asyncio
async def test_token_bucket_raises_when_wait_exceeds_budget():
    bucket = AsyncTokenBucket(
        capacity=1,
        refill_per_second=0.1,
        max_wait_seconds=0.0,
    )

    await bucket.acquire("ckan")

    with pytest.raises(SourceRateLimitExceeded) as exc_info:
        await bucket.acquire("ckan")

    assert exc_info.value.source == "ckan"
    assert exc_info.value.retry_after_seconds > 0
