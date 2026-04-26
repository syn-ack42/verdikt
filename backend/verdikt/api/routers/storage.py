from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import Form
from fastapi.responses import Response

from verdikt.api.deps import get_storage
from verdikt.storage.files import StorageBackend, StorageEntry

router = APIRouter(prefix="/api/storage", tags=["storage"])


def _entry_dict(e: StorageEntry) -> dict:
    return {
        "name": e.name,
        "path": e.path,
        "is_dir": e.is_dir,
        "size": e.size,
        "modified_at": e.modified_at.isoformat(),
    }


@router.get("")
def list_directory(
    path: str = "/",
    backend: StorageBackend = Depends(get_storage),
) -> dict:
    entries = backend.list(path)
    return {"path": path, "entries": [_entry_dict(e) for e in entries]}


@router.post("/upload", status_code=201)
async def upload_files(
    files: list[UploadFile],
    path: str = Form(default="/"),
    backend: StorageBackend = Depends(get_storage),
) -> dict:
    if not files:
        raise HTTPException(status_code=422, detail="No files provided")
    uploaded: list[str] = []
    for file in files:
        if not file.filename:
            continue
        safe_name = file.filename.replace("\\", "/").split("/")[-1]
        if not safe_name or safe_name in {".", ".."}:
            continue
        target = path.rstrip("/") + "/" + safe_name
        data = await file.read()
        backend.write(target, data)
        uploaded.append(safe_name)
    return {"uploaded": uploaded, "path": path}


@router.post("/mkdir", status_code=201)
def create_directory(
    path: str,
    backend: StorageBackend = Depends(get_storage),
) -> dict:
    backend.mkdir(path)
    return {"path": path}


@router.get("/download")
def download_file(
    path: str,
    backend: StorageBackend = Depends(get_storage),
) -> Response:
    if not backend.exists(path) or backend.is_dir(path):
        raise HTTPException(status_code=404, detail="File not found")
    data = backend.read(path)
    filename = path.split("/")[-1]
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("", status_code=204)
def delete_entry(
    path: str,
    backend: StorageBackend = Depends(get_storage),
) -> None:
    if not backend.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
    try:
        backend.delete(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
