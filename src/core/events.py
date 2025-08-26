"""
Event system for decoupled communication between components.
Implements observer pattern with type-safe events and async support.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Set, Type, TypeVar, Generic
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
import weakref
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor


T = TypeVar('T')


class EventPriority(Enum):
    """Event priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class EventContext:
    """Context information for events."""
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class IEvent(ABC):
    """Base interface for all events."""
    
    @property
    @abstractmethod
    def event_type(self) -> str:
        """Unique identifier for this event type."""
        pass
    
    @property
    @abstractmethod
    def priority(self) -> EventPriority:
        """Priority level of this event."""
        pass
    
    @property
    @abstractmethod
    def context(self) -> EventContext:
        """Context information for this event."""
        pass


class BaseEvent(IEvent):
    """Base implementation for events."""
    
    def __init__(self, context: EventContext, priority: EventPriority = EventPriority.NORMAL):
        self._context = context
        self._priority = priority
    
    @property
    def event_type(self) -> str:
        return self.__class__.__name__
    
    @property
    def priority(self) -> EventPriority:
        return self._priority
    
    @property
    def context(self) -> EventContext:
        return self._context


# Application Events

class ApplicationStartedEvent(BaseEvent):
    """Fired when the application starts."""
    pass


class ApplicationShutdownEvent(BaseEvent):
    """Fired when the application is shutting down."""
    pass


class UserLoginEvent(BaseEvent):
    """Fired when a user logs in."""
    
    def __init__(self, username: str, context: EventContext):
        super().__init__(context)
        self.username = username


class UserLogoutEvent(BaseEvent):
    """Fired when a user logs out."""
    
    def __init__(self, username: str, context: EventContext):
        super().__init__(context)
        self.username = username


# Gallery Events

class GalleryAddedEvent(BaseEvent):
    """Fired when a gallery is added to the queue."""
    
    def __init__(self, gallery_id: str, gallery_name: str, folder_path: str, context: EventContext):
        super().__init__(context)
        self.gallery_id = gallery_id
        self.gallery_name = gallery_name
        self.folder_path = folder_path


class GalleryRemovedEvent(BaseEvent):
    """Fired when a gallery is removed from the queue."""
    
    def __init__(self, gallery_id: str, context: EventContext):
        super().__init__(context)
        self.gallery_id = gallery_id


class GalleryUploadStartedEvent(BaseEvent):
    """Fired when gallery upload begins."""
    
    def __init__(self, gallery_id: str, total_images: int, context: EventContext):
        super().__init__(context, EventPriority.HIGH)
        self.gallery_id = gallery_id
        self.total_images = total_images


class GalleryUploadProgressEvent(BaseEvent):
    """Fired during gallery upload progress."""
    
    def __init__(self, gallery_id: str, completed: int, total: int, current_image: str, context: EventContext):
        super().__init__(context)
        self.gallery_id = gallery_id
        self.completed = completed
        self.total = total
        self.current_image = current_image
        self.progress_percent = (completed / total * 100) if total > 0 else 0


class GalleryUploadCompletedEvent(BaseEvent):
    """Fired when gallery upload completes successfully."""
    
    def __init__(self, gallery_id: str, gallery_url: str, total_images: int, duration: float, context: EventContext):
        super().__init__(context, EventPriority.HIGH)
        self.gallery_id = gallery_id
        self.gallery_url = gallery_url
        self.total_images = total_images
        self.duration = duration


class GalleryUploadFailedEvent(BaseEvent):
    """Fired when gallery upload fails."""
    
    def __init__(self, gallery_id: str, error: str, failed_image: Optional[str], context: EventContext):
        super().__init__(context, EventPriority.CRITICAL)
        self.gallery_id = gallery_id
        self.error = error
        self.failed_image = failed_image


# Settings Events

class SettingChangedEvent(BaseEvent):
    """Fired when a setting is changed."""
    
    def __init__(self, key: str, old_value: Any, new_value: Any, context: EventContext):
        super().__init__(context)
        self.key = key
        self.old_value = old_value
        self.new_value = new_value


