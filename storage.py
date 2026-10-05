from urllib.parse import quote

import boto3
from botocore.config import Config

from config import S3_ACCESS_KEY, S3_BUCKET, S3_ENDPOINT, S3_PUBLIC_ENDPOINT, S3_SECRET_KEY

_config = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)


def _make_client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
        config=_config,
    )


s3 = _make_client(S3_ENDPOINT)
s3_public = _make_client(S3_PUBLIC_ENDPOINT)


def create_download_url(object_key: str, filename: str, expires: int) -> str:
    return s3_public.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": object_key,
            "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
        ExpiresIn=expires,
    )
