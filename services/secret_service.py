import os
from google.cloud import secretmanager

def get_secret(secret_id, project_id=None):
    """
    GCP Secret Manager からシークレットの値を取得する。
    `project_id` が指定されていない場合は、環境変数 `GOOGLE_CLOUD_PROJECT` を使用する。
    """
    if not project_id:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        
    if not project_id:
        raise ValueError("GCP Project ID is not set. Please set GOOGLE_CLOUD_PROJECT environment variable.")

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
