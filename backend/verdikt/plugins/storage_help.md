# File Drop

Ingest files from your personal Verdikt storage area. Files you upload here are encrypted at rest and only accessible to you.

## Adding files

There are two ways to add files to your storage:

**Upload via the UI** — on any project dashboard, click **Browse & Ingest Files**, then **Upload files**. You can upload multiple files at once.

**Drop files directly** — copy files into your user storage directory. On the server the path is `$VERDIKT_USERS_DIR/<your-user-id>/files/`. Files and folders you create there appear immediately in the browser.

## Selecting what to ingest

The browser shows your full file tree. For each project ingest you choose:

- **Individual files** — click a file to toggle selection
- **Whole folders** — click the folder toggle to include everything inside; new files added to the folder later are picked up automatically on the next ingest

Click **Ingest selected** when ready. Running the pipeline afterwards is required to chunk, embed, and cluster the new content before it can be rated.

## Supported formats

**Text projects:** `.txt`, `.md`, `.html`, `.epub`, `.pdf`, `.rtf`

**Image projects:** `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, `.tiff`

Files with unsupported extensions are silently skipped. Ingest is idempotent: files already in the project are only updated when their content changes.

## Updating content

If you replace a file with a newer version, run **Ingest** again. Verdikt detects the change via a content hash and re-processes only the modified file — chunks, embeddings, and ratings for unchanged files are left untouched.

The **Update** button on the project dashboard re-checks all folder selections for new and changed files without you having to re-open the ingest dialog.

## Privacy

Files are stored as opaque encrypted blobs on disk using AES-256-GCM. The encryption key is derived from your login password and is never stored on the server. A server administrator with filesystem access cannot read your file content or determine what files you have uploaded.
