"""
Dependency injection container for clean architecture and testability.
Provides service registration, resolution, and lifecycle management.
"""

from typing import Dict, Type, TypeVar, Callable, Any, Optional, Protocol
from abc import ABC, abstractmethod
from enum import Enum
import threading
import logging
from pathlib import Path


T = TypeVar('T')


class ServiceLifetime(Enum):
    """Service lifetime management options."""
    TRANSIENT = "transient"  # New instance every time
    SINGLETON = "singleton"  # Single instance for the application
    SCOPED = "scoped"       # Single instance per scope (not implemented yet)


class IServiceProvider(Protocol):
    """Protocol for service provider implementations."""
    
    def get_service(self, service_type: Type[T]) -> T:
        """Get service instance by type."""
        ...
    
    def get_required_service(self, service_type: Type[T]) -> T:
        """Get required service instance, throws if not found."""
        ...


class ServiceDescriptor:
    """Describes how to create and manage a service."""
    
    def __init__(
        self,
        service_type: Type,
        implementation_type: Optional[Type] = None,
        factory: Optional[Callable[..., Any]] = None,
        instance: Optional[Any] = None,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ):
        self.service_type = service_type
        self.implementation_type = implementation_type
        self.factory = factory
        self.instance = instance
        self.lifetime = lifetime
        
        # Validation
        if not any([implementation_type, factory, instance]):
            raise ValueError("Must provide implementation_type, factory, or instance")


