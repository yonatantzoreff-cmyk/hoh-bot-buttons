"""
In-memory pub/sub for SSE event broadcasting.
Designed to be easily replaced with Redis or Postgres LISTEN/NOTIFY in the future.
"""
import asyncio
import logging
from typing import Any, Dict, List, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

# Maximum number of messages to buffer per subscriber
# This prevents memory issues if a slow client falls behind
# Messages beyond this limit will be dropped with a warning
SSE_QUEUE_SIZE = 100


class InMemoryPubSub:
    """Simple in-memory pub/sub for broadcasting events within a single process."""
    
    def __init__(self):
        self._subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
    
    async def subscribe(self, channel: str) -> asyncio.Queue:
        """Subscribe to a channel and return a queue for receiving messages."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)
        async with self._lock:
            self._subscribers[channel].add(queue)
        logger.debug(f"Subscriber added to channel '{channel}'. Total: {len(self._subscribers[channel])}")
        return queue
    
    async def unsubscribe(self, channel: str, queue: asyncio.Queue):
        """Unsubscribe from a channel."""
        async with self._lock:
            self._subscribers[channel].discard(queue)
        logger.debug(f"Subscriber removed from channel '{channel}'. Remaining: {len(self._subscribers[channel])}")
    
    async def publish(self, channel: str, message: Dict[str, Any]):
        """Publish a message to all subscribers of a channel."""
        async with self._lock:
            subscribers = list(self._subscribers[channel])
        
        if not subscribers:
            logger.debug(f"No subscribers for channel '{channel}'")
            return
        
        logger.info(f"Publishing to channel '{channel}' with {len(subscribers)} subscribers")
        
        for queue in subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(f"Queue full for subscriber on channel '{channel}', dropping message")
            except Exception as e:
                logger.error(f"Error publishing to subscriber: {e}")


# Global singleton instance
_pubsub_instance = None


def get_pubsub() -> InMemoryPubSub:
    """Get the global pub/sub instance."""
    global _pubsub_instance
    if _pubsub_instance is None:
        _pubsub_instance = InMemoryPubSub()
    return _pubsub_instance
