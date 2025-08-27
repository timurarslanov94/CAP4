from dishka import Provider, Scope, provide

from src.repositories.call_repository import CallRepository


class RepositoryProvider(Provider):
    scope = Scope.APP
    
    @provide
    def provide_call_repository(self) -> CallRepository:
        return CallRepository()