class DependencyInjectionContainer:
    """
    Dependency injection container with support for different service lifetimes.
    Thread-safe singleton implementation.
    """
    
    _instance: Optional['DependencyInjectionContainer'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'DependencyInjectionContainer':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._services: Dict[Type, ServiceDescriptor] = {}
            self._singletons: Dict[Type, Any] = {}
            self._lock = threading.RLock()
            self._logger = logging.getLogger(__name__)
            self._initialized = True
    
    def register_transient(
        self,
        service_type: Type[T],
        implementation_type: Type[T]
    ) -> 'DependencyInjectionContainer':
        """Register a transient service (new instance each time)."""
        return self.register(
            service_type,
            ServiceDescriptor(service_type, implementation_type, lifetime=ServiceLifetime.TRANSIENT)
        )
    
    def register_singleton(
        self,
        service_type: Type[T],
        implementation_type: Type[T]
    ) -> 'DependencyInjectionContainer':
        """Register a singleton service (single instance)."""
        return self.register(
            service_type,
            ServiceDescriptor(service_type, implementation_type, lifetime=ServiceLifetime.SINGLETON)
        )
    
    def register_instance(
        self,
        service_type: Type[T],
        instance: T
    ) -> 'DependencyInjectionContainer':
        """Register a specific instance as a singleton."""
        return self.register(
            service_type,
            ServiceDescriptor(service_type, instance=instance, lifetime=ServiceLifetime.SINGLETON)
        )
    
    def register_factory(
        self,
        service_type: Type[T],
        factory: Callable[[], T],
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ) -> 'DependencyInjectionContainer':
        """Register a factory function for creating service instances."""
        return self.register(
            service_type,
            ServiceDescriptor(service_type, factory=factory, lifetime=lifetime)
        )
    
    def register(
        self,
        service_type: Type[T],
        descriptor: ServiceDescriptor
    ) -> 'DependencyInjectionContainer':
        """Register a service with a custom descriptor."""
        with self._lock:
            self._services[service_type] = descriptor
            self._logger.debug(f"Registered service: {service_type.__name__}")
            return self
    
    def get_service(self, service_type: Type[T]) -> Optional[T]:
        """Get service instance by type, returns None if not found."""
        with self._lock:
            try:
                return self._resolve_service(service_type)
            except Exception as e:
                self._logger.error(f"Failed to resolve service {service_type.__name__}: {e}")
                return None
    
    def get_required_service(self, service_type: Type[T]) -> T:
        """Get required service instance, throws if not found."""
        with self._lock:
            service = self._resolve_service(service_type)
            if service is None:
                raise ValueError(f"Required service not registered: {service_type.__name__}")
            return service
    
    def is_registered(self, service_type: Type) -> bool:
        """Check if a service type is registered."""
        with self._lock:
            return service_type in self._services
    
    def clear(self) -> None:
        """Clear all registered services."""
        with self._lock:
            self._services.clear()
            self._singletons.clear()
            self._logger.debug("Cleared all registered services")
    
    def _resolve_service(self, service_type: Type[T]) -> T:
        """Internal service resolution logic."""
        descriptor = self._services.get(service_type)
        if not descriptor:
            raise ValueError(f"Service not registered: {service_type.__name__}")
        
        # Handle singleton lifetime
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if service_type in self._singletons:
                return self._singletons[service_type]
            
            instance = self._create_instance(descriptor)
            self._singletons[service_type] = instance
            return instance
        
        # Handle transient lifetime
        return self._create_instance(descriptor)
    
    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """Create a service instance from descriptor."""
        # Use existing instance
        if descriptor.instance is not None:
            return descriptor.instance
        
        # Use factory
        if descriptor.factory is not None:
            return self._invoke_factory(descriptor.factory)
        
        # Use implementation type
        if descriptor.implementation_type is not None:
            return self._create_from_type(descriptor.implementation_type)
        
        raise ValueError("No way to create service instance")
    
    def _invoke_factory(self, factory: Callable) -> Any:
        """Invoke factory with dependency injection."""
        import inspect
        
        signature = inspect.signature(factory)
        kwargs = {}
        
        for param_name, param in signature.parameters.items():
            if param.annotation != inspect.Parameter.empty:
                dependency = self.get_service(param.annotation)
                if dependency is not None:
                    kwargs[param_name] = dependency
                elif param.default == inspect.Parameter.empty:
                    # Required parameter without default value
                    raise ValueError(f"Cannot resolve dependency: {param.annotation}")
        
        return factory(**kwargs)
    
    def _create_from_type(self, implementation_type: Type) -> Any:
        """Create instance from type with dependency injection."""
        import inspect
        
        constructor = implementation_type.__init__
        signature = inspect.signature(constructor)
        kwargs = {}
        
        # Skip 'self' parameter
        params = list(signature.parameters.values())[1:]
        
        for param in params:
            if param.annotation != inspect.Parameter.empty:
                dependency = self.get_service(param.annotation)
                if dependency is not None:
                    kwargs[param.name] = dependency
                elif param.default == inspect.Parameter.empty:
                    # Required parameter without default value
                    raise ValueError(f"Cannot resolve dependency: {param.annotation}")
        
        return implementation_type(**kwargs)


class ServiceFactory:
    """Factory for creating and configuring services."""
    
    @staticmethod
    def configure_services(container: DependencyInjectionContainer) -> None:
        """Configure all application services in the container."""
        from ..core.events import EventBus, get_event_bus
        from ..services.service_implementations import (
            AuthenticationService, SettingsService, TemplateService, DatabaseService
        )
        from ..core.interfaces import (
            IAuthenticationService, ISettingsService, ITemplateService, IStorageService, IEventBus
        )
        
        # Register event bus as singleton
        event_bus = get_event_bus()
        container.register_instance(IEventBus, event_bus)
        container.register_instance(EventBus, event_bus)
        
        # Register settings service as singleton
        container.register_singleton(ISettingsService, SettingsService)
        
        # Register other services
        container.register_singleton(IStorageService, DatabaseService)
        container.register_singleton(ITemplateService, TemplateService)
        
        # Register authentication service with dependencies
        container.register_factory(
            IAuthenticationService,
            lambda settings=container.get_service(ISettingsService),
                   events=container.get_service(IEventBus):
            AuthenticationService(settings, events),
            ServiceLifetime.SINGLETON
        )


class ServiceLocator:
    """
    Service locator pattern implementation.
    Provides global access to the DI container.
    """
    
    _container: Optional[DependencyInjectionContainer] = None
    
    @classmethod
    def get_container(cls) -> DependencyInjectionContainer:
        """Get the global DI container."""
        if cls._container is None:
            cls._container = DependencyInjectionContainer()
            ServiceFactory.configure_services(cls._container)
        return cls._container
    
    @classmethod
    def get_service(cls, service_type: Type[T]) -> Optional[T]:
        """Convenience method to get service from global container."""
        return cls.get_container().get_service(service_type)
    
    @classmethod
    def get_required_service(cls, service_type: Type[T]) -> T:
        """Convenience method to get required service from global container."""
        return cls.get_container().get_required_service(service_type)
    
    @classmethod
    def reset(cls) -> None:
        """Reset the service locator (mainly for testing)."""
        if cls._container:
            cls._container.clear()
        cls._container = None


# Decorators for dependency injection

def inject(service_type: Type[T]):
    """Decorator to inject services into class methods."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            service = ServiceLocator.get_service(service_type)
            if service is None:
                raise ValueError(f"Service not available: {service_type.__name__}")
            return func(*args, service=service, **kwargs)
        return wrapper
    return decorator


def autowired(cls):
    """Class decorator to enable automatic dependency injection."""
    original_init = cls.__init__
    
    def new_init(self, *args, **kwargs):
        # Get the container
        container = ServiceLocator.get_container()
        
        # Inject dependencies
        import inspect
        signature = inspect.signature(original_init)
        
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
                
            if param.annotation != inspect.Parameter.empty and param_name not in kwargs:
                service = container.get_service(param.annotation)
                if service is not None:
                    kwargs[param_name] = service
        
        original_init(self, *args, **kwargs)
    
    cls.__init__ = new_init
    return cls


# Context manager for service scopes (future enhancement)

class ServiceScope:
    """Context manager for scoped services."""
    
    def __init__(self, container: DependencyInjectionContainer):
        self.container = container
        self.scoped_services: Dict[Type, Any] = {}
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Cleanup scoped services if they implement IDisposable
        for service in self.scoped_services.values():
            if hasattr(service, 'dispose'):
                try:
                    service.dispose()
                except Exception as e:
                    logging.getLogger(__name__).error(f"Error disposing service: {e}")
        
        self.scoped_services.clear()


# Service health checks

class IHealthCheck(Protocol):
    """Protocol for service health checks."""
    
    def check_health(self) -> Dict[str, Any]:
        """Check service health and return status."""
        ...


class HealthCheckService:
    """Service for monitoring the health of registered services."""
    
    def __init__(self, container: DependencyInjectionContainer):
        self.container = container
        self.logger = logging.getLogger(__name__)
    
    def check_all_services(self) -> Dict[str, Dict[str, Any]]:
        """Check health of all registered services that implement IHealthCheck."""
        results = {}
        
        for service_type, descriptor in self.container._services.items():
            try:
                service = self.container.get_service(service_type)
                if service and isinstance(service, IHealthCheck):
                    results[service_type.__name__] = service.check_health()
            except Exception as e:
                results[service_type.__name__] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return results