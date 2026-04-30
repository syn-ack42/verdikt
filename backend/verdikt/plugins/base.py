from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import ClassVar

from verdikt.core.models import Domain, MaterialItem


class PluginBase(ABC):
    """Base class for all Verdikt content source plugins.

    Plugins fetch raw material and normalise it into MaterialItems.
    They know nothing about preference learning — fetch, parse, emit.

    Register via pyproject.toml entry_points:
        [project.entry_points."verdikt.plugins"]
        myplugin = "my_package.plugin:MyPlugin"
    """

    plugin_name: str  # must be declared by each subclass
    supported_domains: ClassVar[frozenset[Domain]] = frozenset(Domain)  # all domains by default

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

    def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
        """Return {work_id: last_modified} for the given work IDs without fetching full content.

        The default returns {} — plugins that can do lightweight date checks override this
        to make update-plugin skip unchanged works without a full re-download.
        """
        return {}

    def estimate_count(self) -> int | None:
        """Return an approximate item count before fetching, or None if unknown.

        Used to show a progress total in the UI. May overestimate (e.g. max_works
        for AO3). Does not need to be exact.
        """
        return None

    @classmethod
    def help_markdown(cls) -> str:
        """Return user-facing help text for this plugin as a Markdown string.

        Displayed in the UI under Help › Plugins. Override to provide content;
        the default returns an empty string (no help section shown).
        """
        return ""

    def get_new_work_ids(self, existing: set[str]) -> list[str]:
        """Return work IDs that should be ingested but are not yet in existing.

        Called during update to discover new content in source-configured collections
        (e.g. a whole-folder selection where new files may have appeared).
        Default returns [] — override when the plugin can cheaply enumerate new items.
        """
        return []

    def fetch_by_ids(self, project_id: str, work_ids: list[str], **kwargs) -> Iterator[MaterialItem]:
        """Fetch only the works with the given IDs (plugin-native identity keys).

        Default falls back to fetch() and filters — override for efficiency.
        kwargs allows plugin-specific hints (e.g. date_hints) without changing the base signature.
        """
        ids = set(work_ids)
        for item in self.fetch(project_id):
            if item.plugin_metadata.get("work_id") in ids:
                yield item
