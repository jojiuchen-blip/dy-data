"""Bind one unfiltered backend export request to its completed task and bytes.

Task status/type are export protocol fields observed in the real endpoint,
not mappings for account type or certification status.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apps.worker.account_qualification import digest

EXPORT_START_PATH = "/life/gate/v3/collaborator/download_bc/start/"
EXPORT_TASK_TYPE = 120
EXPORT_CONTRACT = "backend-download-bc-empty-request-v1"


def protocol_code(value, expected):
    return type(value) in (int, str) and str(value) == str(expected)


class ExportedWorkbook(type(Path())):
    """A local Path carrying the exact task proof that produced its bytes."""

    def __new__(cls, path, *, export_proof):
        result = super().__new__(cls, path)
        result.export_proof = export_proof
        return result


class BackendExportTask:
    def __init__(self):
        self.start = None
        self.completed = None
        self.error_code = None

    def observe_start(self, *, method, url, request_json, response):
        parsed = urlparse(url)
        if parsed.path != EXPORT_START_PATH:
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        data = response.get("data") if isinstance(response, dict) else None
        if (method != "POST" or request_json != {} or set(query) - {"root_life_account_id"}
                or any(len(values) != 1 for values in query.values())
                or not isinstance(data, dict) or not protocol_code(response.get("status_code"), 0)
                or not protocol_code(data.get("status"), 1) or not isinstance(data.get("download_id"), str)
                or not data["download_id"].strip()):
            self.error_code = "unverified_export_request_contract"
            return
        if self.start is not None and self.start["download_id"] != data["download_id"]:
            self.error_code = "multiple_export_start_tasks"
            return
        self.start = {"contract": EXPORT_CONTRACT, "method": "POST", "start_path": EXPORT_START_PATH,
                      "request_json": {}, "context_query_keys": sorted(query),
                      "context_query_sha256": digest(query), "download_id": data["download_id"],
                      "start_status": data["status"], "response_status_code": response["status_code"]}

    def observe_poll(self, payload):
        if self.start is None or self.error_code is not None:
            return
        data = payload.get("data") if isinstance(payload, dict) else None
        infos = data.get("download_infos") if isinstance(data, dict) else None
        if not isinstance(infos, list):
            return
        mine = [item for item in infos if isinstance(item, dict)
                and item.get("download_id") == self.start["download_id"]]
        if len(mine) > 1:
            self.error_code = "duplicate_export_task_metadata"
            return
        if not mine or not protocol_code(mine[0].get("status"), 2):
            return
        item = mine[0]
        start, end = item.get("generate_start_time"), item.get("generate_complete_time")
        if (not protocol_code(item.get("download_type"), EXPORT_TASK_TYPE)
                or not isinstance(start, int) or isinstance(start, bool) or start <= 0
                or not isinstance(end, int) or isinstance(end, bool) or end < start
                or not isinstance(item.get("file_url"), str) or not item["file_url"].strip()
                or not isinstance(item.get("file_name"), str) or not item["file_name"].strip()):
            self.error_code = "invalid_completed_export_task_metadata"
            return
        metadata = {key: item[key] for key in ("download_id", "download_type", "status", "file_name",
                                               "generate_start_time", "generate_complete_time")}
        if self.completed is not None and self.completed["metadata"] != metadata:
            self.error_code = "conflicting_completed_export_task_metadata"
            return
        # The signed URL stays only in memory for this task's actual download.
        self.completed = {"file_url": item["file_url"], "metadata": metadata}

    def file_info(self):
        if self.error_code is not None or self.completed is None:
            return None
        return {"file_url": self.completed["file_url"], "file_name": self.completed["metadata"]["file_name"]}

    def bind_file(self, path):
        path = Path(path)
        if self.error_code is not None or self.start is None or self.completed is None:
            raise ValueError(self.error_code or "export_task_not_complete")
        if path.name != Path(self.completed["metadata"]["file_name"]).name:
            raise ValueError("export_task_file_name_mismatch")
        body = path.read_bytes()
        if not body:
            raise ValueError("export_task_file_empty")
        proof = {**self.start, "completed_task": dict(self.completed["metadata"]),
                 "file_bytes": len(body), "workbook_sha256": hashlib.sha256(body).hexdigest()}
        return ExportedWorkbook(path, export_proof=proof)


def apply_export_task_proof(records, workbook):
    proof = getattr(workbook, "export_proof", None)
    if not isinstance(proof, dict):
        records.proof["complete"] = False
        records.proof["corroboration_error"] = "exact_export_task_proof_missing"
        return records
    metadata = proof.get("completed_task") or {}
    start, end = metadata.get("generate_start_time"), metadata.get("generate_complete_time")
    valid = (proof.get("contract") == EXPORT_CONTRACT and proof.get("method") == "POST"
             and proof.get("start_path") == EXPORT_START_PATH and proof.get("request_json") == {}
             and protocol_code(proof.get("start_status"), 1) and protocol_code(proof.get("response_status_code"), 0)
             and not (set(proof.get("context_query_keys") or []) - {"root_life_account_id"})
             and proof.get("download_id") == metadata.get("download_id")
             and protocol_code(metadata.get("download_type"), EXPORT_TASK_TYPE)
             and protocol_code(metadata.get("status"), 2)
             and type(start) is int and type(end) is int and start > 0 and end >= start
             and Path(workbook).name == Path(metadata.get("file_name") or "").name
             and proof.get("workbook_sha256") == records.proof.get("workbook_sha256")
             and proof.get("file_bytes") == Path(workbook).stat().st_size)
    records.proof.update({"export_task": proof,
                          "complete": bool(valid and records.proof.get("file_complete")),
                          "scope": "unfiltered_download_bc_empty_request"})
    return records
