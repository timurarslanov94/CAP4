from dishka import Provider, Scope, provide

from src.core.config import Settings, get_settings


class ConfigProvider(Provider):
    scope = Scope.APP
    
    @provide
    def provide_settings(self) -> Settings:
        return get_settings()