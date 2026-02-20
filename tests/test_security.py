"""Security tests — path traversal, CORS, request IDs, no info leaks.

Covers:
- Path traversal attacks in all file-serving endpoints
- CORS configuration (no credentials with wildcard)
- Request ID middleware
- No absolute paths in API responses
- Snapshot name sanitization
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestPathTraversal:
    """Verify path traversal protection on all file-access endpoints."""

    traversal_payloads = [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    ]

    def test_load_segs_rejects_traversal(self):
        """Direct unit test of _load_segs with traversal job_id."""
        from fastapi import HTTPException
        from src.api.routes import _load_segs

        for payload in self.traversal_payloads:
            with pytest.raises(HTTPException) as exc_info:
                _load_segs(payload)
            assert exc_info.value.status_code in (400, 404)

    def test_delete_file_traversal(self, client, _patch_dirs, storage_root):
        """DELETE /api/files/{filename} rejects traversal."""
        # Create a file outside uploads to ensure it's not deleted
        secret = storage_root / "secret.txt"
        secret.write_text("sensitive")

        r = client.delete("/api/files/../secret.txt")
        assert r.status_code in (400, 404)
        assert secret.exists(), "File outside uploads must not be deleted"

    def test_download_traversal_in_job_id(self, client, _patch_dirs):
        """GET /api/jobs/{job_id}/files rejects traversal in job_id."""
        r = client.get("/api/jobs/../../etc/files")
        assert r.status_code in (400, 404)

    def test_download_traversal_in_filename(self, client, seed_job):
        """GET /api/jobs/{job_id}/download/{filename} rejects traversal."""
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/download/../../../etc/passwd")
        assert r.status_code in (400, 404)

    def test_content_traversal(self, client, seed_job):
        """GET /api/jobs/{job_id}/content/{filename} rejects traversal."""
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/content/../../../etc/passwd")
        assert r.status_code in (400, 404)

    def test_snapshot_name_sanitized(self, client, seed_job):
        """POST /api/jobs/{job_id}/snapshot sanitizes name (no ../)."""
        job_id, job_dir = seed_job
        r = client.post(f"/api/jobs/{job_id}/snapshot",
                        params={"name": "../../malicious"})
        assert r.status_code == 200
        # Verify no directory escaping occurred
        snap_dir = job_dir / "snapshots"
        if snap_dir.exists():
            for f in snap_dir.iterdir():
                assert ".." not in f.name


class TestCORS:
    """Verify CORS is configured securely."""

    def test_cors_no_credentials_with_wildcard(self):
        """Wildcard origin + allow_credentials=True is insecure."""
        from main import app
        cors_mw = None
        for m in app.user_middleware:
            if "CORSMiddleware" in str(m):
                cors_mw = m
                break
        assert cors_mw is not None, "CORSMiddleware must be configured"
        assert cors_mw.kwargs.get("allow_credentials") is False

    def test_cors_headers_in_response(self, client, _patch_dirs):
        """OPTIONS request returns proper CORS headers."""
        r = client.options("/api/health",
                           headers={"Origin": "http://example.com",
                                    "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" in r.headers


class TestRequestIdMiddleware:
    """Verify request ID assignment and propagation."""

    def test_request_id_generated(self, client, _patch_dirs):
        """Response includes x-request-id header."""
        r = client.get("/api/health")
        assert "x-request-id" in r.headers
        assert len(r.headers["x-request-id"]) > 0

    def test_request_id_passthrough(self, client, _patch_dirs):
        """Client-provided x-request-id is echoed back."""
        custom_id = "test-req-123"
        r = client.get("/api/health", headers={"x-request-id": custom_id})
        assert r.headers["x-request-id"] == custom_id


class TestNoAbsolutePathLeaks:
    """Verify API responses don't leak server-side absolute paths."""

    def test_upload_response_no_abs_path(self, client, _patch_dirs):
        import io
        r = client.post("/api/upload",
                        files={"file": ("test.wav", io.BytesIO(b"RIFF" + b"\x00" * 50), "audio/wav")})
        assert r.status_code == 200
        body = json.dumps(r.json())
        # No server-side absolute paths should appear in API responses
        assert not any(body.count(prefix) for prefix in ["/home/", "/root/", "/var/", "/opt/"])

    def test_job_files_response_no_abs_path(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/files")
        body = json.dumps(r.json())
        assert "/home/" not in body

    def test_stats_response_no_abs_path(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/stats")
        body = json.dumps(r.json())
        assert "/home/" not in body
