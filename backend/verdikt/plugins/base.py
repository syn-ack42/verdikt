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

    @classmethod
    def supports_remote_content(cls) -> bool:
        """True if this plugin stores only references at ingest and fetches bytes on demand.

        When True, MaterialItems may be ingested with content=b"" and content_is_remote=True.
        The plugin must implement fetch_content().
        """
        return False

    def fetch_content(self, source_path: str) -> bytes:
        """Fetch the raw bytes for a remote item on demand.

        Called during the pipeline chunk phase (or on every display access for "none"
        storage mode). Only required when supports_remote_content() returns True.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not implement fetch_content()")

    @classmethod
    def plugin_actions(cls) -> list[dict]:
        """Declare user-triggerable actions this plugin supports.

        Each action is a dict with keys:
          name          — machine identifier (used in the API URL)
          title         — button label shown in the UI
          description   — one-line explanation shown below the button
          options_schema — JSON Schema object describing the action's options form
        Returns [] by default (no actions).
        """
        return []

    def run_action(self, action_name: str, project_id: str, session: object, options: dict) -> dict:
        """Execute a named action declared by plugin_actions().

        Returns a result dict (shape is action-specific; writeback returns
        {"updated": int, "skipped": int, "errors": list[str]}).
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not implement run_action()")

    @classmethod
    def supports_batched_ingest(cls) -> bool:
        """True if this plugin implements the batched ingest protocol.

        Batched ingest fetches content in small pages, runs the pipeline after each page,
        and persists state so runs can be resumed, stopped, or reset.
        """
        return False

    def ingest_batch(self, project_id: str, state: dict | None) -> tuple[list[MaterialItem], dict | None]:
        """Fetch one batch of MaterialItems.

        state: opaque dict returned by the previous call (None = fresh start).
        Returns (items, next_state). next_state is None when all content has been fetched.
        The router persists next_state between requests; its shape is entirely plugin-defined.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not implement ingest_batch()")
