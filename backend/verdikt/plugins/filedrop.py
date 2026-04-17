from collections.abc import Iterator
from pathlib import Path

from verdikt.core.models import MaterialItem
from verdikt.plugins.base import PluginBase


class FileDropPlugin(PluginBase):
    """Ingests local files from a directory.

    Supported formats: .txt, .epub, .pdf, .html, .htm, .md
    """

    plugin_name = "filedrop"

    SUPPORTED_EXTENSIONS = {".txt", ".epub", ".pdf", ".html", ".htm", ".md"}

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to directory containing source files",
                },
            },
            "required": ["path"],
        }

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        raise NotImplementedError
