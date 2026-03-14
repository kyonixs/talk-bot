import logging
import os
import threading
import urllib.error
import urllib.request
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

_cached_project_id = None
_cached_client = None
_cache_lock = threading.Lock()

def _get_project_id() -> str:
    """
    GCPプロジェクトIDを取得する。優先順位:
    1. 環境変数 GOOGLE_CLOUD_PROJECT（ローカル開発用）
    2. GCP VM メタデータサーバー（本番環境で自動検出）
    """
    global _cached_project_id
    if _cached_project_id:
        return _cached_project_id

    # 1. 環境変数から
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        _cached_project_id = project_id
        return project_id

    # 2. GCP メタデータサーバーから自動取得
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                _cached_project_id = resp.read().decode("utf-8")
                return _cached_project_id
    except (OSError, urllib.error.URLError):
        logger.debug("GCP metadata server not reachable (expected if not on GCP VM)")

    raise ValueError(
        "GCP Project ID could not be determined. "
        "Set GOOGLE_CLOUD_PROJECT env var or run on a GCP VM."
    )


def get_secret(secret_id: str) -> str:
    """
    GCP Secret Manager からシークレットの値を取得する。
    プロジェクトIDは自動検出される。
    """
    global _cached_client
    project_id = _get_project_id()
    with _cache_lock:
        if _cached_client is None:
            _cached_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"

    response = _cached_client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
