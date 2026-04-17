from abc import ABC, abstractmethod
from collections.abc import Iterator

from verdikt.core.models import MaterialItem


class PluginBase(ABC):
    """Base class for all Verdikt content source plugins.

    Plugins fetch raw material and normalise it into MaterialItems.
    They know nothing about preference learning — fetch, parse, emit.

    Register via pyproject.toml entry_points:
        [project.entry_points."verdikt.plugins"]
        myplugin = "my_package.plugin:MyPlugin"
    """

    plugin_name: str  # must be declared by each subclass

    @classmethod
    @abstractmethod
    def config_schema(cls) -> dict:
        """JSON Schema describing this plugin's configuration.
        The UI renders config forms automatically from this schema.
        """

    @abstractmethod
    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        """Yield MaterialItems from the content source.
        Implementations must respect rate limits, robots.txt, and ToS.
        """
