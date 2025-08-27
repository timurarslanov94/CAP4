from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka

from src.infrastructure.di import (
    ConfigProvider,
    InfrastructureProvider,
    RepositoryProvider,
    ServiceProvider,
)


def create_container():
    container = make_async_container(
        ConfigProvider(),
        RepositoryProvider(),
        InfrastructureProvider(),
        ServiceProvider(),
    )
    return container


def setup_di(app):
    container = create_container()
    setup_dishka(container, app)