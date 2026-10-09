# Milestone 2: integration with the existing application

Inspected the existing models, FastAPI route factory, session/CSRF dependencies, schemas, migration, tests, Next.js workspace and Docker Compose before implementation.

- Existing business tables share tenant IDs and composite foreign keys. Keep existing CRUD contracts and reuse their input schemas and link validation when confirming a document.
- Authentication uses a database session cookie and CSRF header. Document APIs use the same dependencies, including organization switching.
- `Document` existed but had no routes or storage implementation. Extend it; retain existing business entities and audit events.
- The frontend is one App Router workspace with sidebar screen navigation. Add document routes that render the same shell and a dedicated document component.
- Native PDF parsing and OCR are backend services. OCR runs only in RQ worker processes. Upload inspection and page previews run in bounded child processes, not the HTTP event loop.
- Private storage is outside Next public files. Original downloads and raster page previews require authentication and tenant ownership. Previewing raster pages avoids executing embedded PDF actions.
- Each extraction is immutable evidence with per-field/page/box provenance. Draft corrections use optimistic revision checks and an append-only correction history. Re-extraction retains drafts. Confirmation creates a new business record transactionally and never updates unrelated manual records.
- Redis jobs use deterministic IDs and database state transitions. Stale jobs become retryable failures; late workers cannot overwrite a newer extraction. No PO/invoice matching is performed.