class SettingsResetEvent(BaseEvent):
    """Fired when settings are reset to defaults."""
    
    def __init__(self, context: EventContext):
        super().__init__(context, EventPriority.HIGH)


# Template Events

class TemplateCreatedEvent(BaseEvent):
    """Fired when a template is created."""
    
    def __init__(self, template_name: str, context: EventContext):
        super().__init__(context)
        self.template_name = template_name


class TemplateUpdatedEvent(BaseEvent):
    """Fired when a template is updated."""
    
    def __init__(self, template_name: str, context: EventContext):
        super().__init__(context)
        self.template_name = template_name


class TemplateDeletedEvent(BaseEvent):
    """Fired when a template is deleted."""
    
    def __init__(self, template_name: str, context: EventContext):
        super().__init__(context)
        self.template_name = template_name


# Network Events

class NetworkErrorEvent(BaseEvent):
    """Fired when a network error occurs."""
    
    def __init__(self, error: str, url: Optional[str], context: EventContext):
        super().__init__(context, EventPriority.HIGH)
        self.error = error
        self.url = url


class ConnectionStatusChangedEvent(BaseEvent):
    """Fired when network connection status changes."""
    
    def __init__(self, is_connected: bool, context: EventContext):
        super().__init__(context, EventPriority.HIGH)
        self.is_connected = is_connected


# Error Events

class ErrorEvent(BaseEvent):
    """Fired when an error occurs."""
    
    def __init__(self, error: Exception, component: str, context: EventContext):
        super().__init__(context, EventPriority.CRITICAL)
        self.error = error
        self.component = component
        self.error_message = str(error)


# Event Handlers

EventHandler = Callable[[IEvent], None]
AsyncEventHandler = Callable[[IEvent], asyncio.Future[None]]


@dataclass
class Subscription:
    """Represents an event subscription."""
    id: str
    event_type: str
    handler: Callable
    is_async: bool
    priority: EventPriority
    weak_ref: bool = True


class EventBus:
    """
    Thread-safe event bus implementation with priority handling.
    Supports both synchronous and asynchronous event handlers.
    """
    
    def __init__(self, max_workers: int = 4):
        self._subscriptions: Dict[str, List[Subscription]] = {}
        self._lock = threading.RLock()
        self._next_id = 0
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._logger = logging.getLogger(__name__)
        
        # Weak references to automatically clean up dead handlers
        self._weak_handlers: Set[weakref.ref] = set()
    
    def subscribe(
        self,
        event_type: str,
        handler: Callable[[IEvent], None],
        priority: EventPriority = EventPriority.NORMAL,
        weak_ref: bool = True
    ) -> str:
        """Subscribe to events of a specific type."""
        with self._lock:
            subscription_id = f"sub_{self._next_id}"
            self._next_id += 1
            
            is_async = asyncio.iscoroutinefunction(handler)
            
            subscription = Subscription(
                id=subscription_id,
                event_type=event_type,
                handler=handler,
                is_async=is_async,
                priority=priority,
                weak_ref=weak_ref
            )
            
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            
            self._subscriptions[event_type].append(subscription)
            
            # Sort by priority (highest first)
            self._subscriptions[event_type].sort(
                key=lambda s: s.priority.value, reverse=True
            )
            
            self._logger.debug(f"Subscribed {subscription_id} to {event_type}")
            return subscription_id
    
    def subscribe_to_type(
        self,
        event_class: Type[IEvent],
        handler: Callable[[IEvent], None],
        priority: EventPriority = EventPriority.NORMAL,
        weak_ref: bool = True
    ) -> str:
        """Subscribe to events of a specific class type."""
        return self.subscribe(event_class.__name__, handler, priority, weak_ref)
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from events."""
        with self._lock:
            for event_type, subscriptions in self._subscriptions.items():
                for i, sub in enumerate(subscriptions):
                    if sub.id == subscription_id:
                        del subscriptions[i]
                        self._logger.debug(f"Unsubscribed {subscription_id}")
                        return True
            return False
    
    def publish(self, event: IEvent) -> None:
        """Publish an event to all subscribers."""
        event_type = event.event_type
        
        with self._lock:
            subscriptions = self._subscriptions.get(event_type, []).copy()
        
        if not subscriptions:
            return
        
        self._logger.debug(f"Publishing {event_type} to {len(subscriptions)} subscribers")
        
        # Handle subscriptions by priority
        for subscription in subscriptions:
            try:
                if subscription.is_async:
                    # Submit async handlers to thread pool
                    self._executor.submit(self._handle_async_event, subscription.handler, event)
                else:
                    # Execute sync handlers immediately
                    subscription.handler(event)
            except Exception as e:
                self._logger.error(f"Error in event handler {subscription.id}: {e}")
    
    def publish_async(self, event: IEvent) -> asyncio.Future[None]:
        """Publish an event asynchronously."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(self._executor, self.publish, event)
    
    def _handle_async_event(self, handler: AsyncEventHandler, event: IEvent) -> None:
        """Handle async event in a separate thread."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(handler(event))
        except Exception as e:
            self._logger.error(f"Error in async event handler: {e}")
        finally:
            loop.close()
    
    def get_subscription_count(self, event_type: str) -> int:
        """Get the number of subscriptions for an event type."""
        with self._lock:
            return len(self._subscriptions.get(event_type, []))
    
    def clear_subscriptions(self, event_type: Optional[str] = None) -> None:
        """Clear subscriptions for a specific event type or all."""
        with self._lock:
            if event_type:
                self._subscriptions.pop(event_type, None)
            else:
                self._subscriptions.clear()
    
    def shutdown(self) -> None:
        """Shutdown the event bus and cleanup resources."""
        self._executor.shutdown(wait=True)
        self.clear_subscriptions()


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def publish_event(event: IEvent) -> None:
    """Convenience function to publish events to the global bus."""
    get_event_bus().publish(event)


def subscribe_to_event(
    event_type: str,
    handler: EventHandler,
    priority: EventPriority = EventPriority.NORMAL
) -> str:
    """Convenience function to subscribe to events on the global bus."""
    return get_event_bus().subscribe(event_type, handler, priority)


# Event Decorators

def event_handler(
    event_type: str,
    priority: EventPriority = EventPriority.NORMAL,
    bus: Optional[EventBus] = None
):
    """Decorator to automatically register event handlers."""
    def decorator(func: EventHandler) -> EventHandler:
        event_bus = bus or get_event_bus()
        event_bus.subscribe(event_type, func, priority)
        return func
    return decorator


def on_event(event_class: Type[IEvent], priority: EventPriority = EventPriority.NORMAL):
    """Decorator to register handlers for specific event classes."""
    def decorator(func: EventHandler) -> EventHandler:
        get_event_bus().subscribe_to_type(event_class, func, priority)
        return func
    return decorator


# Event Middleware

class EventMiddleware(ABC):
    """Base class for event middleware."""
    
    @abstractmethod
    def process_event(self, event: IEvent, next_handler: Callable[[IEvent], None]) -> None:
        """Process event and call next handler in chain."""
        pass


class LoggingMiddleware(EventMiddleware):
    """Middleware for logging events."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    def process_event(self, event: IEvent, next_handler: Callable[[IEvent], None]) -> None:
        self.logger.info(f"Event: {event.event_type} from {event.context.source}")
        next_handler(event)


class MetricsMiddleware(EventMiddleware):
    """Middleware for collecting event metrics."""
    
    def __init__(self):
        self.event_counts: Dict[str, int] = {}
        self.total_events = 0
        self._lock = threading.Lock()
    
    def process_event(self, event: IEvent, next_handler: Callable[[IEvent], None]) -> None:
        with self._lock:
            self.total_events += 1
            event_type = event.event_type
            self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        
        next_handler(event)
    
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'total_events': self.total_events,
                'event_counts': self.event_counts.copy()
            }